// Screenshots of the F&O Engine panels against the replayed session (report evidence; not a test).
// Usage: node fo-engine/tests/shoot.mjs <outDir> <section>[:<action>] ...   (env FO_CHROMIUM, FO_BASE_URL, FO_API)
import { chromium } from "@playwright/test";
const [out, ...jobs] = process.argv.slice(2);
const base = process.env.FO_BASE_URL ?? "http://127.0.0.1:4181", api = process.env.FO_API ?? "http://127.0.0.1:8091";
const browser = await chromium.launch({ executablePath: process.env.FO_CHROMIUM });
for (const theme of (process.env.FO_THEMES ?? "dark").split(",")) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  await page.addInitScript((t) => { try { localStorage.setItem("theme", t); } catch {} }, theme);
  await page.route("**/api/**", (r) => {
    const u = new URL(r.request().url());
    if (u.pathname.startsWith("/api/engine/")) return r.continue({ url: api + u.pathname + u.search });
    return r.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"not part of this screenshot"}' });
  });
  for (const job of jobs) {
    const [what, action] = job.split(":");
    await page.goto(base + "/");
    await page.getByRole("button", { name: /09\s*F&O Engine/ }).click();
    await page.waitForSelector("[data-fo-engine]");
    if (what === "existing") {
      await page.getByRole("button", { name: new RegExp(`^\\d+\\s*${action}\\b`) }).click();
    } else {
      const nav = page.getByRole("navigation", { name: "engine sections" });
      await nav.getByRole("button", { name: action?.startsWith("open") ? "Radar" : what, exact: true }).click();
      if (action === "rejected") await page.getByLabel(/show rejected/).check();
      if (action === "raw") await page.getByRole("button", { name: "raw" }).click();
      if (action?.startsWith("open")) { await page.getByLabel(/show rejected/).check(); await page.locator("tbody tr").first().click(); }
      if (action === "actual") await page.getByRole("tab", { name: /ACTUAL/ }).click();
    }
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);
    const file = `${out}/${theme}-${what.replace(/\s+/g, "-").toLowerCase()}${action ? "-" + action : ""}.png`;
    await page.screenshot({ path: file, fullPage: true, animations: "disabled" });
    console.log("wrote", file);
  }
  await page.close();
}
await browser.close();
