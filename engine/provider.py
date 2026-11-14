"""SubscriptionProvider: which instrument tokens to record, and in which mode.

ConfigSubscriptionProvider (Phase 1) resolves an explicit list against the day's instrument master
(F-INST-1..3). UniverseSubscriptionProvider (Phase 2) subscribed the day's universe from engine.universe.
Since Phase 3 the recorder subscribes through engine.tiers (TierBook + TierExecutor) instead; both
providers are kept, unused by the recorder, as the record of the earlier phases.
"""

import csv
import io
from datetime import date
from typing import Iterable, Mapping, Protocol


class SubscriptionProvider(Protocol):
    def subscriptions(self) -> dict[int, str]:
        """{instrument_token: mode}, mode in {'ltp', 'quote', 'full'}."""


def parse_master(csv_bytes: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))


class ConfigSubscriptionProvider:
    def __init__(self, entries: Iterable[Mapping], master: list[dict[str, str]], trading_date: date):
        self.entries, self.master, self.day = list(entries), master, trading_date
        self.resolved: dict[int, dict] = {}  # token -> master row, for logging/family lookups

    def _resolve(self, e: Mapping) -> dict[str, str]:
        if e.get("select") == "near_future":
            futs = [r for r in self.master
                    if r["exchange"] == e["exchange"] and r["name"] == e["name"] and r["instrument_type"] == "FUT"
                    and r["expiry"] and date.fromisoformat(r["expiry"]) >= self.day]
            if not futs:
                raise LookupError(f"no live {e['exchange']} FUT for {e['name']} on {self.day}")
            return min(futs, key=lambda r: r["expiry"])
        hits = [r for r in self.master if r["exchange"] == e["exchange"] and r["tradingsymbol"] == e["tradingsymbol"]]
        if len(hits) != 1:
            raise LookupError(f"{e['exchange']}:{e['tradingsymbol']}: {len(hits)} master rows (need exactly 1)")
        return hits[0]

    def subscriptions(self) -> dict[int, str]:
        out = {}
        for e in self.entries:
            row = self._resolve(e)
            tok = int(row["instrument_token"])
            self.resolved[tok] = row
            out[tok] = e["mode"]
        return out


class UniverseSubscriptionProvider:
    """Phase 2: spot + the first `futures` active expiries of every universe member, all in one mode.
    `registry` is an engine.universe.Registry (tiering by member comes in Phase 3)."""

    def __init__(self, registry, trading_date: date, mode: str, futures: int):
        self.registry, self.day, self.mode, self.futures = registry, trading_date, mode, futures
        self.resolved: dict[int, dict] = {}

    def subscriptions(self) -> dict[int, str]:
        u = self.registry.get_universe(self.day)
        if "NO_MASTER" in u.flags:
            raise LookupError(f"no instrument master applied to the registry for {self.day}")
        out = {}
        for m in u.members:
            for tok in (m.spot_token, *m.future_tokens[:self.futures]):
                c = self.registry.get_contract(tok, self.day)
                self.resolved[tok] = {"exchange": c.exchange, "tradingsymbol": c.tradingsymbol}
                out[tok] = self.mode
        return out

