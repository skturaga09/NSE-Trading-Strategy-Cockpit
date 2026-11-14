"""Phase 2: universe, contract registry, restrictions. Fixture data only, no network."""

import hashlib
import re
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from engine.config import REPO
from engine.provider import UniverseSubscriptionProvider
from engine.sources import parse_ban, parse_constituents
from engine.universe import Registry, refresh, strike_intervals

from .fixtures import make_config

D1, D2, D3 = date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)  # Thu, Fri, Mon
HDR = "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
CIRC = b"fixture circular"
N50, N100, BAN = "https://x/n50.csv", "https://x/n100.csv", "https://x/ban.csv"


def master(nifty_lot=65, old_fut=True):
    rows = [
        "1,1,NIFTY26NOVFUT,NIFTY,0,2026-11-23,0,0.1,{l},FUT,NFO-FUT,NFO",
        "2,2,NIFTY26DECFUT,NIFTY,0,2026-12-29,0,0.1,{l},FUT,NFO-FUT,NFO",
        "3,3,NIFTY27JANFUT,NIFTY,0,2027-01-25,0,0.1,{l},FUT,NFO-FUT,NFO",
        "10,10,NIFTY26N2324000CE,NIFTY,0,2026-11-23,24000,0.05,{l},CE,NFO-OPT,NFO",
        "11,11,NIFTY26N2324050CE,NIFTY,0,2026-11-23,24050,0.05,{l},CE,NFO-OPT,NFO",
        "12,12,NIFTY26N2324100CE,NIFTY,0,2026-11-23,24100,0.05,{l},CE,NFO-OPT,NFO",
        "13,13,NIFTY26N2324200CE,NIFTY,0,2026-11-23,24200,0.05,{l},CE,NFO-OPT,NFO",
        "14,14,NIFTY26N2324000PE,NIFTY,0,2026-11-23,24000,0.05,{l},PE,NFO-OPT,NFO",
        "256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE",
        "20,20,RELIANCE26NOVFUT,RELIANCE,0,2026-11-23,0,0.1,500,FUT,NFO-FUT,NFO",
        "21,21,RELIANCE26DECFUT,RELIANCE,0,2026-12-29,0,0.1,500,FUT,NFO-FUT,NFO",
        "738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.1,1,EQ,NSE,NSE",
        "30,30,KAYNES26NOVFUT,KAYNES,0,2026-11-23,0,0.1,150,FUT,NFO-FUT,NFO",
        "300,300,KAYNES,KAYNES TECHNOLOGY,0,,0,0.1,1,EQ,NSE,NSE",
        "40,40,M&M26NOVFUT,M&M,0,2026-11-23,0,0.1,200,FUT,NFO-FUT,NFO",
        "400,400,M&M,MAHINDRA & MAHINDRA,0,,0,0.1,1,EQ,NSE,NSE",
        "500,500,TATACAP,TATA CAPITAL,0,,0,0.1,1,EQ,NSE,NSE",
        "600,600,OTHER,OTHER LTD,0,,0,0.1,1,EQ,NSE,NSE",
    ]
    if old_fut:  # a contract expiring on D1, still (stale) in the next day's dump
        rows.append("5,5,NIFTY26NOV05FUT,NIFTY,0,2026-11-05,0,0.1,{l},FUT,NFO-FUT,NFO")
    return (HDR + "\n".join(rows).format(l=nifty_lot) + "\n").encode()


def cons_csv(*syms):
    return ("Company Name,Industry,Symbol,Series,ISIN Code\n"
            + "".join(f"{s} Ltd.,X,{s},EQ,INE000000000\n" for s in syms)).encode()


def ban_csv(d: date, *syms):
    return (f"Securities in Ban For Trade Date {d.strftime('%d-%b-%Y').upper()}:\n"
            + "".join(f"{i},{s}\n" for i, s in enumerate(syms, 1))).encode()


