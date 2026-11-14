// Acceptance: UNAVAILABLE ⇒ "—" with the reason; STALE ⇒ visible stale marking; SIMULATED and ACTUAL never in one total.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Envelope } from "../api";
import { FoRoot, Panel, V } from "../core";
import { Performance } from "../panels/Performance";
import { Radar } from "../panels/Radar";
import { SignalDetail } from "../panels/SignalDetail";
import { Trades } from "../panels/Trades";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const env = <T,>(over: Partial<Envelope<T>>): Envelope<T> => ({
  panel: "radar", mode: "REPLAY", now_ns: 1_793_950_000_000_000_000, status: "OK", reason: null,
  provenance: { source: "fixture", observed_ns: 1_793_949_990_000_000_000, received_ns: null, processed_ns: null, tz: "Asia/Kolkata" },
  age_s: 10, stale_after_s: 120, config_version: "v12", data: null, ...over });

const wrap = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><FoRoot>{ui}</FoRoot></QueryClientProvider>);

describe("values", () => {
  it("renders UNAVAILABLE as an em dash with its reason, in a tooltip inside the scoped root", () => {
    wrap(<V v={{ UNAVAILABLE: "OI_WINDOW_DISABLED: no measured OI cadence" }} />);
    const dash = screen.getByLabelText("unavailable: OI_WINDOW_DISABLED: no measured OI cadence");
    expect(dash.textContent).toBe("—");
    fireEvent.focus(dash.parentElement!);
    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toContain("OI_WINDOW_DISABLED");
    expect(tip.closest("[data-fo-portal]")).not.toBeNull();          // D4: portal inside the root, not document.body
    expect(tip.closest("[data-fo-engine]")).not.toBeNull();
  });
  it("renders a value with tabular numerals and never invents one", () => {
    wrap(<><V v={1234.5} f={(x) => x.toFixed(2)} /><V v={null} /></>);
    expect(screen.getByText("1234.50").className).toContain("fo-num");
    expect(screen.getByLabelText("unavailable").textContent).toBe("—");
  });
});

describe("signal detail with no row picked", () => {
  it("lists the session's signals, best score first, and opens the one clicked (never stuck on Loading…)", async () => {
    const row = (id: string, symbol: string, score: number, status: string) => ({ recommendation_id: id, signal_id: id,
      as_of: 1_793_949_000_000_000_000, symbol, contract: "X", direction: "LONG", signal: "BULLISH_SWEEP_REVERSAL", family: "E",
      kind: "FUT", oi_pct: null, price_pct: null, rvol: null, score, score_available_max: 71.7, band: "", timeliness: "LATE",
      entry: 1, sl: 1, target: 1, status, lifecycle_state: null, rejected_reasons: [], risk_reasons: [], warnings: [], labels: [] });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(env({ panel: "radar",
      data: { rows: [row("a", "ABB", 41.9, "REJECTED"), row("h", "HINDALCO", 66.7, "REJECTED")], feature_window_min: 15 } })))));
    const picked: (string | null)[] = [];
    wrap(<SignalDetail view={{ date: "2026-11-06", asOf: null }} id={null} onPick={(id) => picked.push(id)} />);
    expect(screen.queryByText("Loading…")).toBeNull();
    const first = await screen.findByRole("button", { name: "HINDALCO" });
    expect(screen.getByText(/No signal picked\. 2 signals this session/)).not.toBeNull();
    const names = screen.getAllByRole("button").map((b) => b.textContent);
    expect(names.indexOf("HINDALCO")).toBeLessThan(names.indexOf("ABB"));       // best score first
    fireEvent.click(first);
    expect(picked).toEqual(["h"]);
  });
  it("an open signal has a way back to the list", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(env({ panel: "signal", data: null })))));
    const picked: (string | null)[] = [];
    wrap(<SignalDetail view={{ date: "2026-11-06", asOf: null }} id="h" onPick={(id) => picked.push(id)} />);
    fireEvent.click(screen.getByRole("button", { name: "← Back to all signals" }));
    expect(picked).toEqual([null]);
  });
  it("still shows Loading… while a panel's data is on its way", () => {
    wrap(<Panel title="x" env={undefined}>body</Panel>);
    expect(screen.getByText("Loading…")).not.toBeNull();
  });
});

