#!/usr/bin/env python3
"""
FastAPI backend for the trading dashboard — async/threadpool server for faster plumbing.

Replaces the single-threaded stdlib HTTPServer (dashboard/app.py) so that
positions polling, live order validation, and recommendation fetches run
concurrently instead of serialising behind one another.

All business logic is imported unchanged from dashboard.app (the screener/bias
engines, the Zerodha plumbing inspector, Black-Scholes, backtest evaluator, and
the trade book), so this is purely a faster transport layer — no behaviour
changes. Routes are plain `def` functions, which FastAPI runs in a threadpool,
so the blocking yfinance / Kite calls no longer block other requests.

Run:  uvicorn dashboard.api_server:app --port 8080
"""

from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from dashboard import app as core
from dashboard import journal

STATIC_DIR = Path(__file__).parent / "static"
WEB_DIST = Path(__file__).parent / "web" / "dist"  # built React app (npm run build)

app = FastAPI(title="NSE Trading Dashboard API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v) if v is not None else default


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------

@app.get("/api/plumbing/status")
def plumbing_status() -> Dict[str, Any]:
    inspector = core.ZerodhaPlumbingInspector()
    conn = inspector.inspect_connection()
    return {
        "status": "online",
        "zerodha_mode": conn.details.get("mode", "Mock"),
        "connection_check": conn.__dict__,
        "reference_rules": {"lot_sizes": core.LOT_SIZES, "freeze_limits": core.FREEZE_LIMITS},
        "system_time": "2026-08-20T10:34:00+05:30",
    }


@app.get("/api/market/cockpit")
def market_cockpit() -> Dict[str, Any]:
    return core.get_market_cockpit_data()


@app.get("/api/market/session")
def market_session() -> Dict[str, Any]:
    return core.ZerodhaPlumbingInspector.market_session()


@app.get("/api/journal/attribution")
def journal_attribution() -> Dict[str, Any]:
    return journal.attribution()


@app.get("/api/journal/recent")
def journal_recent() -> Dict[str, Any]:
    return {"trades": journal.recent()}


@app.get("/api/journal/daily-pnl")
def journal_daily_pnl() -> Dict[str, Any]:
    """Net P&L per day (YYYY-MM-DD -> ₹) for the year-heatmap."""
    return {"days": journal.daily_pnl()}


@app.get("/api/journal/swing-signals")
def journal_swing_signals() -> Dict[str, Any]:
    """Learning layer: resolve any newly-settled overnight OI signals, then return the
    edge stats (hit-rate by tier/side, sample-size gated) and recent signals."""
    from dashboard import swing_journal
    try:
        resolved = swing_journal.resolve_due()
    except Exception:
        resolved = 0
    return {"stats": swing_journal.stats(), "recent": swing_journal.recent(), "resolved_now": resolved}


@app.post("/api/journal/import-kite")
def journal_import_kite() -> JSONResponse:
    """Pull real F&O/intraday positions from the live Kite account into the journal."""
    from dashboard import kite_import
    res = kite_import.import_positions()
    return JSONResponse(res, status_code=200 if res.get("success") else 400)


@app.get("/api/intraday/context")
def intraday_context(underlying: str = "NIFTY") -> Dict[str, Any]:
    """Live underlying context for the Intraday tab so the user doesn't hand-type
    it: spot, day OHLC, previous close, and India VIX from Kite /quote. Every value
    is timestamped and labelled live/unavailable — never invented."""
    import requests
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        ts = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    from dashboard.option_chain import spot_symbol, ensure_fresh_config
    ensure_fresh_config()
    index_sym = spot_symbol(underlying)
    vix_sym = "NSE:INDIA VIX"
    kc = core.KITE_CONFIG
    out: Dict[str, Any] = {"timestamp_ist": ts, "underlying": underlying.upper(),
                           "is_live": False, "source": "unavailable",
                           "spot": None, "open": None, "high": None, "low": None,
                           "prev_close": None, "vix": None, "gap": None}
    if not (kc.get("api_key") and kc.get("access_token")):
        out["source"] = "Kite not connected — connect on System Check"
        return out
    try:
        headers = {"Authorization": f"token {kc['api_key']}:{kc['access_token']}", "X-Kite-Version": "3"}
        r = requests.get("https://api.kite.trade/quote",
                         params=[("i", index_sym), ("i", vix_sym)], headers=headers, timeout=6)
        j = r.json()
        if j.get("status") != "success":
            out["source"] = f"Kite error: {j.get('message', 'quote failed')}"
            return out
        d = j["data"]
        idx = d.get(index_sym, {})
        ohlc = idx.get("ohlc", {}) or {}
        out.update({
            "is_live": True, "source": "Zerodha Kite live (/quote)",
            "spot": idx.get("last_price"),
            "open": ohlc.get("open"), "high": ohlc.get("high"),
            "low": ohlc.get("low"), "prev_close": ohlc.get("close"),
            "vix": (d.get(vix_sym, {}) or {}).get("last_price"),
        })
        if out["open"] is not None and out["prev_close"]:
            out["gap"] = round(out["open"] - out["prev_close"], 2)
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


@app.get("/api/exits/status")
def exits_status() -> Dict[str, Any]:
    from dashboard import exit_monitor
    return exit_monitor.evaluate()


@app.get("/api/exits/config")
def exits_get_config() -> Dict[str, Any]:
    from dashboard import exit_monitor
    return exit_monitor.get_config()


@app.post("/api/exits/config")
async def exits_set_config(request: Request) -> Dict[str, Any]:
    from dashboard import exit_monitor
    return exit_monitor.set_config(await request.json())


@app.post("/api/exits/test-alert")
def exits_test_alert() -> JSONResponse:
    from dashboard import exit_monitor
    # Send a realistic sample card (with a live portfolio line if positions exist).
    try:
        line = exit_monitor._portfolio_line(exit_monitor.evaluate())
    except Exception:
        line = "Portfolio: —"
    body = ("This is how an exit alert will look.\n"
            "P&L: +42.0%  (₹8,600)\n"
            "Now ₹40.5 · entry ₹28.5 · peak +48.0%\n"
            "Rule: gave back 6% from +48% peak\n"
            f"{line}\n"
            "Tap ‘Open Kite’ to act — you decide.")
    res = exit_monitor.notify("🎯 EXIT TARGET · CAMS26SEP760CE (sample)", body,
                              tags=["dart", "tada"], priority=4)
    return JSONResponse(res, status_code=200 if res.get("success") else 400)


@app.post("/api/exits/candidates-now")
def exits_candidates_now() -> JSONResponse:
    from dashboard import exit_monitor
    res = exit_monitor.send_candidates()
    return JSONResponse(res, status_code=200 if res.get("success") else 400)


@app.post("/api/exits/breakouts-now")
def exits_breakouts_now() -> JSONResponse:
    from dashboard import exit_monitor
    res = exit_monitor.send_breakouts()
    return JSONResponse(res, status_code=200 if res.get("success") else 400)


@app.post("/api/exits/overnight-now")
def exits_overnight_now() -> JSONResponse:
    """Push the overnight OI-buildup board to the phone now (same as the ~15:15 EOD job).
    warm=False here so the on-demand test reuses the server's already-cached OI map and
    returns fast instead of blocking ~80s on a fresh full-universe refresh."""
    from dashboard import exit_monitor
    res = exit_monitor.send_overnight(warm=False)
    return JSONResponse(res, status_code=200 if res.get("success") else 400)


@app.get("/api/exits/target-calc")
def exits_target_calc() -> Dict[str, Any]:
    """For each open option: the stock price needed to hit your pending sell target."""
    from dashboard import target_calc
    return target_calc.compute()


@app.get("/api/exits/thesis")
def exits_thesis() -> Dict[str, Any]:
    """Thesis-drift: does each open option's underlying still agree with the bet."""
    from dashboard import thesis
    return thesis.alignment()


@app.post("/api/exits/summary-now")
def exits_summary_now() -> JSONResponse:
    from dashboard import exit_monitor
    res = exit_monitor.send_summary(exit_monitor.evaluate(), exit_monitor.get_config())
    return JSONResponse(res, status_code=200 if res.get("success") else 400)


@app.get("/api/swing/scan")
def swing_scan_ep() -> Dict[str, Any]:
    """EOD overnight-swing positioning scan (close strength + futures OI buildup)."""
    from dashboard import swing_scan
    return swing_scan.scan()


@app.get("/api/intraday/fno-scan")
def intraday_fno_scan() -> Dict[str, Any]:
    """Live intraday F&O stock scan — ranked long/short candidates by objective
    momentum (vs day VWAP, range position, % change). A screen, not advice."""
    from dashboard import fno_scanner
    return fno_scanner.scan()


@app.get("/api/intraday/plan")
def intraday_plan(underlying: str = "NIFTY") -> Dict[str, Any]:
    """Structure-based intraday stop/target (underlying) from 15-min swing pivots."""
    from dashboard import swing_scan
    return swing_scan.intraday_structure_plan(underlying)


@app.get("/api/intraday/optionchain")
def intraday_optionchain(underlying: str = "NIFTY") -> Dict[str, Any]:
    """Live ATM ±3 option chain (LTP, bid/ask/spread, volume, OI, computed IV),
    plus verified lot size and nearest expiry from the Kite instrument master."""
    from dashboard import option_chain
    return option_chain.chain(underlying)


@app.post("/api/journal/decision")
async def journal_decision(request: Request) -> JSONResponse:
    """Log one intraday-console decision (any verdict, including NO TRADE/WAIT)."""
    d = await request.json()
    rid = journal.record_decision(d)
    return JSONResponse({"success": True, "id": rid})


@app.get("/api/journal/decisions")
def journal_decisions() -> Dict[str, Any]:
    return {"decisions": journal.decisions(), "summary": journal.decision_summary()}


@app.get("/api/journal/costs")
def journal_costs() -> Dict[str, Any]:
    """Estimated Zerodha charges across closed journaled trades."""
    return journal.costs_summary()


@app.get("/api/strategy/recommendations")
def recommendations() -> Dict[str, Any]:
    return core.build_trade_recommendations()


@app.get("/api/strategy/breakouts")
def breakouts() -> Dict[str, Any]:
    return core.compute_breakouts()


@app.get("/api/zerodha/config")
def get_zerodha_config() -> Dict[str, Any]:
    kc = core.KITE_CONFIG
    api_key = kc.get("api_key", "")
    is_conn = kc.get("is_connected", False)
    return {
        "is_connected": is_conn,
        "api_key": (api_key[:4] + "****") if api_key else "",
        "has_token": bool(kc.get("access_token") or kc.get("enctoken")),
        "auth_type": "Kite Connect API" if api_key else ("Kite Web Enctoken" if kc.get("enctoken") else "None"),
        "data_source": "Zerodha Kite Live API (api.kite.trade)" if is_conn else "Calibrated Live Simulation",
    }


@app.post("/api/zerodha/refresh")
def zerodha_refresh() -> JSONResponse:
    """On-demand Kite login: run the daily refresh flow now, reload the fresh
    token, and verify live connectivity. Backs the dashboard 'Connect to Zerodha'
    button so the user never has to touch the terminal or wait for the 08:00 cron.
    Secrets stay in the macOS Keychain — the script reads them; nothing crosses the
    browser."""
    import subprocess
    import sys

    script = Path(__file__).parent / "scripts" / "refresh_kite_token.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"success": False, "message": "Kite login timed out (120s). Try again."},
            status_code=504,
        )

    # Reload whatever the script wrote and test it against the live quote endpoint.
    core.KITE_CONFIG.clear()
    core.KITE_CONFIG.update(core.load_kite_config())
    kc = core.KITE_CONFIG
    quotes = core.ZerodhaPlumbingInspector.fetch_kite_ltp(
        ["NSE:NIFTY 50"], api_key=kc.get("api_key", ""),
        access_token=kc.get("access_token", ""), enctoken=kc.get("enctoken", ""))
    if quotes:
        kc["is_connected"] = True
        core.save_kite_config(kc)
        nifty = quotes.get("NSE:NIFTY 50", "?")
        return JSONResponse({"success": True, "message": f"Connected to Zerodha Kite — NIFTY 50 @ ₹{nifty}", "quotes": quotes})

    # Failed — give the user the actionable reason from the script's own output.
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    hint = tail[-1] if tail else f"exit code {proc.returncode}"
    if proc.returncode == 3:
        hint = "Kite Keychain secrets missing. Store them once (see dashboard/scripts/README.md)."
    elif proc.returncode == 2:
        hint = "Missing Python deps on the server. Run: pip install requests pyotp"
    return JSONResponse({"success": False, "message": f"Could not connect: {hint}"}, status_code=400)


