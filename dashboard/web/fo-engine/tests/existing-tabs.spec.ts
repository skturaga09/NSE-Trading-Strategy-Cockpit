// Before/after pixel comparison of every visible existing tab. Run once on the pre-Phase-10 build with
// --update-snapshots (baseline), then on the Phase 10 build. The nav strip gains one entry ("F&O Engine"), so each tab
// is compared twice: with the nav strip masked (must be identical) and as the full page (difference expected in the nav only).
import { expect, test, type Page } from "@playwright/test";

const TABS = ["Today", "Radar", "Swing", "Exits", "Journal", "Ideas", "Screener", "Commodities"];
const FIXED = new Date("2026-11-06T11:00:00+05:30");

async function open(page: Page) {
  await page.clock.install({ time: FIXED });
  await page.route("**/*", (r) => {
    const u = new URL(r.request().url());
    if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") return r.abort();
    if (u.pathname.startsWith("/api/"))
      return r.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"stubbed for visual test"}' });
    return r.continue();
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
}

for (const tab of TABS) {
  test(`existing tab ${tab}`, async ({ page }) => {
    await open(page);
    await page.getByRole("button", { name: new RegExp(`^\\d+\\s*${tab}\\b`) }).click();
    await page.clock.runFor(5000);                                     // lets react-query retries settle
    await page.waitForLoadState("networkidle");
    await page.clock.pauseAt(new Date(FIXED.getTime() + 60_000));   // freezes JS-driven (motion) animations too
    const nav = page.locator("main > div").first();
    await expect(page).toHaveScreenshot(`${tab}-nav-masked.png`, { fullPage: true, mask: [nav] });
    if (process.env.FO_FULL === "1") await expect(page).toHaveScreenshot(`${tab}-full.png`, { fullPage: true });
  });
}
