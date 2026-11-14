"""Pure decoding of KiteTicker binary frames into raw integer fields (no scaling, no clock).

Layout: F-WS-3/4/5/7 (kite.trade/docs/connect/v3/websocket) and kiteconnect 5.2.2 ticker.py
`_split_packets` / `_parse_binary`. Prices stay as the exchange integers (paise for NSE/NFO);
timestamps stay as epoch seconds. Nothing is converted, so nothing is lost.
"""

import struct

TICK_FIELDS = ("mode", "ltp", "ltq", "atp", "volume", "tbq", "tsq", "open", "high", "low", "close",
               "last_trade_ts", "oi", "oi_day_high", "oi_day_low", "index_change")
DEPTH_FIELDS = tuple(f"{side}{i}_{f}" for side in ("b", "s") for i in range(5) for f in ("qty", "price", "orders"))


def split_frame(payload: bytes) -> list[bytes]:
    """Frame = u16 count, then (u16 length, packet) * count. Heartbeats (<2 bytes) carry no packets."""
    if len(payload) < 2:
        return []
    n, = struct.unpack_from(">H", payload, 0)
    out, j = [], 2
    for _ in range(n):
        ln, = struct.unpack_from(">H", payload, j)
        out.append(payload[j + 2:j + 2 + ln])
        j += 2 + ln
    return out


def packet_count(payload: bytes) -> int:
    return struct.unpack_from(">H", payload, 0)[0] if len(payload) >= 2 else 0


def decode(pkt: bytes) -> tuple[int, int | None, dict, tuple | None]:
    """-> (token, exchange_ts, fields{TICK_FIELDS}, depth tuple of 30 ints | None). Absent fields are None."""
    u = lambda a, b: struct.unpack_from(">I", pkt, a)[0]  # noqa: E731  (unsigned, as the library does)
    f = dict.fromkeys(TICK_FIELDS)
    token, n = u(0, 4), len(pkt)
    ex_ts, depth = None, None
    if n == 8:
        f.update(mode="ltp", ltp=u(4, 8))
    elif n in (28, 32):  # index packets (F-WS-7)
        f.update(mode="quote" if n == 28 else "full", ltp=u(4, 8), high=u(8, 12), low=u(12, 16),
                 open=u(16, 20), close=u(20, 24), index_change=u(24, 28))
        if n == 32:
            ex_ts = u(28, 32)
    elif n in (44, 184):
        f.update(mode="quote" if n == 44 else "full", ltp=u(4, 8), ltq=u(8, 12), atp=u(12, 16), volume=u(16, 20),
                 tbq=u(20, 24), tsq=u(24, 28), open=u(28, 32), high=u(32, 36), low=u(36, 40), close=u(40, 44))
        if n == 184:
            f.update(last_trade_ts=u(44, 48), oi=u(48, 52), oi_day_high=u(52, 56), oi_day_low=u(56, 60))
            ex_ts = u(60, 64)
            depth = tuple(v for p in range(64, 184, 12)
                          for v in (u(p, p + 4), u(p + 4, p + 8), struct.unpack_from(">H", pkt, p + 8)[0]))
    else:
        f["mode"] = f"unknown:{n}"  # undocumented length: kept byte-exact in the frames log
    return token, ex_ts, f, depth