class Fetch:
    def __init__(self, **by_url):
        self.by_url = by_url

    def __call__(self, url):
        v = self.by_url[url]
        if isinstance(v, Exception):
            raise v
        return v


def sources(day, ban=(), **over):
    s = {N50: cons_csv("RELIANCE", "M&M"), N100: cons_csv("RELIANCE", "M&M", "KAYNES", "TATACAP"),
         BAN: ban_csv(day, *ban), "https://x/circ.pdf": CIRC}
    s.update(over)
    return Fetch(**s)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(Path(self.tmp.name), **{
            "universe.indices": {"NIFTY50": N50, "NIFTY100": N100},
            "restrictions.ban_list_url": BAN,
            "restrictions.holiday_circulars": [{"ref": "FIX/1", "url": "https://x/circ.pdf",
                                                "sha256": hashlib.sha256(CIRC).hexdigest()}]})

    def tearDown(self):
        self.tmp.cleanup()

    def refresh(self, day, m=None, fetch=None):
        return refresh(self.cfg, day, m or master(), fetch or sources(day))

    def reg(self):
        r = Registry(self.cfg)
        self.addCleanup(r.close)
        return r


class TestUniverse(Base):
    def test_no_duplicate_underlying_and_fno_derived_from_master(self):
        self.refresh(D1)
        u = self.reg().get_universe(D1)
        names = [m.underlying for m in u.members]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names, ["KAYNES", "M&M", "NIFTY", "RELIANCE"])
        rel = next(m for m in u.members if m.underlying == "RELIANCE")
        self.assertEqual(rel.indices, ("NIFTY100", "NIFTY50"))
        self.assertEqual((rel.spot_token, rel.future_tokens), (738561, (20, 21)))
        self.assertEqual(u.by_family(), {"STOCK": 3, "INDEX": 1})
        self.assertNotIn("TATACAP", names)  # constituent with an NSE spot but no NFO contracts
        self.assertIn(("TATACAP", "NO_NFO_FUTURES"), u.excluded)
        self.assertEqual(u.flags, ())

    def test_expired_contract_never_active_after_expiry(self):
        self.refresh(D1)
        self.refresh(D2)  # token 5 (expiry D1) is still in the D2 dump
        r = self.reg()
        self.assertTrue(r.get_contract(5, D1).active)
        self.assertFalse(r.get_contract(5, D2).active)
        self.assertNotIn(5, [c.token for c in r.get_contracts("NIFTY", D2)])
        self.assertNotIn(5, next(m for m in r.get_universe(D2).members if m.underlying == "NIFTY").future_tokens)
        ok, why = r.is_tradable(5, D2)
        self.assertFalse(ok)
        self.assertIn("EXPIRED", why)

    def test_banned_security_not_tradable(self):
        self.refresh(D1, fetch=sources(D1, ban=["KAYNES"]))
        r = self.reg()
        self.assertEqual(r.is_tradable(30, D1), (False, ["BANNED"]))
        self.assertEqual(r.is_tradable(20, D1), (True, []))

    def test_missing_ban_list_is_restriction_unverified(self):
        self.refresh(D1, fetch=sources(D1, **{BAN: OSError("timeout")}))
        ok, why = self.reg().is_tradable(20, D1)
        self.assertFalse(ok)
        self.assertTrue(any(w.startswith("RESTRICTION_UNVERIFIED:ban_list") for w in why), why)

    def test_ban_list_for_another_trade_date_does_not_verify_today(self):
        self.refresh(D1, fetch=sources(D1, **{BAN: ban_csv(D2, "KAYNES")}))
        r = self.reg()
        self.assertFalse(r.is_tradable(30, D1)[0])
        self.assertTrue(any(w.startswith("RESTRICTION_UNVERIFIED:ban_list") for w in r.is_tradable(30, D1)[1]))
        self.assertIn("BANNED", r.restriction_reasons(D2, True, "KAYNES"))

    def test_historical_lookup_and_daily_diff(self):
        self.refresh(D1)
        self.refresh(D2, m=master(nifty_lot=75))
        self.refresh(D3, m=master(nifty_lot=75, old_fut=False))
        r = self.reg()
        self.assertEqual(r.get_contract(1, D1).lot_size, 65)
        self.assertEqual(r.get_contract(1, D2).lot_size, 75)
        self.assertEqual(r.get_contract(1, D3).lot_size, 75)
        self.assertEqual(r.get_contract(1, D1).first_seen_date, D1)
        self.assertEqual(r.get_contract(1, D1).last_seen_date, D1)
        self.assertEqual(r.get_contract(738561, D1).last_seen_date, D3)  # unchanged rows extend, not duplicate
        self.assertIsNone(r.get_contract(5, D3))                         # removed from the D3 dump
        self.assertIsNone(r.get_contract(1, date(2026, 11, 4)))          # no master that day: no answer
        kinds = {d: dict(r.db.execute("SELECT kind, COUNT(*) FROM master_diff WHERE date=? GROUP BY kind",
                                      (d.isoformat(),)).fetchall()) for d in (D2, D3)}
        self.assertEqual(kinds[D2], {"lot_size_change": 9, "rollover": 1})  # 4 NIFTY futs + 5 options
        self.assertEqual(kinds[D3], {"removed": 1})
        self.assertEqual(r.db.execute("SELECT old, new FROM master_diff WHERE kind='rollover'").fetchone(),
                         ("NIFTY26NOV05FUT", "NIFTY26NOVFUT"))

    def test_token_reused_for_another_contract_resolves_by_date(self):
        self.refresh(D1)
        self.refresh(D2, m=master().replace(b"40,40,M&M26NOVFUT", b"40,40,M&M26DECFUT").replace(
            b"M&M26DECFUT,M&M,0,2026-11-23", b"M&M26DECFUT,M&M,0,2026-12-29"))
        r = self.reg()
        self.assertEqual(r.get_contract(40, D1).tradingsymbol, "M&M26NOVFUT")
        self.assertEqual(r.get_contract(40, D2).tradingsymbol, "M&M26DECFUT")

    def test_stale_constituents_flagged_then_blocked(self):
        fail = {N50: OSError("down"), N100: OSError("down")}
        self.refresh(D1)
        self.refresh(D2, fetch=sources(D2, **fail))
        self.refresh(D3, fetch=sources(D3, **fail))
        r = self.reg()
        self.assertEqual(r.get_universe(D2).flags, ("STALE_CONSTITUENTS",))
        self.assertEqual(r.is_tradable(20, D2), (True, ["STALE_CONSTITUENTS"]))
        self.assertEqual(r.get_universe(D3).flags, ("BLOCKED_STALE_CONSTITUENTS",))  # 4 days > 3
        self.assertEqual(r.is_tradable(20, D3), (False, ["BLOCKED_STALE_CONSTITUENTS"]))
        self.assertEqual(r.get_universe(D3).constituents_date, D1)
        self.assertEqual(r.is_tradable(1, D2), (True, []))  # INDEX ignores constituent staleness (Q-UNI-2)
        self.assertEqual(r.is_tradable(1, D3), (True, []))

    def test_index_tradable_without_any_constituent_list(self):
        self.refresh(D1, fetch=sources(D1, **{N50: OSError("down"), N100: OSError("down")}))
        r = self.reg()
        self.assertEqual(r.get_universe(D1).flags, ("BLOCKED_NO_CONSTITUENTS",))
        self.assertEqual([m.underlying for m in r.get_universe(D1).members], ["NIFTY"])
        self.assertEqual(r.is_tradable(1, D1), (True, []))
        self.assertEqual(r.is_tradable(20, D1), (False, ["NOT_IN_UNIVERSE", "BLOCKED_NO_CONSTITUENTS"]))

    def test_holidays_weekends_and_unverified_circulars(self):
        r = self.reg()
        hol, sat, nxt = date(2026, 11, 24), date(2026, 11, 7), date(2027, 1, 4)
        for d in (sat, hol):
            refresh(self.cfg, d, master(), sources(d))
        self.assertEqual(r.restriction_reasons(hol, True, "X"), ["HOLIDAY"])
        self.assertTrue(r.restriction_reasons(sat, False, "X")[0].startswith("RESTRICTION_UNVERIFIED:weekend"))
        self.assertTrue(r.restriction_reasons(nxt, False, "X")[0].startswith("RESTRICTION_UNVERIFIED:holidays"))
        changed = date(2026, 11, 26)
        refresh(self.cfg, changed, master(), sources(changed, **{"https://x/circ.pdf": b"edited"}))
        self.assertTrue(r.restriction_reasons(changed, False, "X")[0].startswith("RESTRICTION_UNVERIFIED:holidays"))

    def test_refresh_is_idempotent_and_refuses_out_of_order(self):
        self.refresh(D2)
        out = self.refresh(D2)
        self.assertEqual(out["master"]["status"], "already applied")
        self.assertEqual(out["ban_list"], "already fetched OK today")
        r = self.reg()
        self.assertEqual(r.db.execute("SELECT COUNT(*) FROM contracts").fetchone()[0], 17)
        with self.assertRaises(ValueError):
            self.refresh(D1)

    def test_provider_subscribes_spot_near_and_next_in_quote_mode(self):
        self.refresh(D1)
        p = UniverseSubscriptionProvider(self.reg(), D1, "quote", 2)
        self.assertEqual(p.subscriptions(), {t: "quote" for t in (256265, 5, 1, 738561, 20, 21, 300, 30, 400, 40)})
        self.assertEqual(p.resolved[256265], {"exchange": "NSE", "tradingsymbol": "NIFTY 50"})

    def test_strike_intervals_derived_from_listed_strikes(self):
        self.refresh(D1)
        cs = self.reg().get_contracts("NIFTY", D1)
        self.assertEqual(strike_intervals(cs, date(2026, 11, 23)), (Decimal("50"), Decimal("100")))
        self.assertEqual(next(c for c in cs if c.token == 1).lot_size, 65)


