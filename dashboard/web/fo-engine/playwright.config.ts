// Visual regression of the EXISTING app tabs (Phase 10 acceptance). Serves a scratch build with `vite preview`;
// every /api call is stubbed and the clock frozen, so the only input that can change pixels is the code.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: /.*\.spec\.ts/,
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  use: {
    baseURL: process.env.FO_BASE_URL ?? "http://127.0.0.1:4180",
    viewport: { width: 1440, height: 900 },
    launchOptions: { executablePath: process.env.FO_CHROMIUM },
  },
  expect: { toHaveScreenshot: { maxDiffPixels: 0, animations: "disabled", caret: "hide" } },
  workers: 1,
  retries: 2,   // timing races (query retries vs the fake clock) pass on retry; a real pixel change fails every attempt
});
