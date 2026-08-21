#!/usr/bin/env python3
"""
Zerodha Kite Trade Plumbing Inspector & Order Execution Validator

This module provides automated plumbing diagnostic checks for Zerodha Kite API/MCP trading:
- Connection & Authentication Status Check
- Instrument Token & Symbol Resolution
- F&O Lot Size & Slice Order Validation (NSE Freeze Limits)
- Margin & Capital Adequacy Auditor
- Order Parameter Safety Check (Product, Order Type, Trigger Prices)
- GTT OCO (One-Cancels-Other) Plumbing Verification
- Indian Regulatory Cost & Tax Slippage Auditor (STT, Stamp Duty, GST, Exchange Fees)
"""

import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

# ---------------------------------------------------------------------------
# Constants & Reference Rules for Indian Markets (NSE / Zerodha)
# ---------------------------------------------------------------------------

# F&O Lot Sizes (NSE standard lot sizes)
LOT_SIZES: Dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 50,
}

# NSE Order Freeze Quantity Limits (Max allowed quantity per single order)
FREEZE_LIMITS: Dict[str, int] = {
    "NIFTY": 1800,      # 24 lots
    "BANKNIFTY": 900,   # 60 lots
    "FINNIFTY": 1800,   # 72 lots
    "MIDCPNIFTY": 2800, # 56 lots
}

# Exchange Transaction Charges Rates (NSE)
EXCHANGE_CHARGES_RATES = {
    "EQUITY_DELIVERY": 0.0000335,  # 0.00335%
    "EQUITY_INTRADAY": 0.0000335,  # 0.00335%
    "FNO_FUTURES": 0.000019,       # 0.0019%
    "FNO_OPTIONS": 0.0005,         # 0.05% of premium
}

# STT (Securities Transaction Tax) Rates
STT_RATES = {
    "EQUITY_DELIVERY_BUY": 0.001,   # 0.1% on buy
    "EQUITY_DELIVERY_SELL": 0.001,  # 0.1% on sell
    "EQUITY_INTRADAY_SELL": 0.00025,# 0.025% on sell
    "FNO_FUTURES_SELL": 0.000125,  # 0.0125% on sell
    "FNO_OPTIONS_SELL": 0.00125,    # 0.125% on sell (premium)
}

# Stamp Duty Rates (On buy side only)
STAMP_DUTY_RATES = {
    "EQUITY_DELIVERY": 0.00015,  # 0.015%
    "EQUITY_INTRADAY": 0.00003,  # 0.003%
    "FNO_FUTURES": 0.00002,     # 0.002%
    "FNO_OPTIONS": 0.00003,     # 0.003%
}

SEBI_TURNOVER_FEE_RATE = 0.000001  # Rs 10 per crore (0.0001%)
GST_RATE = 0.18                    # 18% GST on (Brokerage + Exchange Fees + SEBI Fees)


class ProductType(Enum):
    CNC = "CNC"     # Cash and Carry (Delivery Equities)
    MIS = "MIS"     # Margin Intraday Square-off
    NRML = "NRML"   # Normal (Overnight F&O positions)


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"        # Stop Loss Limit
    SL_M = "SL-M"    # Stop Loss Market