class TestSources(unittest.TestCase):
    def test_parsers_accept_measured_format_only(self):
        self.assertEqual(parse_ban(b"Securities in Ban For Trade Date 06-NOV-2026:\n1,KAYNES\n"),
                         (date(2026, 11, 6), ["KAYNES"]))
        self.assertEqual(parse_ban(b"Securities in Ban For Trade Date 06-NOV-2026:\n"), (date(2026, 11, 6), []))
        for bad in (b"<html>", b"Securities in Ban For Trade Date 06-NOV-2026:\nNIL\n"):
            with self.assertRaises(ValueError):
                parse_ban(bad)
        self.assertEqual(parse_constituents(cons_csv("A", "B")), ["A", "B"])
        with self.assertRaises(ValueError):
            parse_constituents(cons_csv("A", "A"))


class TestNoHardcodedContractFacts(unittest.TestCase):
    """Lot sizes and expiries come only from the master: no numeric lot sizes or date literals in logic."""

    PATTERNS = (re.compile(r"\b(19|20)\d{2}-[01]\d-[0-3]\d\b"), re.compile(r"\bdate\(\s*\d"),
                re.compile(r"\blot\w*\s*[:=]+\s*\d"), re.compile(r"\b\d{2}-(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-\d{4}"))

    def test_grep_logic_modules(self):
        hits = [f"{p.name}:{i}: {ln.strip()}" for p in sorted((REPO / "engine").glob("*.py"))
                for i, ln in enumerate(p.read_text().splitlines(), 1)
                if any(rx.search(ln) for rx in self.PATTERNS)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
