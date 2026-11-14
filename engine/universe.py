"""Phase 2: daily trading universe, versioned contract registry, trade restrictions.

  python3 -m engine.universe [--date YYYY-MM-DD] [--no-refresh]   refresh (idempotent) + report

Storage: <root>/universe.sqlite across dates; raw NSE source bytes in <root>/<date>/reference/; the
master itself stays in <root>/<date>/instruments.csv.gz (shared with the recorder).
Registry rows are versioned: one row per (token, first_seen_date). A changed attribute (lot size, a
reused token, ...) starts a new row, so a past date resolves to the mapping valid on that date.
Lot sizes, expiries, strikes and tokens come only from the master (F-INST-1..3); constituents, the ban
list and holidays only from the NSE sources in config (F-NSE-2..5). Unverified => not tradable.
"""

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from . import sources
from .config import EngineConfig, load_config
from .provider import parse_master

IST = ZoneInfo("Asia/Kolkata")
ATTRS = ("underlying", "tradingsymbol", "instrument_type", "expiry", "strike", "lot_size", "tick_size",
         "segment", "exchange", "exchange_token")
WARNINGS = {"STALE_CONSTITUENTS"}  # reported, but do not make a contract untradable
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS master_dates (date TEXT PRIMARY KEY, fetched_ts TEXT, sha256 TEXT, rows INTEGER);
CREATE TABLE IF NOT EXISTS contracts (token INTEGER, first_seen_date TEXT, last_seen_date TEXT,
  {", ".join(a + " TEXT" for a in ATTRS)}, PRIMARY KEY (token, first_seen_date));
CREATE INDEX IF NOT EXISTS contracts_und ON contracts (underlying, last_seen_date);
CREATE TABLE IF NOT EXISTS master_diff (date TEXT, kind TEXT, token INTEGER, tradingsymbol TEXT, underlying TEXT,
  old TEXT, new TEXT);
CREATE TABLE IF NOT EXISTS fetches (date TEXT, source TEXT, url TEXT, fetched_ts TEXT, ok INTEGER, sha256 TEXT,
  detail TEXT);
CREATE TABLE IF NOT EXISTS constituents (fetch_date TEXT, index_name TEXT, symbol TEXT,
  PRIMARY KEY (fetch_date, index_name, symbol));