@app.get("/api/trade/positions")
def get_positions() -> Dict[str, Any]:
    from datetime import datetime
    now_ts = datetime.now().strftime("%H:%M:%S")
    latest_source = "Real Market Benchmark (Connect Kite for Direct Live Feed)"
    book = core.TRADE_BOOK

    for t in book:
        if t["status"] == "ACTIVE":
            ltp, source_name = core.fetch_live_market_price(t["symbol"], t.get("is_option", False), t["entry_price"])
            t["current_price"] = ltp
            latest_source = source_name
            if t["transaction_type"] == "BUY":
                gross = (t["current_price"] - t["entry_price"]) * t["quantity"]
            else:
                gross = (t["entry_price"] - t["current_price"]) * t["quantity"]
            costs = core.ZerodhaPlumbingInspector.calculate_trade_costs(
                symbol=t["symbol"], transaction_type=t["transaction_type"],
                product=t.get("product", "CNC"), quantity=t["quantity"],
                price=t["entry_price"], is_option=t.get("is_option", False),
            )
            net = gross - costs.total_friction
            t["gross_pnl"] = round(gross, 2)
            t["friction_costs"] = round(costs.total_friction, 2)
            t["pnl"] = round(net, 2)
            base = t["entry_price"] * t["quantity"]
            t["pnl_pct"] = round((net / base) * 100.0, 2) if base > 0 else 0.0
            # Journal: track excursions while open; finalize when SL/target trips.
            try:
                journal.update_excursion(t["order_id"], t["current_price"])
            except Exception:
                pass
            if t.get("stop_loss_price") and t["transaction_type"] == "BUY" and t["current_price"] <= t["stop_loss_price"]:
                t["status"] = "STOP_LOSS_HIT"
                try:
                    journal.finalize(t["order_id"], t["current_price"], "STOP")
                except Exception:
                    pass
            elif t.get("target_price") and t["transaction_type"] == "BUY" and t["current_price"] >= t["target_price"]:
                t["status"] = "TARGET_HIT"
                try:
                    journal.finalize(t["order_id"], t["current_price"], "TARGET")
                except Exception:
                    pass

    active = [t for t in book if t["status"] == "ACTIVE"]
    closed = [t for t in book if t["status"] != "ACTIVE"]
    unrealized = sum(t["pnl"] for t in active)
    realized = sum(t["pnl"] for t in closed)
    winning = len([t for t in book if t["pnl"] > 0])
    total = len(book)
    core.save_trade_book(book)

    return {
        "summary": {
            "total_pnl": round(unrealized + realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(realized, 2),
            "active_count": len(active),
            "closed_count": len(closed),
            "total_trades": total,
            "win_rate_pct": round((winning / total * 100.0), 1) if total else 0.0,
            "total_capital_invested": round(sum(t["quantity"] * t["entry_price"] for t in active), 2),
            "last_updated": now_ts,
            "data_source": latest_source,
        },
        "trades": book,
    }


# ---------------------------------------------------------------------------
# POST endpoints
# ---------------------------------------------------------------------------

@app.post("/api/plumbing/validate-trade")
async def validate_trade(request: Request) -> Dict[str, Any]:
    p = await request.json()
    inspector = core.ZerodhaPlumbingInspector()
    result = inspector.run_full_trade_validation(
        symbol=p.get("symbol", "RELIANCE"),
        product=p.get("product", "MIS"),
        order_type=p.get("order_type", "LIMIT"),
        transaction_type=p.get("transaction_type", "BUY"),
        quantity=int(p.get("quantity", 10)),
        price=float(p.get("price", 2950.0)),
        trigger_price=float(p["trigger_price"]) if p.get("trigger_price") else None,
        target_price=float(p["target_price"]) if p.get("target_price") else None,
        stop_loss_price=float(p["stop_loss_price"]) if p.get("stop_loss_price") else None,
        is_option=_bool(p.get("is_option", False)),
        available_margin=float(p.get("available_margin", 10_000_000.0)),
        allow_after_hours=_bool(p.get("allow_after_hours", False)),
    )
    return {
        "is_valid": result.is_valid,
        "suggested_limit_price": result.suggested_limit_price,
        "sliced_orders": result.sliced_orders,
        "cost_breakdown": result.cost_breakdown.__dict__ if result.cost_breakdown else None,
        "warnings": result.warnings,
        "errors": result.errors,
        "diagnostics": [d.__dict__ for d in result.diagnostics],
    }


@app.post("/api/strategy/vcp-screen")
async def vcp_screen(request: Request) -> Dict[str, Any]:
    p = await request.json()
    universe = str(p.get("universe", "nifty50")).lower()

    # 1. Prefer the real, computed VCP screen (cached + background-refreshed).
    try:
        from dashboard.live_vcp import get_vcp_candidates
        real, source, screening = get_vcp_candidates(universe)
        if real is not None:
            total_map = {"nifty50": 50, "nifty200": 200, "nifty500": 500}
            return {
                "universe": universe,
                "total_screened": total_map.get(universe, 50),
                "candidates_count": len(real),
                "price_source": source,
                "screening": screening,
                "candidates": real,
            }
        first_call_source = source  # background screen kicked off; show modeled meanwhile
        first_call_screening = screening
    except Exception:
        first_call_source = None
        first_call_screening = False

    # 2. Fallback: modeled snapshot with live price/RS enrichment (first call only).
    data = core.get_vcp_universe_data()
    raw = data.get(universe, data["nifty50"])
    price_source = first_call_source or "Modeled screener snapshot"

    kc = core.KITE_CONFIG
    if kc.get("is_connected") and kc.get("api_key") and kc.get("access_token"):
        try:
            quotes = core.ZerodhaPlumbingInspector.fetch_kite_ltp(
                [f"NSE:{c['symbol']}" for c in raw],
                api_key=kc.get("api_key", ""), access_token=kc.get("access_token", ""), enctoken=kc.get("enctoken", ""),
            )
            if quotes:
                for c in raw:
                    k = f"NSE:{c['symbol']}"
                    if k in quotes and quotes[k] > 0:
                        ltp = quotes[k]
                        c["current_price"] = ltp
                        if ltp > c["pivot_price"]:
                            c["pivot_price"] = round(ltp * 1.008, 1)
                        c["distance_to_pivot_pct"] = max(0.1, round(((c["pivot_price"] - ltp) / ltp) * 100.0, 2))
                price_source = "Zerodha Kite Live API"
        except Exception:
            pass

    if price_source == "Modeled screener snapshot":
        try:
            from dashboard.live_market import get_live_quotes
            q = get_live_quotes([c["symbol"] for c in raw])
            if q:
                for c in raw:
                    rec = q.get(c["symbol"])
                    if rec and rec.get("last_price", 0) > 0:
                        ltp = rec["last_price"]
                        c["current_price"] = ltp
                        if ltp > c["pivot_price"]:
                            c["pivot_price"] = round(ltp * 1.008, 1)
                        c["distance_to_pivot_pct"] = max(0.1, round(((c["pivot_price"] - ltp) / ltp) * 100.0, 2))
                        if "rs_vs_index_6m_pct" in rec:
                            c["rs_vs_index_6m_pct"] = rec["rs_vs_index_6m_pct"]
                price_source = "Yahoo Finance (yfinance) daily close"
        except Exception:
            pass

    # While a real screen runs, keep the honest "screening…" label over the price feed.
    if first_call_screening and first_call_source:
        price_source = first_call_source

    total_map = {"nifty50": 50, "nifty200": 200, "nifty500": 500}
    return {
        "universe": universe,
        "total_screened": total_map.get(universe, 50),
        "candidates_count": len(raw),
        "price_source": price_source,
        "screening": first_call_screening,
        "candidates": raw,
    }


@app.post("/api/options/pricing")
async def options_pricing(request: Request) -> Dict[str, Any]:
    p = await request.json()
    spot = float(p.get("spot", 24000.0))
    strike = float(p.get("strike", 24200.0))
    dte = float(p.get("days_to_expiry", 7.0))
    vol = float(p.get("volatility", 0.15))
    rate = float(p.get("rate", 0.07))
    ot = str(p.get("option_type", "CALL")).upper()

    if core.BLACK_SCHOLES_AVAILABLE:
        opt_type = core.OptionType.CALL if ot == "CALL" else core.OptionType.PUT
        pricer = core.OptionPricer(spot=spot, strike=strike, time_to_expiry=dte / 365.0, volatility=vol, risk_free_rate=rate)
        greeks = pricer.all_greeks(opt_type)
        return {
            "spot": spot, "strike": strike, "days_to_expiry": dte, "implied_volatility": vol,
            "option_type": ot, "calculated_price": round(pricer.price(opt_type), 2),
            "engine": "Black-Scholes (OptionPricer)",
            "greeks": {
                "delta": round(greeks.delta, 4), "gamma": round(greeks.gamma, 5),
                "theta": round(greeks.theta, 4), "vega": round(greeks.vega, 4), "rho": round(greeks.rho, 4),
            },
        }
    return {"spot": spot, "strike": strike, "calculated_price": None, "engine": "unavailable",
            "error": "Black-Scholes engine not importable.",
            "greeks": {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}}


@app.post("/api/strategy/fno-plan")
def fno_plan() -> Dict[str, Any]:
    return {
        "macro_conviction_score": 4.5,
        "dominant_theme": "FII Institutional Inflows + Momentum Continuation",
        "selected_instrument": "NIFTY",
        "trade_card": {
            "instrument": "NIFTY 24000 CE (Weekly Expiry)", "direction": "BULLISH",
            "underlying_spot": 24220.0, "entry_zone": "₹280.00 - ₹290.00",
            "stop_loss_price": 215.00, "target_1": 390.00, "target_2": 460.00,
            "recommended_lots": 1, "total_capital_required": "₹21,525",
            "gtt_levels": {"sl_trigger": 215.00, "t1_trigger": 390.00, "t2_trigger": 460.00},
            "risk_reward_ratio": "1 : 2.5",
            "rules": [
                "Trailing SL: Move SL to Cost once Target 1 is hit",
                "Profit Booking: Book 50% lots at Target 1, trail rest for Target 2",
                "Time Stop: Exit position before 3:15 PM on Expiry Day",
            ],
        },
    }


@app.post("/api/backtest/evaluate")
async def backtest_evaluate(request: Request) -> JSONResponse:
    try:
        p = await request.json()
    except Exception:
        p = {}
    if not core.BACKTEST_EVAL_AVAILABLE:
        return JSONResponse({"total_score": None, "verdict": "UNAVAILABLE",
                             "error": "Backtest evaluator not importable."}, status_code=503)
    result = core.evaluate_backtest(
        total_trades=int(p.get("total_trades", 150)), win_rate=float(p.get("win_rate", 52.0)),
        avg_win_pct=float(p.get("avg_win_pct", 2.4)), avg_loss_pct=float(p.get("avg_loss_pct", 1.3)),
        max_drawdown_pct=float(p.get("max_drawdown_pct", 14.0)), years_tested=float(p.get("years_tested", 5.0)),
        num_parameters=int(p.get("num_parameters", 4)), slippage_tested=_bool(p.get("slippage_tested", True)),
        include_india_costs=_bool(p.get("include_india_costs", True)),
        brokerage_per_trade=float(p.get("brokerage_per_trade", 20.0)),
        avg_trade_value=float(p.get("avg_trade_value", 50000.0)), trade_type=p.get("trade_type", "delivery"),
    )
    resp = core.result_to_dict(result)
    resp["expectancy_per_trade_pct"] = result.adjusted_expectancy
    return JSONResponse(resp)


@app.post("/api/trade/place")
async def place_trade(request: Request) -> JSONResponse:
    import os
    from datetime import datetime
    p = await request.json()
    mode = p.get("mode", "mock")
    is_option = _bool(p.get("is_option", True), True)
    inspector = core.ZerodhaPlumbingInspector()
    validation = inspector.run_full_trade_validation(
        symbol=p.get("symbol", "NIFTY"), product=p.get("product", "MIS"),
        order_type=p.get("order_type", "LIMIT"), transaction_type=p.get("transaction_type", "BUY"),
        quantity=int(p.get("quantity", 75)), price=float(p.get("price", 140.0)),
        stop_loss_price=float(p["stop_loss_price"]) if p.get("stop_loss_price") else None,
        target_price=float(p["target_price"]) if p.get("target_price") else None,
        is_option=is_option, available_margin=float(p.get("available_margin", 10_000_000.0)),
        allow_after_hours=_bool(p.get("allow_after_hours", False)),
    )
    if not validation.is_valid:
        return JSONResponse({"success": False, "message": "Order failed plumbing validation.",
                             "errors": validation.errors,
                             "diagnostics": [d.__dict__ for d in validation.diagnostics]}, status_code=400)

    order_id = "MOCK_ORD_" + os.urandom(3).hex().upper()
    entry = float(p.get("price", 140.0))
    rec = {
        "order_id": order_id, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": inspector.resolve_symbol(p.get("symbol", "NIFTY")), "product": p.get("product", "NRML"),
        "transaction_type": p.get("transaction_type", "BUY"), "quantity": int(p.get("quantity", 75)),
        "entry_price": entry, "current_price": entry, "pnl": 0.0, "pnl_pct": 0.0,
        "stop_loss_price": float(p["stop_loss_price"]) if p.get("stop_loss_price") else None,
        "target_price": float(p["target_price"]) if p.get("target_price") else None,
        "status": "ACTIVE", "is_option": is_option,
        "strategy_origin": p.get("strategy_origin", "User Manual Order"),
    }
    core.TRADE_BOOK.insert(0, rec)
    core.save_trade_book(core.TRADE_BOOK)

    # Journal the entry with its signal-feature snapshot (for outcome attribution).
    try:
        journal.record_entry(
            order_id=order_id, symbol=rec["symbol"], entry_price=entry,
            stop=rec.get("stop_loss_price"), target=rec.get("target_price"),
            qty=rec["quantity"], source=rec["strategy_origin"], is_option=is_option,
            signal=p.get("signal") or {},
        )
    except Exception:
        pass

    return JSONResponse({
        "success": True, "mode": mode, "order_id": order_id,
        "message": f"Order executed successfully in {mode.upper()} mode.",
        "sliced_orders_executed": len(validation.sliced_orders),
        "cost_breakdown": validation.cost_breakdown.__dict__ if validation.cost_breakdown else None,
    })


@app.post("/api/trade/square-off")
async def square_off(request: Request) -> JSONResponse:
    p = await request.json()
    oid = p.get("order_id")
    for t in core.TRADE_BOOK:
        if t["order_id"] == oid:
            t["status"] = "CLOSED"
            core.save_trade_book(core.TRADE_BOOK)
            try:
                journal.finalize(oid, t.get("current_price", t["entry_price"]), "MANUAL")
            except Exception:
                pass
            return JSONResponse({"success": True, "message": f"Position {oid} squared off successfully."})
    return JSONResponse({"success": False, "message": f"Order {oid} not found."}, status_code=404)


@app.post("/api/trade/square-off-all")
def square_off_all() -> Dict[str, Any]:
    count = 0
    for t in core.TRADE_BOOK:
        if t["status"] == "ACTIVE":
            t["status"] = "CLOSED"
            count += 1
    core.save_trade_book(core.TRADE_BOOK)
    return {"success": True, "message": f"Squared off {count} active position(s)."}


@app.post("/api/trade/clear-all")
def clear_all() -> Dict[str, Any]:
    core.TRADE_BOOK.clear()
    core.save_trade_book(core.TRADE_BOOK)
    return {"success": True, "message": "Trade book cleared successfully."}


@app.post("/api/zerodha/config")
async def post_zerodha_config(request: Request) -> JSONResponse:
    p = await request.json()
    api_key = p.get("api_key", "").strip()
    access_token = p.get("access_token", "").strip()
    enctoken = p.get("enctoken", "").strip()
    test = core.ZerodhaPlumbingInspector.fetch_kite_ltp(
        ["NSE:NIFTY 50", "NSE:RELIANCE"], api_key=api_key, access_token=access_token, enctoken=enctoken)
    if test or enctoken or (api_key and access_token):
        core.KITE_CONFIG.update({"api_key": api_key, "access_token": access_token,
                                 "enctoken": enctoken, "is_connected": True})
        core.save_kite_config(core.KITE_CONFIG)
        msg = (f"Successfully connected to Zerodha Kite Live API! NIFTY 50 @ ₹{test.get('NSE:NIFTY 50', 'N/A')}"
               if test else "Zerodha Kite credentials saved.")
        return JSONResponse({"success": True, "message": msg, "quotes": test or {}})
    return JSONResponse({"success": False, "message": "Could not connect to Zerodha Kite API."}, status_code=400)


# Serve the UI (mounted last so /api/* routes win). Prefer the built React app
# (dashboard/web/dist) so one process serves API + UI on boot with no Vite; fall
# back to the classic static UI if the bundle hasn't been built.
_UI_DIR = WEB_DIST if (WEB_DIST / "index.html").exists() else STATIC_DIR
app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="static")
