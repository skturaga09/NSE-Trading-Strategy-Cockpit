// Direct deterministic capture of every visible existing tab (APIs stubbed, clock frozen, JS animations paused).
// Usage: node fo-engine/tests/capture-tabs.mjs <baseURL> <outDir>   (env FO_CHROMIUM)
import { chromium } from "@playwright/test";
const [base, out] = process.argv.slice(2);
const TABS = ["Today", "Radar", "Swing", "Exits", "Journal", "Ideas", "Screener", "Commodities"];
const b = await chromium.launch({ executablePath: process.env.FO_CHROMIUM });
for (const tab of TABS) {
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await p.clock.install({ time: new Date("2026-11-06T11:00:00+05:30") });
  await p.route("**/*", (r) => { const u = new URL(r.request().url());
    if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") return r.abort();
    if (u.pathname.startsWith("/api/")) return r.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"stubbed for visual test"}' });
    return r.continue(); });
  await p.goto(base); await p.waitForLoadState("networkidle");
  await p.getByRole("button", { name: new RegExp(`^\\d+\\s*${tab}\\b`) }).click();
  await p.clock.runFor(5000); await p.waitForLoadState("networkidle");
  await p.clock.pauseAt(new Date(Date.parse("2026-11-06T11:01:00+05:30")));
  await p.screenshot({ path: `${out}/${tab}.png`, fullPage: true, animations: "disabled" });
  await p.close();
}
await b.close();