CREATE TABLE IF NOT EXISTS ban_dates (trade_date TEXT PRIMARY KEY, fetched_ts TEXT);
CREATE TABLE IF NOT EXISTS bans (trade_date TEXT, symbol TEXT, PRIMARY KEY (trade_date, symbol));
"""


@dataclass(frozen=True)
class Contract:
    token: int
    underlying: str
    family: str          # 'INDEX' | 'STOCK'
    tradingsymbol: str
    instrument_type: str  # FUT / CE / PE, or EQ for the spot row
    expiry: date | None
    strike: Decimal | None  # options only
    lot_size: int
    tick_size: Decimal
    segment: str
    exchange: str
    active: bool         # listed in that day's master and not past expiry
    first_seen_date: date
    last_seen_date: date


@dataclass(frozen=True)
class Member:
    underlying: str
    family: str
    spot_token: int
    future_tokens: tuple[int, ...]  # every active expiry, nearest first
    indices: tuple[str, ...]        # constituent lists it came from; () for the INDEX family


@dataclass(frozen=True)
class Universe:
    date: date
    flags: tuple[str, ...]          # NO_MASTER / STALE_CONSTITUENTS / BLOCKED_STALE_CONSTITUENTS / BLOCKED_NO_CONSTITUENTS
    constituents_date: date | None  # oldest of the constituent lists used
    members: tuple[Member, ...]
    excluded: tuple[tuple[str, str], ...]  # (underlying, reason)

    def by_family(self) -> dict[str, int]:
        return dict(collections.Counter(m.family for m in self.members))


# ---------------------------------------------------------------- pure
def registry_rows(master: list[Mapping[str, str]], index_spots: Mapping[str, str]) -> dict[int, tuple]:
    """Master rows the registry keeps -> {token: ATTRS}: every NFO contract plus each NFO underlying's spot row
    (stock: NSE tradingsymbol == NFO name; index: config universe.index_spots; F-INST-5)."""
    nfo_names = {r["name"] for r in master if r["exchange"] == "NFO"}
    index_of = {spot: name for name, spot in index_spots.items()}
    out = {}
    for r in master:
        if r["exchange"] == "NFO":
            und = r["name"]
        elif r["exchange"] == "NSE" and r["segment"] == "NSE" and r["tradingsymbol"] in nfo_names:
            und = r["tradingsymbol"]
        elif r["exchange"] == "NSE" and r["segment"] == "INDICES" and r["tradingsymbol"] in index_of:
            und = index_of[r["tradingsymbol"]]
        else:
            continue
        out[int(r["instrument_token"])] = (und, r["tradingsymbol"], r["instrument_type"], r["expiry"] or None,
                                           r["strike"], r["lot_size"], r["tick_size"], r["segment"], r["exchange"],
                                           r["exchange_token"])
    return out


def near_futures(rows: Mapping[int, tuple], day: date) -> dict[str, tuple[int, str]]:
    """{underlying: (token, tradingsymbol)} of the earliest FUT expiry >= day."""
    best: dict[str, tuple] = {}
    for tok, a in rows.items():
        if a[2] == "FUT" and a[3] and date.fromisoformat(a[3]) >= day and (a[0] not in best or a[3] < best[a[0]][0]):
            best[a[0]] = (a[3], tok, a[1])
    return {u: (t, s) for u, (_, t, s) in best.items()}


def build_universe(constituents: Mapping[str, list[str]], contracts: list[Contract],
                   index_names: set[str]) -> tuple[tuple[Member, ...], tuple[tuple[str, str], ...]]:
    """(members, excluded). One member per underlying, however many lists name it. F&O status is derived
    from active futures in the master, never assumed."""
    futs, spots = collections.defaultdict(list), collections.defaultdict(list)
    for c in contracts:
        if c.instrument_type == "FUT" and c.active:
            futs[c.underlying].append(c)
        elif c.exchange == "NSE":
            spots[c.underlying].append(c.token)
    wanted: dict[str, list[str]] = {n: [] for n in index_names}
    for idx in sorted(constituents):
        for s in constituents[idx]:
            wanted.setdefault(s, []).append(idx)
    members, excluded = [], []
    for u in sorted(wanted):
        if not futs[u]:
            excluded.append((u, "NO_NFO_FUTURES"))
        elif len(spots[u]) != 1:
            excluded.append((u, "NO_SPOT_IN_MASTER" if not spots[u] else "AMBIGUOUS_SPOT"))
        else:
            fts = tuple(c.token for c in sorted(futs[u], key=lambda c: c.expiry))
            members.append(Member(u, "INDEX" if u in index_names else "STOCK", spots[u][0], fts, tuple(wanted[u])))
    return tuple(members), tuple(excluded)


def strike_intervals(contracts: list[Contract], expiry: date) -> tuple[Decimal, ...]:
    """Distinct gaps between consecutive listed strikes of one expiry (derived, never assumed)."""
    ks = sorted({c.strike for c in contracts if c.expiry == expiry and c.strike is not None})
    return tuple(sorted({b - a for a, b in zip(ks, ks[1:])}))


# ---------------------------------------------------------------- registry (edge: SQLite)
class Registry:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self.index_spots: dict[str, str] = dict(cfg.get("universe.index_spots"))
        cfg.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cfg.root / "universe.sqlite", timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._universe: dict[date, Universe] = {}

    def close(self) -> None:
        self.db.close()

    # ---- writes
    def apply_master(self, d: date, master: list[Mapping[str, str]], fetched_ts: str, sha256: str) -> dict:
        """Version the registry with day d's master and log the diff against the previous master date."""
        ds = d.isoformat()
        if self.has_master(d):
            return {"date": ds, "status": "already applied"}
        last = self.db.execute("SELECT MAX(date) FROM master_dates").fetchone()[0]
        if last and last > ds:
            raise ValueError(f"master for {ds} is older than the registry's last master {last}; refusing out of order")
        new = registry_rows(master, self.index_spots)
        cols = ", ".join(ATTRS)
        prev = {r[0]: r for r in self.db.execute(
            f"SELECT token, first_seen_date, {cols} FROM contracts WHERE last_seen_date=?", (last,))} if last else {}
        extend, insert, diff = [], [], []
        for tok, a in new.items():
            p = prev.get(tok)
            if p is not None and tuple(p[2:]) == a:
                extend.append((ds, tok, p[1]))
                continue
            insert.append((tok, ds, ds, *a))
            if p is None and last:
                diff.append((ds, "added", tok, a[1], a[0], None, None))
            elif p is not None:
                diff += [(ds, f"{f}_change", tok, a[1], a[0], o, n)
                         for f, o, n in zip(ATTRS, p[2:], a) if o != n]
        for tok, p in prev.items():
            if tok not in new:
                diff.append((ds, "removed", tok, p[3], p[2], None, None))
        if last:
            old_near = near_futures({t: tuple(p[2:]) for t, p in prev.items()}, date.fromisoformat(last))
            for u, (tok, sym) in near_futures(new, d).items():
                if u in old_near and old_near[u][0] != tok:
                    diff.append((ds, "rollover", tok, sym, u, old_near[u][1], sym))
        with self.db:
            self.db.executemany("UPDATE contracts SET last_seen_date=? WHERE token=? AND first_seen_date=?", extend)
            self.db.executemany(f"INSERT INTO contracts VALUES ({', '.join('?' * (3 + len(ATTRS)))})", insert)
            self.db.executemany("INSERT INTO master_diff VALUES (?,?,?,?,?,?,?)", diff)
            self.db.execute("INSERT INTO master_dates VALUES (?,?,?,?)", (ds, fetched_ts, sha256, len(new)))
        self._universe.pop(d, None)
        kinds = collections.Counter(k for _, k, *_ in diff)
        return {"date": ds, "previous": last, "registered": len(new), "diff": dict(kinds) or ("baseline" if not last else {})}

    def log_fetch(self, d: date, source: str, url: str, fetched_ts: str, ok: bool, sha256: str | None, detail: str):
        with self.db:
            self.db.execute("INSERT INTO fetches VALUES (?,?,?,?,?,?,?)",
                            (d.isoformat(), source, url, fetched_ts, int(ok), sha256, detail))

    def fetched_ok(self, d: date, source: str) -> bool:
        return self.db.execute("SELECT 1 FROM fetches WHERE date=? AND source=? AND ok=1",
                               (d.isoformat(), source)).fetchone() is not None

    def store_constituents(self, d: date, index_name: str, symbols: list[str]) -> str:
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO constituents VALUES (?,?,?)",
                                [(d.isoformat(), index_name, s) for s in symbols])
        self._universe.pop(d, None)
        return f"{len(symbols)} symbols"

    def store_ban(self, trade_date: date, symbols: list[str], fetched_ts: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO ban_dates VALUES (?,?)", (trade_date.isoformat(), fetched_ts))
            self.db.executemany("INSERT OR IGNORE INTO bans VALUES (?,?)", [(trade_date.isoformat(), s) for s in symbols])

    # ---- reads
    def has_master(self, d: date) -> bool:
        return self.db.execute("SELECT 1 FROM master_dates WHERE date=?", (d.isoformat(),)).fetchone() is not None

    def _contracts(self, d: date, where: str = "", args: tuple = ()) -> list[Contract]:
        if not self.has_master(d):
            return []
        ds = d.isoformat()
        rows = self.db.execute(f"SELECT token, first_seen_date, last_seen_date, {', '.join(ATTRS)} FROM contracts "
                               f"WHERE first_seen_date<=? AND last_seen_date>=? {where}", (ds, ds, *args))
        return [self._contract(r, d) for r in rows]

    def _contract(self, r, d: date) -> Contract:
        tok, first, last, und, sym, typ, exp, strike, lot, tick, seg, exch, _ = r
        expiry = date.fromisoformat(exp) if exp else None
        return Contract(tok, und, "INDEX" if und in self.index_spots else "STOCK", sym, typ, expiry,
                        Decimal(strike) if typ in ("CE", "PE") else None, int(lot), Decimal(tick), seg, exch,
                        expiry is None or expiry >= d, date.fromisoformat(first), date.fromisoformat(last))

    def get_contract(self, token: int, d: date) -> Contract | None:
        """The mapping of `token` valid on d (None if d has no master or the token was not listed that day)."""
        hits = self._contracts(d, "AND token=?", (token,))
        return hits[0] if hits else None

    def get_contracts(self, underlying: str, d: date) -> list[Contract]:
        """Active NFO contracts (FUT/CE/PE) of `underlying` on d, by type, expiry, strike."""
        cs = [c for c in self._contracts(d, "AND underlying=? AND exchange='NFO'", (underlying,)) if c.active]
        return sorted(cs, key=lambda c: (c.instrument_type, c.expiry, c.strike or 0))

    def constituents(self, d: date) -> dict[str, tuple[date, list[str]]]:
        """{index: (fetch_date, symbols)} of the latest successful fetch on or before d."""
        out = {}
        for idx in self.cfg.get("universe.indices"):
            got = self.db.execute("SELECT MAX(fetch_date) FROM constituents WHERE index_name=? AND fetch_date<=?",
                                  (idx, d.isoformat())).fetchone()[0]
            if got:
                syms = [s for (s,) in self.db.execute(
                    "SELECT symbol FROM constituents WHERE index_name=? AND fetch_date=? ORDER BY symbol", (idx, got))]
                out[idx] = (date.fromisoformat(got), syms)
        return out

    def get_universe(self, d: date) -> Universe:
        if d in self._universe:
            return self._universe[d]
        if not self.has_master(d):
            return Universe(d, ("NO_MASTER",), None, (), ())
        cons = self.constituents(d)
        flags = []
        if len(cons) < len(self.cfg.get("universe.indices")):
            flags.append("BLOCKED_NO_CONSTITUENTS")
        oldest = min((fd for fd, _ in cons.values()), default=None)
        if oldest is not None and oldest < d:
            age = (d - oldest).days
            flags.append("BLOCKED_STALE_CONSTITUENTS" if age > self.cfg.get("universe.constituents_max_age_days")
                         else "STALE_CONSTITUENTS")
        members, excluded = build_universe({i: s for i, (_, s) in cons.items()}, self._contracts(d), set(self.index_spots))
        u = self._universe[d] = Universe(d, tuple(flags), oldest, members, excluded)
        return u

    def restriction_reasons(self, d: date, derivative: bool, underlying: str) -> list[str]:
        r = self.cfg.get("restrictions")
        out = []
        missing = [c["ref"] for c in r["holiday_circulars"] if not self.fetched_ok(d, f"holiday:{c['ref']}")]
        if d.year not in r["holiday_years"]:
            out.append(f"RESTRICTION_UNVERIFIED:holidays (no verified circular for {d.year})")
        elif missing:
            out.append(f"RESTRICTION_UNVERIFIED:holidays (not re-verified on {d}: {', '.join(missing)})")
        elif any(h["date"] == d for h in r["holidays"]):
            out.append("HOLIDAY")
        elif any(s["date"] == d for s in r["special_sessions"]):
            out.append("RESTRICTION_UNVERIFIED:special_session")
        elif d.weekday() >= 5:
            out.append("RESTRICTION_UNVERIFIED:weekend (weekend sessions not verified, Q-NSE-5)")
        if derivative:
            ds = d.isoformat()
            if not self.db.execute("SELECT 1 FROM ban_dates WHERE trade_date=?", (ds,)).fetchone():
                out.append(f"RESTRICTION_UNVERIFIED:ban_list (none fetched for trade date {ds})")
            elif self.db.execute("SELECT 1 FROM bans WHERE trade_date=? AND symbol=?", (ds, underlying)).fetchone():
                out.append("BANNED")
        return out

    def is_tradable(self, token: int, d: date) -> tuple[bool, list[str]]:
        u = self.get_universe(d)
        if "NO_MASTER" in u.flags:
            return False, ["NO_MASTER"]
        c = self.get_contract(token, d)
        if c is None:
            return False, ["NOT_IN_MASTER"]
        reasons = [] if c.active else ["EXPIRED"]
        if c.underlying not in {m.underlying for m in u.members}:
            reasons.append("NOT_IN_UNIVERSE")
        if c.family == "STOCK":  # owner decision Q-UNI-2: INDEX doesn't depend on the constituent lists
            reasons += list(u.flags)
        reasons += self.restriction_reasons(d, c.exchange == "NFO", c.underlying)
        return all(r in WARNINGS for r in reasons), reasons

    def report(self, d: date) -> dict:
        u = self.get_universe(d)
        diff = collections.Counter(k for (k,) in self.db.execute("SELECT kind FROM master_diff WHERE date=?",
                                                                    (d.isoformat(),)))
        fetches = [dict(zip(("source", "url", "fetched_ts", "ok", "detail"), r)) for r in self.db.execute(
            "SELECT source, url, fetched_ts, ok, detail FROM fetches WHERE date=? ORDER BY rowid", (d.isoformat(),))]
        banned = [s for (s,) in self.db.execute("SELECT symbol FROM bans WHERE trade_date=?", (d.isoformat(),))]
        return {"date": d.isoformat(), "flags": list(u.flags),
                "constituents_date": u.constituents_date and u.constituents_date.isoformat(),
                "universe_count": len(u.members), "by_family": u.by_family(),
                "excluded": [list(e) for e in u.excluded],
                "restrictions_for_derivatives": self.restriction_reasons(d, True, ""), "banned": banned,
                "master_diff": dict(diff), "fetches": fetches}


# ---------------------------------------------------------------- refresh (edge)
def refresh(cfg: EngineConfig, d: date, master_csv: bytes, fetch: Callable[[str], bytes] | None = None,
            now: Callable[[], datetime] = lambda: datetime.now(IST)) -> dict:
    """Daily pre-open job, idempotent: version the master, then fetch every NSE source not yet fetched OK
    today. A failed source is logged (fetches.ok=0) and retried on the next call; it never raises."""
    fetch = fetch or (lambda url: sources.fetch(url, cfg.get("http.user_agent"), cfg.get("http.timeout_s")))
    reg = Registry(cfg)
    ts = lambda: now().isoformat(timespec="seconds")  # noqa: E731
    out = {"master": reg.apply_master(d, parse_master(master_csv), ts(), hashlib.sha256(master_csv).hexdigest())}
    ref_dir = cfg.root / d.isoformat() / "reference"

    def attempt(source: str, url: str, handle: Callable[[bytes, str], str]) -> str:
        if reg.fetched_ok(d, source):
            return "already fetched OK today"
        at, raw, sha = ts(), None, None
        try:
            raw = fetch(url)
            sha = hashlib.sha256(raw).hexdigest()
            ref_dir.mkdir(parents=True, exist_ok=True)
            (ref_dir / f"{source.replace(':', '_').replace('/', '_')}.{at.replace(':', '')}").write_bytes(raw)
            detail, ok = handle(raw, at), True
        except Exception as e:  # logged as unverified, never filled in
            detail, ok = f"{type(e).__name__}: {e}", False
        reg.log_fetch(d, source, url, at, ok, sha, detail)
        return ("OK " if ok else "FAILED ") + detail

    for idx, url in cfg.get("universe.indices").items():
        out[f"constituents:{idx}"] = attempt(f"constituents:{idx}", url,
                                             lambda raw, at, idx=idx: reg.store_constituents(d, idx, sources.parse_constituents(raw)))

    def ban(raw: bytes, at: str) -> str:
        trade_date, syms = sources.parse_ban(raw)
        reg.store_ban(trade_date, syms, at)
        if trade_date != d:
            raise ValueError(f"file is for trade date {trade_date}, not {d} (stored for {trade_date})")
        return f"trade date {trade_date}: {syms}"

    out["ban_list"] = attempt("ban_list", cfg.get("restrictions.ban_list_url"), ban)

    for c in cfg.get("restrictions.holiday_circulars"):
        def check(raw: bytes, at: str, c=c) -> str:
            if hashlib.sha256(raw).hexdigest() != c["sha256"]:
                raise ValueError(f"{c['ref']} sha256 changed since verification; re-verify the holiday list")
            return "sha256 matches the verified circular"
        out[f"holiday:{c['ref']}"] = attempt(f"holiday:{c['ref']}", c["url"], check)
    reg.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.universe")
    ap.add_argument("--config", default=None)
    ap.add_argument("--date", default=None, help="IST trading date (default: today)")
    ap.add_argument("--no-refresh", action="store_true", help="report only")
    a = ap.parse_args(argv)
    cfg = load_config(a.config) if a.config else load_config()
    d = date.fromisoformat(a.date) if a.date else datetime.now(IST).date()
    if not a.no_refresh:
        if d != datetime.now(IST).date() and not (cfg.root / d.isoformat() / "instruments.csv.gz").exists():
            print(f"[engine.universe] no stored master for {d}; only today's master can be downloaded", file=sys.stderr)
            return 1
        from .broker import KiteSession, TokenExpired
        from .recorder import _master
        try:
            master = _master(KiteSession.load(), cfg.root / d.isoformat())
        except TokenExpired as e:
            print(f"[engine.universe] {e}", file=sys.stderr)
            return 2
        print(json.dumps(refresh(cfg, d, master), indent=2))
    reg = Registry(cfg)
    rep = reg.report(d)
    reg.close()
    print(json.dumps(rep, indent=2))
    return 0 if "NO_MASTER" not in rep["flags"] else 1


if __name__ == "__main__":
    sys.exit(main())
