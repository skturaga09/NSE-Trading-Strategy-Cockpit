"""Phase 3 tiered subscriptions: a pure planning function, the in-process tier book, and the
per-connection executor diff.

Tier A = whole universe (spot + every active future + index spot), rebuilt daily from the registry.
Tier B = instruments under active watch, Tier C = option contracts; both set by later phases through
`TierBook.promote(token, reason, ttl)` / `demote(token)` (tier="C" for C) and expire after their TTL.

One token is one subscription slot whatever its mode. A token asked for by several tiers gets the
richest mode (full > quote > ltp) and keeps the slot of its highest tier. The limit is
ws.max_tokens_per_connection x ws.max_connections (F-WS-2). Past it the lowest-priority requests
(tier A, then B, then C; inside a tier, earlier requests first) are dropped, each with its reason. A tier may also have
its own cap (`tiers.<T>.max_tokens`, Phase 11: tier C = 400, D-51): past it that tier's further new tokens are dropped.
"""

import threading
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

MODES = {"ltp": 0, "quote": 1, "full": 2}
TIER_RANK = {"A": 0, "B": 1, "C": 2}


@dataclass(frozen=True)
class Request:
    token: int
    tier: str        # 'A' | 'B' | 'C'
    mode: str        # 'ltp' | 'quote' | 'full'
    kind: str        # 'INDEX' | 'EQ' | 'FUT' | 'CE' | 'PE' | 'UNKNOWN'
    underlying: str
    reason: str
    order: int       # position inside its tier: lower = higher priority


@dataclass(frozen=True)
class Plan:
    subs: dict[int, str]                          # token -> mode
    meta: dict[int, tuple[str, str, str]]         # token -> (tiers e.g. 'AB', kind, underlying)
    dropped: tuple[tuple[int, str, str], ...]     # (token, tier, reason)
    usage: dict[str, int]                         # tokens per tier, total, limit, dropped


def allocate(requests: Iterable[Request], per_conn: int, max_conns: int, *, caps: Mapping[str, int] | None = None) -> Plan:
    limit, caps = per_conn * max_conns, caps or {}
    subs, first, tiers, dropped, taken = {}, {}, {}, [], Counter()
    for r in sorted(requests, key=lambda r: (TIER_RANK[r.tier], r.order, r.token)):
        if r.token in subs:
            if MODES[r.mode] > MODES[subs[r.token]]:
                subs[r.token] = r.mode
            tiers[r.token].add(r.tier)
        elif r.tier in caps and taken[r.tier] >= caps[r.tier]:
            dropped.append((r.token, r.tier, f"{r.reason}: over the tier {r.tier} cap of {caps[r.tier]} tokens"))
        elif len(subs) < limit:
            subs[r.token], first[r.token], tiers[r.token] = r.mode, r, {r.tier}
            taken[r.tier] += 1
        else:
            dropped.append((r.token, r.tier, f"{r.reason}: over the limit of {limit} tokens "
                                             f"({max_conns} connections x {per_conn}, F-WS-2)"))
    meta = {t: ("".join(sorted(tiers[t])), first[t].kind, first[t].underlying) for t in subs}
    usage = Counter(x for t in subs for x in tiers[t])
    usage.update(total=len(subs), limit=limit, dropped=len(dropped))
    return Plan(subs, meta, tuple(dropped), dict(usage))


def assign(subs: Mapping[int, str], current: Mapping[int, Mapping[int, str]], per_conn: int, max_conns: int):
    """Place a plan on connection slots 0..max_conns-1, keeping every token on the slot it is on.
    -> (new {slot: {token: mode}}, ops [(slot, op, mode | None, tokens)]), op in open/unsubscribe/subscribe/mode."""
    new = {s: {t: subs[t] for t in toks if t in subs} for s, toks in current.items()}
    for t in sorted(set(subs) - {t for c in new.values() for t in c}):
        slot = next((s for s in sorted(new) if len(new[s]) < per_conn), None)
        if slot is None:
            slot = next((s for s in range(max_conns) if s not in new), None)
            if slot is None:
                raise ValueError(f"{len(subs)} tokens do not fit {max_conns} x {per_conn} (use allocate() first)")
            new[slot] = {}
        new[slot][t] = subs[t]
    ops = []
    for s in sorted(new):
        old = current.get(s, {})
        if s not in current:
            ops.append((s, "open", None, ()))
        gone, added = sorted(set(old) - set(new[s])), sorted(set(new[s]) - set(old))
        if gone:
            ops.append((s, "unsubscribe", None, tuple(gone)))
        if added:
            ops.append((s, "subscribe", None, tuple(added)))
        for mode in sorted(set(new[s].values())):
            toks = tuple(sorted(t for t, m in new[s].items() if m == mode and old.get(t) != m))
            if toks:
                ops.append((s, "mode", mode, toks))
    return new, ops


def tier_a_requests(universe, contract: Callable[[int], object], cfg) -> list[Request]:
    """Tier A from an engine.universe.Universe: INDEX family first, then stocks by name."""
    out = []
    for m in sorted(universe.members, key=lambda m: (m.family != "INDEX", m.underlying)):
        kind = "INDEX" if m.family == "INDEX" else "EQ"
        out.append(Request(m.spot_token, "A", cfg.get("tiers.A.spot_mode"), kind, m.underlying, "tier A spot", len(out)))
        for tok in m.future_tokens:
            out.append(Request(tok, "A", cfg.get("tiers.A.futures_mode"), contract(tok).instrument_type,
                               m.underlying, "tier A future", len(out)))
    return out


class TierBook:
    """Thread-safe in-process API for later phases. Time comes from the injected `clock_ns`.
    `describe(token) -> (kind, underlying)` labels B/C tokens (e.g. a registry lookup)."""

    def __init__(self, cfg, clock_ns: Callable[[], int],
                 describe: Callable[[int], tuple[str, str]] = lambda t: ("UNKNOWN", "")):
        self.cfg, self.clock_ns, self.describe = cfg, clock_ns, describe
        self._lock = threading.Lock()
        self._a: list[Request] = []
        self._live: dict[str, dict[int, tuple[str, int, int]]] = {"B": {}, "C": {}}  # token -> (reason, expires_ns, order)
        self._n = 0

    def set_tier_a(self, requests: Iterable[Request]) -> None:
        with self._lock:
            self._a = list(requests)

    def promote(self, token: int, reason: str, ttl: float, tier: str = "B") -> None:
        with self._lock:
            self._n += 1
            cur = self._live[tier].get(token)
            self._live[tier][token] = (reason, self.clock_ns() + int(ttl * 1e9), cur[2] if cur else self._n)

    def demote(self, token: int, tier: str = "B") -> None:
        with self._lock:
            self._live[tier].pop(token, None)

    def plan(self) -> Plan:
        now = self.clock_ns()
        with self._lock:
            reqs = list(self._a)
            for tier, d in self._live.items():
                for t in [t for t, (_, exp, _) in d.items() if exp <= now]:
                    del d[t]
                mode = self.cfg.get(f"tiers.{tier}.mode")
                reqs += [Request(t, tier, mode, *self.describe(t), reason, order) for t, (reason, _, order) in d.items()]
        # a config without tiers.<T>.max_tokens (v4 ... v13) keeps the Phase 3 behaviour: only the global limit
        caps = {t: self.cfg.get(f"tiers.{t}.max_tokens") for t in ("B", "C") if "max_tokens" in self.cfg.get(f"tiers.{t}")}
        return allocate(reqs, self.cfg.get("ws.max_tokens_per_connection"), self.cfg.get("ws.max_connections"), caps=caps)