describe("radar calls", () => {
  it("shows a plain BUY/CHECK/AVOID call with its reason, the option, and the real-price track record", async () => {
    const row = (id: string, symbol: string, action: string, why: string) => ({ recommendation_id: id, signal_id: id,
      as_of: 1_793_949_000_000_000_000, symbol, contract: `${symbol}26NOV100CE`, direction: "LONG", signal: "S", family: "E",
      kind: "REVERSAL", oi_pct: null, price_pct: null, rvol: null, score: 1, score_available_max: 2, band: "", timeliness: "LATE",
      entry: 1, sl: 1, target: 1, status: "REJECTED", lifecycle_state: null, rejected_reasons: [], risk_reasons: [],
      warnings: [], labels: [], verdict: { action, why: [why] } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(env({ panel: "radar", data: {
      rows: [row("a", "ABB", "AVOID", "too late: price already ran 2.0x"), row("c", "TCS", "CHECK", "setup passed")],
      feature_window_min: 15,
      track_record: [{ day: "2026-11-09", trades: 121, wins: 29, net_inr: -83148, calls_net_inr: -12259, puts_net_inr: -70889 }] } })))));
    wrap(<Radar view={{ date: "2026-11-09", asOf: null }} onOpen={() => {}} />);
    expect(await screen.findByText("1 option idea to look at.")).not.toBeNull();
    expect(screen.getByText("too late: price already ran 2.0x")).not.toBeNull();
    expect(screen.getByText("TCS26NOV100CE")).not.toBeNull();
    expect(screen.getByText("−₹83,148")).not.toBeNull();
    const calls = screen.getAllByText(/^(BUY|CHECK|WAIT|AVOID)$/).map((e) => e.textContent);
    expect(calls).toEqual(["CHECK", "AVOID"]);                                   // best call first
    fireEvent.click(screen.getByLabelText(/show AVOID/));
    expect(screen.queryByText("ABB")).toBeNull();
  });
});

describe("panel age and staleness", () => {
  it("shows the data age on every panel and marks STALE visibly (label + hatch, not colour only)", () => {
    wrap(<>
      <Panel title="fresh" env={env({ status: "OK", age_s: 12 })}>ok</Panel>
      <Panel title="stale" env={env({ status: "STALE", age_s: 2580, reason: "newest observation 2580 s old > 120 s" })}>x</Panel>
    </>);
    const fresh = screen.getByRole("region", { name: "fresh" }), stale = screen.getByRole("region", { name: "stale" });
    expect(within(fresh).getByTestId("age").textContent).toBe("age 12 s");
    expect(fresh.getAttribute("data-status")).toBe("OK");
    expect(stale.getAttribute("data-status")).toBe("STALE");
    expect(within(stale).getByText("STALE")).toBeTruthy();
    expect(stale.className).toContain("fo-stale-hatch");
    expect(within(stale).getByTestId("age").textContent).toBe("age 43 min");
  });
  it("an UNAVAILABLE panel says why instead of showing numbers", () => {
    wrap(<Panel title="u" env={env({ status: "UNAVAILABLE", age_s: null, reason: "no signals.sqlite" })}>numbers</Panel>);
    expect(screen.getByText("— no signals.sqlite")).toBeTruthy();
    expect(screen.queryByText("numbers")).toBeNull();
  });
});

const perf = (ledger: string, net: number) => ({
  ledger, status: "OK", reason: null, now_ns: 1, config_version: "v12",
  data: { ledger, label: ledger, trades: 2, win_rate: 0.5, expectancy_inr: net / 2, profit_factor: 2, max_drawdown_inr: 10,
    net_inr: net, gross_inr: net + 40, charges_inr: 40, slippage_inr: 3, daily: [{ date: "2026-11-06", net_inr: net }],
    cumulative: [{ ts_ns: 1, cumulative_net_inr: net }], by: { regime: { UNAVAILABLE: "no regime classifier" } } } });

