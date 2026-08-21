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

STATIC_DIR = Path(__file__).parent / "static"

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


@app.get("/api/strategy/recommendations")
def recommendations() -> Dict[str, Any]:
    return core.build_trade_recommendations()


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
            if t.get("stop_loss_price") and t["transaction_type"] == "BUY" and t["current_price"] <= t["stop_loss_price"]:
                t["status"] = "STOP_LOSS_HIT"
            elif t.get("target_price") and t["transaction_type"] == "BUY" and t["current_price"] >= t["target_price"]:
                t["status"] = "TARGET_HIT"

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
    data = core.get_vcp_universe_data()
    raw = data.get(universe, data["nifty50"])
    price_source = "Modeled screener snapshot"

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

    total_map = {"nifty50": 50, "nifty200": 200, "nifty500": 500}
    return {
        "universe": universe,
        "total_screened": total_map.get(universe, 50),
        "candidates_count": len(raw),
        "price_source": price_source,
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


# Serve the classic static UI (mounted last so /api/* routes win).
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
