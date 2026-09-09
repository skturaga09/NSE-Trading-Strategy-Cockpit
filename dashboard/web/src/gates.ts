// The 14 pre-trade discipline gates — single source of truth, shared by the Intraday console
// (where they're evaluated) and the Journal decision log (where failures are shown by name).
export const GATE_LABELS = [
  "Market regime is clearly identified",
  "Candidate exactly matches one approved setup",
  "15-min & 5-min price structure supports the direction",
  "VWAP location and slope support the direction",
  "Relative volume confirms the trigger",
  "Defined S/R leaves distance for at least 2R after costs",
  "NIFTY/BANKNIFTY alignment or breadth does not materially conflict",
  "No high-impact scheduled event in the restricted window",
  "Option contract is liquid with acceptable bid-ask spread",
  "Underlying, premium, expiry, lot size, entry, stop & costs verified",
  "Max loss ≤ ₹1,000 including costs & slippage",
  "Daily P&L, entries & consecutive-loss count permit a new trade",
  "Documented backtest / paper sample in the SAME regime",
  "Defined entry trigger, invalidation, time stop, target & cancellation",
];

// Compact labels for tight UI (the decision-log cell); full text is shown on hover.
export const GATE_SHORT = [
  "Regime", "Setup match", "Structure", "VWAP", "Rel volume", "2R distance",
  "Breadth align", "Event window", "Liquidity", "Contract verified", "Max loss ≤₹1k",
  "Daily rules", "Backtest sample", "Trade plan",
];

export function gateName(n: number): string {       // n is 1-indexed
  return GATE_LABELS[n - 1] ?? `gate ${n}`;
}
export function gateShort(n: number): string {
  return GATE_SHORT[n - 1] ?? `gate ${n}`;
}
