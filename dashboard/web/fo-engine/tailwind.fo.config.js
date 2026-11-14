// Tailwind config for the F&O Engine module ONLY (loaded by fo-engine.css through @config). The app's own
// tailwind.config.js is untouched and does not scan this directory, so the app's CSS output is unchanged.
// - prefix "fo-": every utility is .fo-*, so no class can collide with the app's classes
// - important "[data-fo-engine]": every rule is scoped under the module root
// - preflight off: no reset leaks into the app
const v = (n) => `var(--fo-${n})`;
const names = ["bg", "surface", "raised", "line", "ink", "muted", "accent", "bullish", "bearish", "neutral", "stale",
  "unavailable", "simulated", "actual", "warning"];

/** @type {import('tailwindcss').Config} */
export default {
  prefix: "fo-",
  important: "[data-fo-engine]",
  corePlugins: { preflight: false },
  content: ["./fo-engine/**/*.{ts,tsx}", "!./fo-engine/tests/**"],
  theme: {
    colors: { transparent: "transparent", current: "currentColor", ...Object.fromEntries(names.map((n) => [n, v(n)])) },
    fontFamily: { sans: v("font-sans"), mono: v("font-mono") },
    fontSize: Object.fromEntries(["2xs", "xs", "sm", "base", "lg", "xl"].map((k) => [k, [v(`text-${k}`), v(`leading-${k}`)]])),
    spacing: Object.fromEntries(["0", "1", "2", "3", "4", "5", "6", "7", "8"].map((k) => [k, v(`space-${k}`)])),
    borderRadius: Object.fromEntries(["none", "sm", "md", "lg"].map((k) => [k, v(`radius-${k}`)])),
    boxShadow: { panel: v("shadow-panel"), pop: v("shadow-pop"), none: "none" },
    maxWidth: { tip: v("size-tooltip") },
    height: { control: v("size-control"), chart: v("size-chart"), "chart-sm": v("size-chartSmall") },
    maxHeight: { scroll: v("size-scroll") },
    extend: {},
  },
  plugins: [],
};
