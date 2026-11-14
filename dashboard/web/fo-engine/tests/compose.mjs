import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
const [out, a, b, la, lb] = process.argv.slice(2);
const img = (p) => "data:image/png;base64," + readFileSync(p).toString("base64");
const browser = await chromium.launch({ executablePath: process.env.FO_CHROMIUM });
const page = await browser.newPage({ viewport: { width: 2000, height: 760 } });
await page.setContent(`<body style="margin:0;background:#222;font:14px system-ui;color:#eee;display:flex;gap:16px;padding:12px">
 ${[[a, la], [b, lb]].map(([p, l]) => `<figure style="margin:0;flex:1"><figcaption style="padding:4px 0">${l}</figcaption>
 <div style="height:690px;overflow:hidden;border:1px solid #555"><img src="${img(p)}" style="width:100%"></div></figure>`).join("")}</body>`);
await page.screenshot({ path: out });
await browser.close();
