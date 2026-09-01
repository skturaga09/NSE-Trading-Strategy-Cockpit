#!/usr/bin/env python3
"""
Thesis-drift monitor: for each OPEN option position, check whether the underlying
still agrees with the directional bet you made (CALL = bullish, PUT = bearish),
using three objective signals — today's move vs previous close, position vs the day
VWAP, and futures OI buildup. It does NOT predict; it flags when the *reason you
entered* has weakened, so you can decide.

Alignment score = how many of the 3 signals agree with the bet:
  3 or 2 → ALIGNED · 1 → MIXED · 0 → DRIFT
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from dashboard import app as core
from dashboard.option_chain import _headers, _connected
from dashboard.swing_scan import _futures_map, _oi_buildup

_UND_RE = re.compile(r"^([A-Z&-]+?)\d{2}[A-Z]{3}\d+(CE|PE)$")


def _underlying(sym: str) -> Optional[str]:
    m = _UND_RE.match(sym)
    return m.group(1) if m else None


def alignment() -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"timestamp": ts, "is_live": False, "source": "unavailable", "positions": []}
    if not _connected():
        out["source"] = "Kite not connected"
        return out
    try:
        j = requests.get("https://api.kite.trade/portfolio/positions", headers=_headers(), timeout=12).json()
        net = j.get("data", {}).get("net", []) if j.get("status") == "success" else []
        opts = [p for p in net if p.get("quantity") and (p["tradingsymbol"].endswith("CE") or p["tradingsymbol"].endswith("PE"))]
        unds = sorted({u for p in opts if (u := _underlying(p["tradingsymbol"]))})
        if not opts:
            out.update({"is_live": True, "source": "Zerodha Kite live", "positions": []})
            return out

        q = requests.get("https://api.kite.trade/quote", params=[("i", f"NSE:{u}") for u in unds],
                         headers=_headers(), timeout=12).json().get("data", {})
        futmap = _futures_map()
        bu_cache: Dict[str, Any] = {}

        rows: List[Dict[str, Any]] = []
        for p in opts:
            sym = p["tradingsymbol"]
            u = _underlying(sym)
            is_call = sym.endswith("CE")
            d = q.get(f"NSE:{u}", {}) if u else {}
            o = d.get("ohlc", {}) or {}
            ltp, pc, vw = d.get("last_price"), o.get("close"), d.get("average_price")
            day_pct = round((ltp / pc - 1) * 100, 2) if (ltp and pc) else None
            vs_vwap = round((ltp / vw - 1) * 100, 2) if (ltp and vw) else None
            if u and u not in bu_cache:
                fut = futmap.get(u)
                bu_cache[u] = _oi_buildup(fut["token"]) if fut else None
            bu = bu_cache.get(u)
            lean = bu["lean"] if bu else None

            # Count signals that agree with the directional bet.
            want_bull = is_call
            agree, total = 0, 0
            for val, positive in ((day_pct, day_pct is not None), (vs_vwap, vs_vwap is not None)):
                if positive:
                    total += 1
                    if (val > 0) == want_bull:
                        agree += 1
            if lean:
                total += 1
                if (lean == "bullish") == want_bull:
                    agree += 1
            status = "UNKNOWN" if total == 0 else ("ALIGNED" if agree >= 2 else "MIXED" if agree == 1 else "DRIFT")

            rows.append({
                "symbol": sym, "underlying": u, "direction": "CALL" if is_call else "PUT",
                "day_pct": day_pct, "vs_vwap_pct": vs_vwap,
                "buildup": bu["label"] if bu else None, "lean": lean,
                "agree": agree, "total": total, "status": status,
            })
        order = {"DRIFT": 0, "MIXED": 1, "ALIGNED": 2, "UNKNOWN": 3}
        rows.sort(key=lambda r: order.get(r["status"], 3))
        out.update({"is_live": True, "source": "Zerodha Kite live (/quote + futures OI)", "positions": rows})
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(alignment(), indent=2, default=str))
