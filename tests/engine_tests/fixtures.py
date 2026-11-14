"""Hand-built KiteTicker frames per the documented byte layout (F-WS-4/5/7). No network."""

import copy
import struct
from pathlib import Path

from engine.config import DEFAULT_PATH, EngineConfig, load_config

FUT, IDX, EQ = 12345602, 256265, 738561  # NFO-ish, index, NSE-ish tokens (fixture values only)


def full_packet(token=FUT, ltp=2450000, ltq=75, atp=2449000, volume=1000, tbq=500, tsq=600,
                ohlc=(2440000, 2460000, 2430000, 2445000), last_trade_ts=1_790_000_000, oi=100,
                oi_hi=120, oi_lo=90, ex_ts=1_790_000_000, depth=None):
    b = struct.pack(">11I", token, ltp, ltq, atp, volume, tbq, tsq, *ohlc)
    b += struct.pack(">5I", last_trade_ts, oi, oi_hi, oi_lo, ex_ts)
    depth = depth or [(10 + i, 100000 - i, 1 + i) for i in range(5)] + [(20 + i, 100001 + i, 2 + i) for i in range(5)]
    for q, p, o in depth:
        b += struct.pack(">IIH2x", q, p, o)
    assert len(b) == 184
    return b


def index_packet(token=IDX, ltp=2440000, ex_ts=1_790_000_000):
    b = struct.pack(">7I", token, ltp, 2450000, 2430000, 2435000, 2420000, 20000) + struct.pack(">I", ex_ts)
    assert len(b) == 32
    return b


def frame(*packets: bytes) -> bytes:
    return struct.pack(">H", len(packets)) + b"".join(struct.pack(">H", len(p)) + p for p in packets)


def make_config(root: Path, **overrides) -> EngineConfig:
    base = load_config(DEFAULT_PATH)
    v = copy.deepcopy(dict(base.values))
    v["storage"]["root"] = str(root)
    for dotted, val in overrides.items():
        d = v
        *head, last = dotted.split(".")
        for h in head:
            d = d[h]
        d[last] = val
    return EngineConfig(base.version, base.sha256, v)


class Clock:
    """Deterministic ns clock: set .t or let each call advance by `step`."""

    def __init__(self, t=1_790_000_000_000_000_000, step=1_000_000):
        self.t, self.step = t, step

    def __call__(self):
        self.t += self.step
        return self.t
