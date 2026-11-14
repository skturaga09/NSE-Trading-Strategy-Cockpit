"""Raw market recorder: KiteTicker -> bounded queue -> writer thread -> DayStore.

The WebSocket callbacks only timestamp and enqueue (never block, never touch disk). A full queue
drops the frame and the drop is written as a `queue_drop` gap — never silent. Connection events go
through a separate unbounded deque so they are never dropped. Gaps are rows in `gaps`; nothing is
ever synthesised to fill them.

CLI:  python3 -m engine.recorder [--until 15:45] [--refresh] [--config config/engine/v2.yaml]
"""

import argparse
import collections
import fcntl
import gzip
import json
import queue
import shutil
import signal
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from .alerts import alert_once
from .config import EngineConfig, load_config
from .packets import decode, packet_count, split_frame
from .store import DayStore, Event, conn_event, depth_event, gap_event, tick_event

IST = ZoneInfo("Asia/Kolkata")
GB = 1e9


def _stderr_alert(msg: str) -> None:
    print(f"[engine.recorder] ALERT {msg}", file=sys.stderr, flush=True)


class Recorder:
    def __init__(self, cfg: EngineConfig, store: DayStore, consumers: Iterable[Callable[[Event], None]] = (),
                 clock_ns: Callable[[], int] = time.time_ns, disk_free: Callable[[], int] | None = None,
                 alert: Callable[[str], None] = _stderr_alert, symbols: dict[int, str] | None = None,
                 on_idle: Callable[[int], None] | None = None):
        self.cfg, self.store, self.consumers, self.clock_ns, self.alert = cfg, store, list(consumers), clock_ns, alert
        self.on_idle = on_idle  # Phase 3: called with clock_ns() at each status interval while the queue is empty
        self.disk_free = disk_free or (lambda: shutil.disk_usage(store.dir).free)
        self.symbols = symbols or {}
        self.q: queue.Queue = queue.Queue(maxsize=cfg.get("writer.queue_max"))
        self.control: collections.deque = collections.deque()
        self._seq: dict[int, int] = collections.defaultdict(int)
        self._drop_lock = threading.Lock()
        self._drop = [0, None, None]          # count, first_ns, last_ns since last flush
        self.dropped_total = 0
        # writer-thread state
        self._last_sig: dict[int, tuple] = {}
        self._last_depth: dict[int, tuple] = {}
        self._last_depth_ns: dict[int, int] = {}
        self._oi: dict[int, int] = {}
        self._inst: dict[int, dict] = {}
        self._open_disconnect: dict[int, tuple[int, str]] = {}
        self.conn_state: dict[int, str] = {}
        self._shutting_down: set[int] = set()
        self._rate = (0, 0)  # (ns, packets) at last status write
        self.degraded = {"depth": None, "ticks": None}   # start_ns while degraded
        self._degraded_skipped = {"depth": 0, "ticks": 0}
        self._alerted = False
        self.gaps_written = 0
        self.counts = collections.Counter()
        self._running = False
        self._thread: threading.Thread | None = None
        self.unclean_stop_ns: int | None = None
        self.last_frame_ns: dict[int, int] = {}   # per connection, heartbeats included (stall watchdog)
        self.max_frame_gap_ns: dict[int, int] = {}
        self._connected_ns: dict[int, int] = {}
        self._stalled: set[int] = set()

    def resume(self) -> int:
        """Call before connecting. If this day already has data from an earlier process, record the
        time in between as a `restart` gap and return a connection id not used yet today.
        Sets `unclean_stop_ns` when the earlier process never logged a shutdown (crash, kill, sleep)."""
        db = self.store.db
        last, self.unclean_stop_ns = last_run_end(db)
        if last is not None:
            self._gap(last, self.clock_ns(), -1, "restart", "recorder process restarted; nothing recorded in between", None)
            self.store.commit()
        return db.execute("SELECT COALESCE(MAX(conn), -1) + 1 FROM events WHERE conn >= 0").fetchone()[0]

    # ---- callback side (WebSocket thread): timestamp + enqueue only ----
    def on_message(self, conn: int, payload: bytes, is_binary: bool) -> None:
        rns = self.clock_ns()
        prev = self.last_frame_ns.get(conn)
        if prev is not None and rns - prev > self.max_frame_gap_ns.get(conn, 0):
            self.max_frame_gap_ns[conn] = rns - prev
        self.last_frame_ns[conn] = rns
        if not is_binary:
            self.control.append((rns, conn, "text", payload.decode("utf-8", "replace")))
            return
        n = packet_count(payload)
        if n == 0:
            return  # 1-byte heartbeat
        seq = self._seq[conn]
        self._seq[conn] = seq + n
        try:
            self.q.put_nowait((rns, conn, seq, payload))
        except queue.Full:
            with self._drop_lock:
                d = self._drop
                d[0] += n
                d[1] = rns if d[1] is None else d[1]
                d[2] = rns

    def on_conn_event(self, conn: int, kind: str, detail) -> None:
        self.control.append((self.clock_ns(), conn, kind, json.dumps(detail, default=str, sort_keys=True)))

    def check_stall(self, conns: Iterable[int], now: int) -> list[int]:
        """Connections that claim 'connected' but sent no frame (heartbeats count) for ws.stall_after_s.
        Each is logged once as a 'stall' event + gap from its last frame; the caller force-closes the socket."""
        limit = int(self.cfg.get("ws.stall_after_s") * 1e9)
        out = []
        for c in conns:
            last = max(self.last_frame_ns.get(c, 0), self._connected_ns.get(c, 0))
            if self.conn_state.get(c) == "connected" and c not in self._stalled and last and now - last >= limit:
                self._stalled.add(c)
                self.control.append((now, c, "stall", json.dumps({"last_frame_ns": last})))
                out.append(c)
        return out

    # ---- writer side ----
    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="engine-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join()
        else:
            self.drain()
        now = self.clock_ns()
        for conn, (start, reason) in list(self._open_disconnect.items()):
            self._gap(start, now, conn, "disconnect", f"session ended while disconnected ({reason})", None)
        self._open_disconnect.clear()
        for what in ("depth", "ticks"):
            self._end_degrade(what, now)
        self._write_status(now)
        self.store.commit()

    def drain(self) -> None:
        """Process everything queued (single-threaded use and tests)."""
        self._control()
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            self._frame(*item)
        self._control()
        self._flush_drops()
        self.store.commit()

    def _loop(self) -> None:
        flush, status = self.cfg.get("writer.flush_interval_s"), self.cfg.get("writer.status_interval_s")
        check = self.cfg.get("disk_guard.check_interval_s")
        t_flush = t_status = t_disk = 0.0
        self._disk_check()
        while self._running or not self.q.empty() or self.control:
            self._control()
            try:
                self._frame(*self.q.get(timeout=min(flush, status)))
            except queue.Empty:
                pass
            mono = time.monotonic()
            if mono - t_disk >= check:
                self._disk_check()
                t_disk = mono
            if mono - t_flush >= flush:
                self._flush_drops()
                self.store.commit()
                t_flush = mono
            if mono - t_status >= status:
                self._write_status(self.clock_ns())
                t_status = mono
                if self.on_idle and self.q.empty():
                    self.on_idle(self.clock_ns())
        self._control()
        self._flush_drops()

    def _control(self) -> None:
        while self.control:
            rns, conn, kind, detail = self.control.popleft()
            self._event((rns, conn, kind, detail))
            if kind == "shutdown":
                self._shutting_down.add(conn)
                self.conn_state[conn] = "shutdown"
            elif kind in ("close", "error", "noreconnect") and conn not in self._shutting_down:
                self.conn_state[conn] = kind
                self._open_disconnect.setdefault(conn, (rns, f"{kind}: {detail}"))
            elif kind == "stall":
                self._gap(json.loads(detail)["last_frame_ns"], rns, conn, "stall",
                          f"no frame for {self.cfg.get('ws.stall_after_s')} s on a connected socket; force-closed", None)
            elif kind == "connect":
                self.conn_state[conn] = "connected"
                self._connected_ns[conn] = rns
                self._stalled.discard(conn)
                if conn in self._open_disconnect:
                    start, reason = self._open_disconnect.pop(conn)
                    self._gap(start, rns, conn, "disconnect", reason, None)

    def _event(self, row: tuple) -> None:
        self.store.insert("events", [row])
        self._deliver(conn_event(row))

    def _gap(self, start, end, conn, kind, reason, count) -> None:
        row = (start, end, conn, kind, reason, count)
        self.store.insert("gaps", [row])
        self.gaps_written += 1
        self._deliver(gap_event(row))

    def _deliver(self, e: Event) -> None:
        for c in self.consumers:
            c(e)

    def _flush_drops(self) -> None:
        with self._drop_lock:
            n, first, last = self._drop
            self._drop = [0, None, None]
        if n:
            self.dropped_total += n
            self._gap(first, last, -1, "queue_drop", f"writer queue full (max {self.q.maxsize} frames)", n)

    def _frame(self, rns: int, conn: int, seq_first: int, payload: bytes) -> None:
        self.counts["frames"] += 1
        ticks_off, depth_off = self.degraded["ticks"] is not None, self.degraded["depth"] is not None
        if not ticks_off:
            self.store.write_frame(rns, conn, seq_first, payload)
        ticks, depths, ois, out = [], [], [], []
        min_depth_ns = int(self.cfg.get("depth_min_interval_s") * 1e9)
        for i, pkt in enumerate(split_frame(payload)):
            seq = seq_first + i
            tok, ex, f, depth = decode(pkt)
            self.counts["packets"] += 1
            st = self._inst.setdefault(tok, {"packets": 0})
            st.update(packets=st["packets"] + 1, last_receive_ns=rns, last_exchange_ts=ex)
            if f["oi"] is not None and self._oi.get(tok) != f["oi"]:
                ois.append((tok, ex, rns, conn, seq, f["oi"], self._oi.get(tok)))
                self._oi[tok] = f["oi"]
            if ticks_off:
                self._degraded_skipped["ticks"] += 1
            else:
                sig = tuple(v for k, v in f.items() if k != "last_trade_ts")  # step 9: ignore timestamp-only changes
                if self._last_sig.get(tok) != sig:
                    self._last_sig[tok] = sig
                    ticks.append((rns, conn, seq, tok, ex, *f.values()))
                else:
                    self.counts["ticks_unchanged_skipped"] += 1
            if depth is None:
                continue
            if ticks_off or depth_off:
                self._degraded_skipped["depth"] += 1
            elif depth != self._last_depth.get(tok) and rns - self._last_depth_ns.get(tok, -min_depth_ns) >= min_depth_ns:
                self._last_depth[tok], self._last_depth_ns[tok] = depth, rns
                depths.append((rns, conn, seq, tok, ex, *depth))
        self.store.insert("ticks", ticks)
        self.store.insert("depth", depths)
        self.store.insert("oi_changes", ois)
        self.counts["ticks_written"] += len(ticks)
        if self.consumers:
            for e in [tick_event(r) for r in ticks] + [depth_event(r) for r in depths]:
                self._deliver(e)

    # ---- disk guard (step 11) ----
    def _disk_check(self) -> None:
        free_gb = self.disk_free() / GB
        now = self.clock_ns()
        g = lambda k: self.cfg.get(f"disk_guard.{k}")  # noqa: E731
        low = free_gb < g("alert_below_gb")
        if low and not self._alerted:
            self._event((now, -1, "disk_alert", json.dumps({"free_gb": round(free_gb, 3)})))
            self.alert(f"disk free {free_gb:.2f} GB < {g('alert_below_gb')} GB")
        self._alerted = low
        for what, limit in (("depth", g("stop_depth_below_gb")), ("ticks", g("stop_ticks_below_gb"))):
            if free_gb < limit and self.degraded[what] is None:
                self.degraded[what] = now
                self._degraded_skipped[what] = 0
                self._event((now, -1, f"disk_stop_{what}", json.dumps({"free_gb": round(free_gb, 3)})))
                self.alert(f"disk free {free_gb:.2f} GB < {limit} GB: stopped writing {what}")
            elif free_gb >= limit:
                self._end_degrade(what, now)

    def _end_degrade(self, what: str, now: int) -> None:
        start = self.degraded[what]
        if start is not None:
            self._gap(start, now, -1, f"disk_{what}", "disk guard: free space below threshold",
                      self._degraded_skipped[what])
            self.degraded[what] = None

    # ---- health (step 5) ----
    def status(self, now: int) -> dict:
        return {
            "ts_ns": now, "config_version": self.cfg.version, "counts": dict(self.counts),
            "ticks_per_s": round(getattr(self, "ticks_per_s", 0.0), 2),
            "queue_depth": self.q.qsize(), "queue_max": self.q.maxsize, "dropped_total": self.dropped_total,
            "gaps_today": self.gaps_written + len(self._open_disconnect)
                          + sum(v is not None for v in self.degraded.values()),
            "connections": self.conn_state,
            "max_frame_gap_s": {str(c): round(v / 1e9, 3) for c, v in self.max_frame_gap_ns.items()},
            "degraded": {k: v is not None for k, v in self.degraded.items()},
            "instruments": {str(t): {**s, "symbol": self.symbols.get(t, "?")} for t, s in self._inst.items()},
        }

    def _write_status(self, now: int) -> None:
        t0, n0 = self._rate
        n = self.counts["packets"]
        self.ticks_per_s = (n - n0) / ((now - t0) / 1e9) if t0 and now > t0 else 0.0
        self._rate = (now, n)
        p = self.store.dir / "status.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status(now)))
        tmp.replace(p)


