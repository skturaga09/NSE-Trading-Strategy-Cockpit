// Component and isolation tests of the F&O Engine module only: npx vitest run -c fo-engine/vitest.config.ts
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: fileURLToPath(new URL("..", import.meta.url)),
  plugins: [react()],
  test: { environment: "jsdom", include: ["fo-engine/tests/**/*.test.{ts,tsx}"], css: false },
});