describe("SIMULATED and ACTUAL are never displayed in the same total", () => {
  it("performance: one ledger per tab, each fetched alone; no number is the sum of both", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string) => {
      calls.push(u);
      const led = u.includes("ACTUAL") ? "ACTUAL" : "SIMULATED";
      return new Response(JSON.stringify(perf(led, led === "ACTUAL" ? 250 : 111)), { status: 200 });
    }));
    wrap(<Performance />);
    const panel = await screen.findByRole("tabpanel");
    await within(panel).findAllByText(/₹111\.00/);
    expect(panel.getAttribute("data-ledger")).toBe("SIMULATED");
    expect(panel.textContent).not.toMatch(/250|361/);          // ACTUAL net 250; SIM + ACTUAL = 361
    await act(async () => { fireEvent.click(screen.getByRole("tab", { name: /ACTUAL/ })); });
    const p2 = await screen.findByRole("tabpanel");
    await within(p2).findAllByText(/₹250\.00/);
    expect(p2.getAttribute("data-ledger")).toBe("ACTUAL");
    expect(p2.textContent).not.toMatch(/111\.00|361/);
    expect(calls.every((u) => /ledger=(SIMULATED|ACTUAL)$/.test(u))).toBe(true);
    expect(document.body.textContent).not.toMatch(/361/);
  });
  it("active trades: separate, labelled tables per ledger and no combined total", async () => {
    const t = (id: string, ledger: string, net: number) => ({ id, underlying: id.toUpperCase(), kind: "FUT", side: "BUY", qty: 100, lots: 1,
      open_qty: 100, entry_price: 100010, entry_ns: 1_793_940_000_000_000_000, t1: 103000, underlying_stop: 99000, stop: 99000,
      decision: "HOLD", rule_id: "NO_EXIT_RULE", pnl_gross_inr: net, pnl_net_inr: net, warnings: [], thesis: "NOT_INVALIDATED", alerts: [],
      mark: { bid: 100100, ask: 100110, observed_ns: null }, mark_label: "", ledger });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(env({ panel: "trades",
      data: { SIMULATED: [t("sim", "SIMULATED", 111)], ACTUAL: [t("act", "ACTUAL", 222)] } })), { status: 200 })));
    wrap(<Trades view={{ date: "2026-11-06", asOf: 1 }} />);
    await screen.findByText("SIM");
    const sections = document.querySelectorAll("section[data-ledger]");
    expect([...sections].map((s) => s.getAttribute("data-ledger"))).toEqual(["SIMULATED", "ACTUAL"]);
    expect(sections[0].textContent).toContain("◇ SIMULATED");
    expect(sections[0].textContent).not.toContain("222");
    expect(sections[1].textContent).toContain("◆ ACTUAL");
    expect(sections[1].textContent).not.toContain("111.00");
    expect(document.body.textContent).not.toMatch(/333/);
  });
});

describe("panel D option chain (Phase 11)", () => {
  it("shows IV UNAVAILABLE with its reason, hypotheses as labelled chips, and the comparison's reason", async () => {
    const { OptionChain } = await import("../panels/OptionChain");
    const u = (r: string) => ({ UNAVAILABLE: r });
    const row = (kind: "CE" | "PE", iv: unknown, hyp: string) => ({ token: kind === "CE" ? 1 : 2, kind, strike: 100, oi: 5000,
      oi_change: 200, oi_change_pct: 4.17, volume_day: 9000, premium: 1050, premium_change_pct: -3.1, spread_pct: 12.5,
      depth_bid_qty: 300, depth_ask_qty: 400, iv, iv_change_pts: u("IV_UNAVAILABLE"), greeks: u("SPREAD_TOO_WIDE_FOR_IV"),
      hypothesis: hyp, evidence: ["IV: IV_UNAVAILABLE"] });
    const data = { underlying: "STK", underlyings: ["STK"], snapshot_ns: 1, options_config_version: "v14",
      expiries: [{ expiry: "2026-11-24", atm_strike: 100, underlying_price: 10000, underlying_change_pct: 0.1,
        rows: [row("CE", u("SPREAD_TOO_WIDE_FOR_IV: 12.5 % > 10.0 % (not computed from LTP)"), "UNCERTAIN"), row("PE", 0.21, "UNCERTAIN")],
        pcr_oi: 1, pcr_volume: u("CE: 1 of 1 strikes missing volume_day"), concentration: { CE: [100, 1], PE: [100, 1] },
        concentration_change: { CE: u("x"), PE: u("x") }, iv_coverage: [1, 2] }],
      selected: null, comparison: u("NO_SELECTED_OPTION: no recommendation"), labels: ["Hypotheses about the data, not facts"] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(env({ panel: "chain", data })))));
    wrap(<OptionChain view={{ date: "2026-11-09", asOf: 1 }} />);
    expect(await screen.findByLabelText("unavailable: SPREAD_TOO_WIDE_FOR_IV: 12.5 % > 10.0 % (not computed from LTP)")).toBeTruthy();
    expect(screen.getByText("21.0%")).toBeTruthy();                       // the PE IV the backend computed, formatted only
    expect(screen.getAllByText("UNCERTAIN").length).toBe(2);
    expect(screen.getByText("— NO_SELECTED_OPTION: no recommendation")).toBeTruthy();
    expect(screen.getByText("Hypotheses about the data, not facts")).toBeTruthy();
  });
});