def last_run_end(db) -> tuple[int | None, int | None]:
    """-> (last receive_ns recorded today, same value again if that run never logged a clean shutdown)."""
    last = db.execute("SELECT MAX(m) FROM (SELECT MAX(receive_ns) m FROM ticks UNION ALL "
                      "SELECT MAX(receive_ns) FROM events)").fetchone()[0]
    last_connect, last_shutdown = db.execute(
        "SELECT MAX(CASE WHEN kind='connect' THEN receive_ns END), "
        "MAX(CASE WHEN kind='shutdown' THEN receive_ns END) FROM events").fetchone()
    return last, (last if last is not None and (last_shutdown or -1) < (last_connect or 0) else None)


# ---------------------------------------------------------------- live edge
def _master(session, day_dir: Path) -> bytes:
    p = day_dir / "instruments.csv.gz"
    if p.exists():
        return gzip.decompress(p.read_bytes())
    raw = session.instruments_csv()
    day_dir.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(raw))
    tmp.replace(p)
    return raw


def acquire_lock(root: Path):
    """One recorder per storage root. Returns the open lock file (keep it referenced) or None if held."""
    root.mkdir(parents=True, exist_ok=True)
    f = open(root / "recorder.lock", "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except BlockingIOError:
        f.close()
        return None


class TierExecutor:
    """Runs TierBook plans on the live connections (Phase 3). A plan change becomes a 'tier_plan' event
    ({token: [mode, tiers, kind, underlying]} + usage per tier), a newly dropped request a 'tier_drop'
    event, and each op sent a 'tier_ops' event. Ops for a slot that is not connected wait for the next
    step, because a KiteTicker send while it is down closes the socket (ticker.py subscribe)."""

    def __init__(self, rec: "Recorder", book, cfg: EngineConfig, open_slot: Callable[[int], None],
                 send: Callable[[int, str, str | None, tuple], None], connected: Callable[[int], bool]):
        self.rec, self.book, self.open_slot, self.send, self.connected = rec, book, open_slot, send, connected
        self.per, self.most = cfg.get("ws.max_tokens_per_connection"), cfg.get("ws.max_connections")
        self.applied: dict[int, dict[int, str]] = {}
        self.last = None
        self._dropped: set[tuple[int, str]] = set()

    def step(self):
        from .tiers import assign
        plan = self.book.plan()
        if self.last is None or (plan.subs, plan.meta) != (self.last.subs, self.last.meta):
            self.rec.on_conn_event(-1, "tier_plan", {"plan": {str(t): [m, *plan.meta[t]] for t, m in sorted(plan.subs.items())},
                                                     "usage": plan.usage})
        for tok, tier, reason in plan.dropped:
            if (tok, tier) not in self._dropped:
                self._dropped.add((tok, tier))
                self.rec.on_conn_event(-1, "tier_drop", {"token": tok, "tier": tier, "reason": reason})
        self.last = plan
        for slot, op, mode, toks in assign(plan.subs, self.applied, self.per, self.most)[1]:
            if op == "open":
                self.open_slot(slot)
                self.applied[slot] = {}
                continue
            if not self.connected(slot):
                continue
            self.send(slot, op, mode, toks)
            a = self.applied[slot]
            if op == "unsubscribe":
                for t in toks:
                    a.pop(t, None)
            else:
                a.update(dict.fromkeys(toks, "quote" if op == "subscribe" else mode))  # KiteTicker subscribes in quote
            self.rec.on_conn_event(-1, "tier_ops", {"slot": slot, "op": op, "mode": mode, "tokens": list(toks)})
        return plan


def previous_session(root: Path, today) -> tuple[str | None, list[str], dict]:
    """Planner inputs from the latest recorded day before `today` (Phases 4-6 are batch, Q-4-6, so no live setups exist):
    (day, underlyings by Phase 6 setup count, {underlying: [LevelMap level paise at that day's end]})."""
    from .structure import Detection, levels_at
    days = sorted(p.name for p in root.iterdir() if p.is_dir() and len(p.name) == 10 and p.name < today.isoformat()
                  and (p / "opportunity.sqlite").exists())
    if not days:
        return None, [], {}
    d = root / days[-1]
    with sqlite3.connect(f"file:{d / 'opportunity.sqlite'}?mode=ro", uri=True) as db:
        v = db.execute("SELECT max(config_version) FROM setups").fetchone()[0]
        ranked = [u for u, _ in db.execute("SELECT underlying, count(*) n FROM setups WHERE config_version=? "
                                           "GROUP BY underlying ORDER BY n DESC, underlying", (v,))]
    levels = {}
    if (d / "structure.sqlite").exists():
        with sqlite3.connect(f"file:{d / 'structure.sqlite'}?mode=ro", uri=True) as db:
            v = db.execute("SELECT max(config_version) FROM structure_detections").fetchone()[0]
            dets = {}
            for (p,) in db.execute("SELECT payload FROM structure_detections WHERE config_version=?", (v,)):
                j = json.loads(p)
                dets.setdefault(j["underlying"], []).append(Detection(**{**j, "source": tuple(j["source"])}))
        levels = {u: [lv for _, _, lv, _ in levels_at(ds, max(x.confirmed_ts for x in ds)) if lv] for u, ds in dets.items()}
    return days[-1], ranked, levels


def start_tier_c_planner(cfg, session, universe, book, day, day_dir: Path, stop: threading.Event,
                         make_registry=None, clock_ns=time.time_ns) -> threading.Thread:
    """The tier C planner thread. It opens its OWN registry: sqlite3 objects may not cross threads, and borrowing the
    main thread's registry made every run fail (the Muhurat session recorded no option)."""
    def loop():
        from .universe import Registry
        reg = (make_registry or Registry)(cfg)
        planner = TierCPlanner(cfg, session, reg, universe, book, day, day_dir, clock_ns)
        try:
            while not stop.is_set():
                try:
                    p = planner.run_once()
                    print(json.dumps({k: p[k] for k in ("planned", "scanned", "cap")} | {"dropped": len(p["dropped"])}), flush=True)
                except Exception as e:  # noqa: BLE001  tier C is optional: futures recording must go on
                    print(f"[engine.recorder] tier C planner failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                stop.wait(cfg.get("options.planner.replan_interval_min") * 60)
        finally:
            db = getattr(reg, "db", None)
            if db is not None:
                db.close()
    t = threading.Thread(target=loop, name="tier-c-planner", daemon=True)
    t.start()
    return t


class TierCPlanner:
    """Phase 11 tier C feeder (D-51): every `options.planner.replan_interval_min`, a read-only REST `/quote` scan of
    each underlying's spot and ATM +/- scan_strikes chain, then `engine.options.plan_tier_c` -> TierBook.promote(tier C)
    with a TTL of two intervals (unplanned tokens are demoted). Underlyings: INDEX family, then the previous session's
    setup underlyings, then the rest by scanned ATM option volume. The plan and its drops go to `<day>/tier_c_plan.json`."""

    def __init__(self, cfg, session, registry, universe, book, day, day_dir: Path, clock_ns=time.time_ns):
        self.cfg, self.session, self.reg, self.universe, self.book = cfg, session, registry, universe, book
        self.day, self.day_dir, self.clock_ns = day, day_dir, clock_ns
        self.first_oi: dict[int, int] = {}
        self.planned: set[int] = set()
        self.prev_day, self.ranked, self.levels = previous_session(cfg.root, day)

    def _quotes(self, contracts) -> dict:
        from .options import quote_from_rest
        P = self.cfg.get("options.planner")
        keys = {f"{c.exchange}:{c.tradingsymbol}": c.token for c in contracts}
        got = self.session.quote(sorted(keys), P["quote_batch"], P["quote_rate_per_s"])
        return {keys[k]: quote_from_rest(keys[k], j, rns) for k, (j, rns) in got.items() if k in keys}

    def run_once(self) -> dict:
        from .options import OPTION_KINDS, plan_tier_c
        P, members = self.cfg.get("options.planner"), self.universe.members
        spots = {m.underlying: c for m in members if (c := self.reg.get_contract(m.spot_token, self.day))}
        sq = self._quotes(list(spots.values()))
        atm = {u: q.last_price for u, c in spots.items() if (q := sq.get(c.token)) and q.last_price}
        opts, scan_set = {}, []
        for m in members:
            cs = [c for c in self.reg.get_contracts(m.underlying, self.day) if c.instrument_type in OPTION_KINDS
                  and c.expiry >= self.day]
            opts[m.underlying] = cs
            if m.underlying not in atm:
                continue
            for e in sorted({c.expiry for c in cs})[:P["expiries"] + 1]:
                ks = sorted({float(c.strike) for c in cs if c.expiry == e})
                i = min(range(len(ks)), key=lambda j: (abs(ks[j] * 100 - atm[m.underlying]), ks[j]))
                keep = set(ks[max(0, i - P["scan_strikes"]): i + P["scan_strikes"] + 1])
                scan_set += [c for c in cs if c.expiry == e and float(c.strike) in keep]
        scan = self._quotes(scan_set)
        for t, q in scan.items():
            if q.oi is not None:
                self.first_oi.setdefault(t, q.oi)

        def atm_volume(u):
            vs = [scan[c.token].volume_day or 0 for c in opts.get(u, []) if c.token in scan]
            return -sum(vs)
        index = sorted(m.underlying for m in members if m.family == "INDEX")
        setups = [u for u in self.ranked if u in opts and u not in index]
        rest = sorted((m.underlying for m in members if m.underlying not in index and m.underlying not in setups),
                      key=lambda u: (atm_volume(u), u))
        order = [(u, "INDEX") for u in index] + [(u, f"SETUPS_PREVIOUS_SESSION {self.prev_day}") for u in setups] + \
                [(u, "SCAN_ATM_VOLUME") for u in rest]
        reqs, dropped = plan_tier_c(order, opts, atm, scan, self.first_oi, self.levels, self.day, self.cfg)
        ttl = 2 * P["replan_interval_min"] * 60
        for r in reqs:
            self.book.promote(r.token, r.reason, ttl, tier="C")
        for t in self.planned - {r.token for r in reqs}:
            self.book.demote(t, tier="C")
        self.planned = {r.token for r in reqs}
        out = {"at_ns": self.clock_ns(), "config_version": self.cfg.version, "previous_session": self.prev_day,
               "scanned": len(scan), "planned": len(reqs), "cap": self.cfg.get("tiers.C.max_tokens"),
               "requests": [[r.token, r.underlying, r.kind, r.reason] for r in reqs], "dropped": dropped}
        tmp = self.day_dir / "tier_c_plan.json.tmp"
        tmp.write_text(json.dumps(out))
        tmp.replace(self.day_dir / "tier_c_plan.json")
        return out


def connections_for(subs: dict[int, str], cfg: EngineConfig) -> list[dict[int, str]]:
    per, most = cfg.get("ws.max_tokens_per_connection"), cfg.get("ws.max_connections")
    toks = sorted(subs)
    chunks = [{t: subs[t] for t in toks[i:i + per]} for i in range(0, len(toks), per)]
    if len(chunks) > most:
        raise ValueError(f"{len(toks)} tokens need {len(chunks)} connections; limit is {most} x {per} (F-WS-2)")
    return chunks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.recorder")
    ap.add_argument("--config", default=None)
    ap.add_argument("--until", default=None, help="IST HH:MM to stop (default: run until Ctrl-C/SIGTERM)")
    ap.add_argument("--refresh", action="store_true", help="on an expired token, run the existing refresh flow once")
    a = ap.parse_args(argv)
    cfg = load_config(a.config) if a.config else load_config()
    today = datetime.now(IST).date()
    if any(h["date"] == today for h in cfg.get("restrictions.holidays")):
        print(f"[engine.recorder] {today} is an exchange holiday (restrictions.holidays); nothing to record", flush=True)
        return 0
    until = None
    if a.until:
        hh, mm = map(int, a.until.split(":"))
        until = datetime.now(IST).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if datetime.now(IST) >= until:
            print(f"[engine.recorder] past --until {a.until}; nothing to do", flush=True)
            return 0
    lock = acquire_lock(cfg.root)  # noqa: F841  (held for the life of the process)
    if lock is None:
        print("[engine.recorder] another recorder holds the lock; exiting", flush=True)
        return 0
    try:
        return _record(cfg, a, until)
    except Exception as e:
        alert_once(cfg.root, f"crash:{type(e).__name__}", "Engine recorder CRASHED",
                   f"{type(e).__name__}: {e}. The 15-min launchd retry will restart it; see dashboard/logs/engine_recorder.err.log")
        raise


def _record(cfg: EngineConfig, a, until) -> int:
    from .broker import KiteSession, TokenExpired
    from .candles import Aggregator
    from .replay import day_events
    from .snapshots import Pipeline, Publisher
    from .store import arrival_key
    from .tiers import TierBook, tier_a_requests
    from .universe import Registry, refresh

    try:
        session = KiteSession.load()
        try:
            session.check()
        except TokenExpired:
            if not a.refresh:
                raise
            session = session.refresh()
            session.check()
    except TokenExpired as e:
        print(f"[engine.recorder] {e}", file=sys.stderr)
        alert_once(cfg.root, "token", "Engine recorder NOT recording: Kite token",
                   f"{e} Retrying every 15 min with whatever token kite_config.json holds.")
        return 2

    today = datetime.now(IST).date()
    day_dir = cfg.root / today.isoformat()
    print(json.dumps({"universe_refresh": refresh(cfg, today, _master(session, day_dir))}), flush=True)
    registry = Registry(cfg)
    universe = registry.get_universe(today)
    if "NO_MASTER" in universe.flags:
        raise LookupError(f"no instrument master applied to the registry for {today}")
    contract = lambda t: registry.get_contract(t, today)  # noqa: E731
    book = TierBook(cfg, time.time_ns, describe=lambda t: (c.instrument_type, c.underlying) if (c := contract(t)) else ("UNKNOWN", ""))
    book.set_tier_a(tier_a_requests(universe, contract, cfg))
    plan = book.plan()
    symbols = {t: f"{c.exchange}:{c.tradingsymbol}" for t in plan.subs if (c := contract(t))}
    trading_day = "HOLIDAY" not in registry.restriction_reasons(today, False, "")

    store = DayStore(day_dir)
    store.insert("meta", [("run_start_ns", str(time.time_ns())), ("config_version", cfg.version),
                          ("config_sha256", cfg.sha256), ("session_source", session.source),
                          ("subscriptions", json.dumps({symbols.get(t, str(t)): [t, m] for t, m in plan.subs.items()}))])
    store.commit()
    pipe = Pipeline(Aggregator(cfg, today, trading_day), Publisher(day_dir), cfg.get("candles.idle_clock_margin_s"))
    for e in sorted(day_events(day_dir, "buffer", control=True), key=arrival_key):  # warm start after a restart
        pipe(e)
    rec = Recorder(cfg, store, consumers=[pipe], symbols=symbols, on_idle=pipe.idle,
                   alert=lambda m: alert_once(cfg.root, "disk:" + next((w for w in ("depth", "ticks") if w in m), "low"),
                                              "Engine disk guard", m))
    base = rec.resume()
    if rec.unclean_stop_ns is not None:
        down_from = datetime.fromtimestamp(rec.unclean_stop_ns / 1e9, IST)
        alert_once(cfg.root, f"unclean:{rec.unclean_stop_ns}", "Engine recorder had DIED; restarted",
                   f"No data from {down_from:%H:%M:%S} to {datetime.now(IST):%H:%M:%S} IST "
                   "(crash, kill or Mac sleep). Logged as a 'restart' gap.")
    rec.start()
    stop = threading.Event()
    tickers: dict[int, object] = {}
    cids = lambda: [base + s for s in tickers]  # noqa: E731

    def open_slot(slot: int) -> None:
        cid, kt = base + slot, session.ticker(cfg)

        def on_connect(ws, resp):
            rec.on_conn_event(cid, "connect", {"tokens": len(ws.subscribed_tokens)})
            if ws.subscribed_tokens:  # reconnect: the library resubscribes with the stored modes (F-WS-8)
                rec.on_conn_event(cid, "resubscribe", {"tokens": sorted(ws.subscribed_tokens)})

        def on_noreconnect(ws):
            rec.on_conn_event(cid, "noreconnect", {})
            if all(rec.conn_state.get(c) == "noreconnect" for c in cids()):
                stop.set()

        kt.on_message = lambda ws, p, b: rec.on_message(cid, p, b)
        kt.on_connect = on_connect
        kt.on_close = lambda ws, code, reason: rec.on_conn_event(cid, "close", {"code": code, "reason": reason})
        kt.on_error = lambda ws, code, reason: rec.on_conn_event(cid, "error", {"code": code, "reason": reason})
        kt.on_reconnect = lambda ws, n: rec.on_conn_event(cid, "reconnect_attempt", {"attempt": n})
        kt.on_noreconnect = on_noreconnect
        tickers[slot] = kt
        kt.connect(threaded=True)

    def send(slot: int, op: str, mode, toks: tuple) -> None:
        from twisted.internet import reactor
        kt = tickers[slot]
        call = {"subscribe": lambda: kt.subscribe(list(toks)), "unsubscribe": lambda: kt.unsubscribe(list(toks)),
                "mode": lambda: kt.set_mode(mode, list(toks))}[op]
        reactor.callFromThread(call)

    executor = TierExecutor(rec, book, cfg, open_slot, send, lambda slot: rec.conn_state.get(base + slot) == "connected")
    executor.step()
    if "options" in cfg.values and trading_day:   # Phase 11 (config v14+): event calendar + live tier C planner (D-51)
        from .events import fetch as fetch_events
        try:
            print(json.dumps({"event_calendar": str(fetch_events(cfg, time.time_ns()))}), flush=True)
        except Exception as e:  # noqa: BLE001  a failed fetch only means EVENT_UNVERIFIED (options rejected)
            print(f"[engine.recorder] event calendar fetch failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        start_tier_c_planner(cfg, session, universe, book, today, day_dir, stop)
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *_: stop.set())
    print(f"[engine.recorder] {today}: {len(plan.subs)} tokens {plan.usage} -> {day_dir}", flush=True)
    while not stop.is_set() and (until is None or datetime.now(IST) < until):
        stop.wait(cfg.get("tiers.executor_interval_s"))
        p = executor.step()
        for cid in rec.check_stall(cids(), time.time_ns()):
            alert_once(cfg.root, "stall", "Engine feed STALLED; reconnecting",
                       f"Connection {cid}: no frame for {cfg.get('ws.stall_after_s')} s while 'connected' "
                       "(half-open socket, e.g. after sleep). Logged as a 'stall' gap; forcing a reconnect.")
            kt = tickers[cid - base]
            from twisted.internet import reactor
            reactor.callFromThread(lambda kt=kt: kt.ws and kt.ws.dropConnection(abort=True))
        for t in p.subs.keys() - rec.symbols.keys():
            c = contract(t)
            rec.symbols[t] = f"{c.exchange}:{c.tradingsymbol}" if c else str(t)
    if tickers and all(rec.conn_state.get(c) == "noreconnect" for c in cids()):
        alert_once(cfg.root, "noreconnect", "Engine recorder STOPPED: WebSocket gave up",
                   f"All {len(tickers)} connection(s) exhausted reconnect attempts. The 15-min retry will try again.")

    for slot, kt in tickers.items():
        rec.on_conn_event(base + slot, "shutdown", {})
        kt.close()
    rec.stop()
    pipe.idle(time.time_ns())
    pipe.pub.close()
    store.close()
    registry.close()
    from twisted.internet import reactor
    reactor.callFromThread(reactor.stop)
    print(json.dumps({k: rec.status(time.time_ns())[k] for k in ("counts", "dropped_total", "gaps_today")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