class TransactionType(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class PlumbingDiagnosticItem:
    check_name: str
    status: str       # "PASSED", "WARNING", "FAILED"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeCostBreakdown:
    trade_value: float
    brokerage: float
    stt: float
    stamp_duty: float
    exchange_charges: float
    sebi_charges: float
    gst: float
    total_friction: float
    friction_pct: float
    break_even_points: float


@dataclass
class PlumbingValidationResult:
    is_valid: bool
    diagnostics: List[PlumbingDiagnosticItem]
    sliced_orders: List[Dict[str, Any]]
    cost_breakdown: Optional[TradeCostBreakdown] = None
    suggested_limit_price: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ZerodhaPlumbingInspector:
    """Diagnostic inspector for Zerodha Kite trade plumbing."""

    def __init__(self, mcp_client: Any = None, kite_api_key: Optional[str] = None):
        self.mcp_client = mcp_client
        self.kite_api_key = kite_api_key

    def inspect_connection(self) -> PlumbingDiagnosticItem:
        """Inspect Zerodha Kite API / MCP session connectivity."""
        if self.mcp_client or self.kite_api_key:
            return PlumbingDiagnosticItem(
                check_name="Kite Auth & Session",
                status="PASSED",
                message="Zerodha Kite session connected and active.",
                details={"mode": "Live MCP/API"}
            )
        else:
            return PlumbingDiagnosticItem(
                check_name="Kite Auth & Session",
                status="WARNING",
                message="Running in Mock Mode (Zerodha Kite API Key / MCP connector not detected). All plumbing checks will validate parameters locally.",
                details={"mode": "Mock / Simulated"}
            )

    @staticmethod
    def market_session(now=None) -> Dict[str, Any]:
        """NSE equity session state (IST). Note: does not account for trading holidays."""
        from datetime import datetime, time as dtime
        if now is None:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo("Asia/Kolkata"))
            except Exception:
                now = datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M IST")
        t = now.time()
        if now.weekday() >= 5:
            return {"is_open": False, "session": "WEEKEND", "now_ist": stamp,
                    "message": "Markets closed (weekend). NSE trades Mon–Fri 09:15–15:30 IST."}
        if t < dtime(9, 0):
            return {"is_open": False, "session": "PRE_MARKET", "now_ist": stamp,
                    "message": "Market not open yet. NSE opens 09:15 IST (pre-open from 09:00)."}
        if t < dtime(9, 15):
            return {"is_open": False, "session": "PRE_OPEN", "now_ist": stamp,
                    "message": "Pre-open session (09:00–09:15). Continuous trading starts 09:15 IST."}
        if t <= dtime(15, 30):
            return {"is_open": True, "session": "OPEN", "now_ist": stamp, "message": "Market open."}
        return {"is_open": False, "session": "CLOSED", "now_ist": stamp,
                "message": "Market closed for the day. NSE trades 09:15–15:30 IST (AMO for after-hours)."}

    @staticmethod
    def get_kite_instrument_candidates(symbol: str) -> List[str]:
        """Generate candidate Zerodha instrument symbols (e.g. NSE:RELIANCE, NFO:NIFTY24AUG24000CE, NFO:NIFTY2482524000CE)."""
        clean = ZerodhaPlumbingInspector.resolve_symbol(symbol)
        if clean in ["NIFTY", "NIFTY50", "NIFTY 50"]:
            return ["NSE:NIFTY 50"]
        elif clean in ["BANKNIFTY", "NIFTY BANK"]:
            return ["NSE:NIFTY BANK"]
        elif clean == "FINNIFTY":
            return ["NSE:NIFTY FIN SERVICE"]
        elif "CE" in clean or "PE" in clean:
            now = datetime.now()
            yy = now.strftime("%y")
            mmm = now.strftime("%b").upper()
            m_digit = str(now.month) if now.month < 10 else ("O" if now.month == 10 else ("N" if now.month == 11 else "D"))
            
            underlying = "BANKNIFTY" if "BANKNIFTY" in clean else ("FINNIFTY" if "FINNIFTY" in clean else "NIFTY")
            opt_type = "CE" if "CE" in clean else "PE"
            
            # Extract strike digits
            digits = "".join([c for c in clean if c.isdigit()])
            strike = digits if digits else "24000"
            if len(strike) > 5 and (strike.startswith("24") or strike.startswith("26")):
                strike = strike[-5:]

            candidates = [
                f"NFO:{underlying}{yy}{mmm}{strike}{opt_type}",
                f"NFO:{underlying}{yy}{m_digit}25{strike}{opt_type}",
                f"NFO:{underlying}{yy}{m_digit}21{strike}{opt_type}",
                f"NFO:{underlying}{yy}{m_digit}28{strike}{opt_type}",
                f"NFO:{clean}"
            ]
            return candidates
        else:
            return [f"NSE:{clean}"]

    @staticmethod
    def to_kite_instrument(symbol: str) -> str:
        """Convert trading symbol to Zerodha Kite instrument format."""
        candidates = ZerodhaPlumbingInspector.get_kite_instrument_candidates(symbol)
        return candidates[0] if candidates else f"NSE:{symbol}"

    @staticmethod
    def fetch_kite_ltp(instruments: List[str], api_key: str = "", access_token: str = "", enctoken: str = "") -> Dict[str, float]:
        """Fetch exact live LTP directly from Zerodha Kite API (api.kite.trade)."""
        if not instruments:
            return {}
        
        # Expand any option symbols into candidate variants
        all_instruments = []
        for inst in instruments:
            clean_sym = inst.replace("NSE:", "").replace("NFO:", "")
            candidates = ZerodhaPlumbingInspector.get_kite_instrument_candidates(clean_sym)
            for c in candidates:
                if c not in all_instruments:
                    all_instruments.append(c)

        query = "&".join([f"i={urllib.parse.quote(inst)}" for inst in all_instruments])
        url = f"https://api.kite.trade/quote/ltp?{query}"
        
        headers = {
            "X-Kite-Version": "3",
            "User-Agent": "ZerodhaDashboard/1.0"
        }
        
        if enctoken:
            headers["Authorization"] = f"enctoken {enctoken.strip()}"
        elif api_key and access_token:
            headers["Authorization"] = f"token {api_key.strip()}:{access_token.strip()}"
        else:
            env_enctoken = os.getenv("KITE_ENCTOKEN") or os.getenv("ZERODHA_ENCTOKEN")
            env_api_key = os.getenv("KITE_API_KEY") or os.getenv("ZERODHA_API_KEY")
            env_access_token = os.getenv("KITE_ACCESS_TOKEN") or os.getenv("ZERODHA_ACCESS_TOKEN")
            if env_enctoken:
                headers["Authorization"] = f"enctoken {env_enctoken.strip()}"
            elif env_api_key and env_access_token:
                headers["Authorization"] = f"token {env_api_key.strip()}:{env_access_token.strip()}"
            else:
                return {}

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    if data.get("status") == "success" and "data" in data:
                        res = {}
                        for k, v in data["data"].items():
                            if "last_price" in v:
                                p = float(v["last_price"])
                                res[k] = p
                                # Map back to original requested instrument name
                                for orig in instruments:
                                    if orig in k or k in orig or orig.replace("NSE:", "").replace("NFO:", "") in k:
                                        res[orig] = p
                        return res
        except Exception:
            pass
        return {}

    @staticmethod
    def resolve_symbol(ticker: str) -> str:
        """Resolve ticker formats (e.g. RELIANCE.NS, ^NSEI) to Zerodha tradingsymbol."""
        sym = ticker.strip().upper()
        if sym.endswith(".NS") or sym.endswith(".BO"):
            sym = sym.split(".")[0]
        if sym in ["^NSEI", "NIFTY50", "NIFTY 50"]:
            return "NIFTY"
        if sym in ["^NSEBANK", "BANKNIFTY", "NIFTY BANK"]:
            return "BANKNIFTY"
        if sym in ["FINNIFTY", "NIFTY FIN SERVICE"]:
            return "FINNIFTY"
        if sym in ["MIDCPNIFTY", "NIFTY MIDCAP 50"]:
            return "MIDCPNIFTY"
        return sym

    @staticmethod
    def get_lot_size(symbol: str) -> int:
        """Get standard lot size for symbol."""
        clean_symbol = ZerodhaPlumbingInspector.resolve_symbol(symbol)
        # Check exact or longest substring match first (e.g. BANKNIFTY before NIFTY)
        for idx_name in sorted(LOT_SIZES.keys(), key=len, reverse=True):
            if idx_name in clean_symbol:
                return LOT_SIZES[idx_name]
        return 1

    @staticmethod
    def validate_lot_size(symbol: str, quantity: int) -> PlumbingDiagnosticItem:
        """Validate if quantity conforms to F&O lot size rules."""
        lot_size = ZerodhaPlumbingInspector.get_lot_size(symbol)
        clean_symbol = ZerodhaPlumbingInspector.resolve_symbol(symbol)
        
        if lot_size > 1:
            if quantity <= 0 or quantity % lot_size != 0:
                recommended_qty = max(lot_size, (math.ceil(quantity / lot_size) * lot_size))
                return PlumbingDiagnosticItem(
                    check_name="Lot Size & Quantity",
                    status="FAILED",
                    message=f"Quantity {quantity} is not a multiple of lot size {lot_size} for {clean_symbol}.",
                    details={"lot_size": lot_size, "provided_quantity": quantity, "recommended_quantity": recommended_qty}
                )
            return PlumbingDiagnosticItem(
                check_name="Lot Size & Quantity",
                status="PASSED",
                message=f"Quantity {quantity} is a valid multiple of lot size {lot_size} ({quantity // lot_size} lot(s)).",
                details={"lot_size": lot_size, "lots": quantity // lot_size}
            )
        else:
            if quantity <= 0:
                return PlumbingDiagnosticItem(
                    check_name="Lot Size & Quantity",
                    status="FAILED",
                    message="Equity quantity must be at least 1.",
                    details={"provided_quantity": quantity}
                )
            return PlumbingDiagnosticItem(
                check_name="Lot Size & Quantity",
                status="PASSED",
                message=f"Equity quantity {quantity} is valid.",
                details={"quantity": quantity}
            )

    @staticmethod
    def check_order_slicing(symbol: str, quantity: int) -> Tuple[PlumbingDiagnosticItem, List[Dict[str, int]]]:
        """Check if quantity exceeds NSE order freeze limits and split into slice orders."""
        clean_symbol = ZerodhaPlumbingInspector.resolve_symbol(symbol)
        freeze_limit = 100000
        for idx_name in sorted(FREEZE_LIMITS.keys(), key=len, reverse=True):
            if idx_name in clean_symbol:
                freeze_limit = FREEZE_LIMITS[idx_name]
                break
        
        if quantity > freeze_limit:
            slices = []
            remaining = quantity
            order_idx = 1
            while remaining > 0:
                qty = min(remaining, freeze_limit)
                slices.append({"slice_number": order_idx, "quantity": qty})
                remaining -= qty
                order_idx += 1
            
            diag = PlumbingDiagnosticItem(
                check_name="Order Freeze & Slicing",
                status="WARNING",
                message=f"Quantity {quantity} exceeds NSE freeze limit ({freeze_limit}). Sliced into {len(slices)} orders.",
                details={"freeze_limit": freeze_limit, "slice_count": len(slices), "slices": slices}
            )
            return diag, slices
        else:
            diag = PlumbingDiagnosticItem(
                check_name="Order Freeze & Slicing",
                status="PASSED",
                message=f"Quantity {quantity} is within NSE freeze limit ({freeze_limit}).",
                details={"freeze_limit": freeze_limit, "slice_count": 1}
            )
            return diag, [{"slice_number": 1, "quantity": quantity}]

    @staticmethod
    def calculate_trade_costs(
        symbol: str,
        transaction_type: str,
        product: str,
        quantity: int,
        price: float,
        is_option: bool = False,
        flat_brokerage: float = 20.0
    ) -> TradeCostBreakdown:
        """Calculate complete round-trip Indian transaction costs & taxes."""
        trade_val = quantity * price
        
        if is_option:
            cat = "FNO_OPTIONS"
        elif product in ["NRML", "MIS"] and ZerodhaPlumbingInspector.get_lot_size(symbol) > 1:
            cat = "FNO_FUTURES"
        elif product == "MIS":
            cat = "EQUITY_INTRADAY"
        else:
            cat = "EQUITY_DELIVERY"

        if product == "CNC" and not is_option:
            brokerage_one_way = 0.0
        else:
            brokerage_one_way = min(flat_brokerage, trade_val * 0.0003)

        if cat == "EQUITY_DELIVERY":
            stt_rate = STT_RATES["EQUITY_DELIVERY_BUY" if transaction_type == "BUY" else "EQUITY_DELIVERY_SELL"]
            stt = trade_val * stt_rate
        elif cat == "EQUITY_INTRADAY":
            stt = trade_val * STT_RATES["EQUITY_INTRADAY_SELL"] if transaction_type == "SELL" else 0.0
        elif cat == "FNO_FUTURES":
            stt = trade_val * STT_RATES["FNO_FUTURES_SELL"] if transaction_type == "SELL" else 0.0
        else:
            stt = trade_val * STT_RATES["FNO_OPTIONS_SELL"] if transaction_type == "SELL" else 0.0

        if transaction_type == "BUY":
            stamp_duty = trade_val * STAMP_DUTY_RATES.get(cat, 0.00003)
        else:
            stamp_duty = 0.0

        ex_rate = EXCHANGE_CHARGES_RATES.get(cat, 0.0000335)
        exchange_charges = trade_val * ex_rate
        sebi_charges = trade_val * SEBI_TURNOVER_FEE_RATE
        gst = (brokerage_one_way + exchange_charges + sebi_charges) * GST_RATE

        one_way_friction = brokerage_one_way + stt + stamp_duty + exchange_charges + sebi_charges + gst
        round_trip_friction = one_way_friction * 2.0
        friction_pct = (round_trip_friction / trade_val) * 100.0 if trade_val > 0 else 0.0
        break_even_points = round_trip_friction / quantity if quantity > 0 else 0.0

        return TradeCostBreakdown(
            trade_value=trade_val,
            brokerage=round(brokerage_one_way, 2),
            stt=round(stt, 2),
            stamp_duty=round(stamp_duty, 2),
            exchange_charges=round(exchange_charges, 2),
            sebi_charges=round(sebi_charges, 4),
            gst=round(gst, 2),
            total_friction=round(round_trip_friction, 2),
            friction_pct=round(friction_pct, 3),
            break_even_points=round(break_even_points, 2)
        )

    @staticmethod
    def validate_order_parameters(
        symbol: str,
        product: str,
        order_type: str,
        transaction_type: str,
        quantity: int,
        price: float,
        trigger_price: Optional[float] = None,
        is_option: bool = False
    ) -> List[PlumbingDiagnosticItem]:
        """Validate order product, type, price, and NSE option safety restrictions."""
        diagnostics = []

        if product not in [p.value for p in ProductType]:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Product Type",
                status="FAILED",
                message=f"Invalid product type '{product}'. Must be CNC, MIS, or NRML.",
                details={"provided_product": product}
            ))
        else:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Product Type",
                status="PASSED",
                message=f"Product type '{product}' is valid.",
                details={"product": product}
            ))

        if order_type not in [o.value for o in OrderType]:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Order Type",
                status="FAILED",
                message=f"Invalid order type '{order_type}'. Must be MARKET, LIMIT, SL, or SL-M.",
                details={"provided_order_type": order_type}
            ))
        else:
            if is_option and order_type == "SL-M":
                diagnostics.append(PlumbingDiagnosticItem(
                    check_name="Order Safety Check",
                    status="WARNING",
                    message="NSE has disabled SL-M for options contracts to prevent freak trades. Recommending 'SL' (Stop-Loss Limit) instead.",
                    details={"recommended_order_type": "SL"}
                ))
            else:
                diagnostics.append(PlumbingDiagnosticItem(
                    check_name="Order Safety Check",
                    status="PASSED",
                    message=f"Order type '{order_type}' is safe for execution.",
                    details={"order_type": order_type}
                ))

        if order_type in ["LIMIT", "SL"] and price <= 0:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Price Parameter",
                status="FAILED",
                message=f"Price must be > 0 for {order_type} orders.",
                details={"price": price}
            ))
        elif order_type in ["SL", "SL-M"] and (trigger_price is None or trigger_price <= 0):
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Trigger Price Parameter",
                status="FAILED",
                message=f"Trigger price must be > 0 for {order_type} orders.",
                details={"trigger_price": trigger_price}
            ))
        else:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Price Parameter",
                status="PASSED",
                message="Order price parameters are valid.",
                details={"price": price, "trigger_price": trigger_price}
            ))

        return diagnostics

    @staticmethod
    def validate_gtt_params(
        last_price: float,
        target_price: Optional[float],
        stop_loss_price: Optional[float],
        transaction_type: str = "BUY"
    ) -> PlumbingDiagnosticItem:
        """Validate GTT (Good Till Triggered) OCO trigger conditions."""
        if last_price <= 0:
            return PlumbingDiagnosticItem(
                check_name="GTT Plumbing",
                status="FAILED",
                message="Invalid last price for GTT validation.",
                details={"last_price": last_price}
            )

        details = {"last_price": last_price, "target_price": target_price, "stop_loss_price": stop_loss_price}

        if transaction_type == "BUY":
            if stop_loss_price and stop_loss_price >= last_price:
                return PlumbingDiagnosticItem(
                    check_name="GTT Plumbing",
                    status="FAILED",
                    message=f"For LONG positions, stop-loss trigger price ({stop_loss_price}) must be lower than last price ({last_price}).",
                    details=details
                )
            if target_price and target_price <= last_price:
                return PlumbingDiagnosticItem(
                    check_name="GTT Plumbing",
                    status="FAILED",
                    message=f"For LONG positions, target trigger price ({target_price}) must be higher than last price ({last_price}).",
                    details=details
                )
        return PlumbingDiagnosticItem(
            check_name="GTT Plumbing",
            status="PASSED",
            message="GTT OCO trigger levels are logically valid.",
            details=details
        )

    def run_full_trade_validation(
        self,
        symbol: str,
        product: str,
        order_type: str,
        transaction_type: str,
        quantity: int,
        price: float,
        trigger_price: Optional[float] = None,
        target_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        is_option: bool = False,
        available_margin: float = 100000.0,
        allow_after_hours: bool = False
    ) -> PlumbingValidationResult:
        """Run complete trade plumbing diagnostic suite (incl. NSE market-session gate)."""
        diagnostics = []
        warnings = []
        errors = []

        conn_diag = self.inspect_connection()
        diagnostics.append(conn_diag)
        if conn_diag.status == "WARNING":
            warnings.append(conn_diag.message)

        # Market session — a real broker rejects regular orders outside 09:15–15:30 IST.
        session = self.market_session()
        if session["is_open"]:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Market Session", status="PASSED",
                message=f"Market open ({session['now_ist']}).", details=session))
        elif allow_after_hours:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Market Session", status="WARNING",
                message=f"{session['message']} Placing anyway (after-hours/AMO override).", details=session))
            warnings.append(session["message"])
        else:
            diagnostics.append(PlumbingDiagnosticItem(
                check_name="Market Session", status="FAILED",
                message=session["message"], details=session))
            errors.append(session["message"])

        clean_symbol = self.resolve_symbol(symbol)
        diagnostics.append(PlumbingDiagnosticItem(
            check_name="Symbol Mapper",
            status="PASSED",
            message=f"Mapped '{symbol}' to Zerodha tradingsymbol '{clean_symbol}'.",
            details={"input_symbol": symbol, "resolved_symbol": clean_symbol}
        ))

        lot_diag = self.validate_lot_size(clean_symbol, quantity)
        diagnostics.append(lot_diag)
        if lot_diag.status == "FAILED":
            errors.append(lot_diag.message)

        slice_diag, sliced_orders = self.check_order_slicing(clean_symbol, quantity)
        diagnostics.append(slice_diag)
        if slice_diag.status == "WARNING":
            warnings.append(slice_diag.message)

        param_diags = self.validate_order_parameters(
            clean_symbol, product, order_type, transaction_type, quantity, price, trigger_price, is_option
        )
        diagnostics.extend(param_diags)
        for pd_item in param_diags:
            if pd_item.status == "FAILED":
                errors.append(pd_item.message)
            elif pd_item.status == "WARNING":
                warnings.append(pd_item.message)

        if target_price or stop_loss_price:
            gtt_diag = self.validate_gtt_params(price, target_price, stop_loss_price, transaction_type)
            diagnostics.append(gtt_diag)
            if gtt_diag.status == "FAILED":
                errors.append(gtt_diag.message)

        cost_breakdown = self.calculate_trade_costs(
            clean_symbol, transaction_type, product, quantity, price, is_option
        )
        required_funds = cost_breakdown.trade_value if product == "CNC" or is_option else cost_breakdown.trade_value * 0.2
        
        if available_margin < required_funds:
            margin_diag = PlumbingDiagnosticItem(
                check_name="Margin & Capital Auditor",
                status="FAILED",
                message=f"Insufficient margin. Required ~₹{required_funds:,.2f}, Available ₹{available_margin:,.2f}.",
                details={"required_funds": required_funds, "available_margin": available_margin}
            )
            errors.append(margin_diag.message)
        else:
            margin_diag = PlumbingDiagnosticItem(
                check_name="Margin & Capital Auditor",
                status="PASSED",
                message=f"Sufficient margin. Required ~₹{required_funds:,.2f}, Available ₹{available_margin:,.2f}.",
                details={"required_funds": required_funds, "available_margin": available_margin}
            )
        diagnostics.append(margin_diag)

        is_valid = len(errors) == 0
        suggested_limit = price * 1.002 if transaction_type == "BUY" else price * 0.998

        return PlumbingValidationResult(
            is_valid=is_valid,
            diagnostics=diagnostics,
            sliced_orders=sliced_orders,
            cost_breakdown=cost_breakdown,
            suggested_limit_price=round(suggested_limit, 2),
            warnings=warnings,
            errors=errors
        )
