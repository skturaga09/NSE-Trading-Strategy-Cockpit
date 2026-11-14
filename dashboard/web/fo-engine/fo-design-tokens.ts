// F&O Engine design tokens — the single source of the module's visual system (docs/design-system.md).
// Components use these through CSS variables (fo-tokens.css, scoped to [data-fo-engine]) or the fo- Tailwind theme
// (tailwind.fo.config.js); never raw values. fo-tokens.test.ts checks the CSS file matches this file exactly.

export const color = {
  dark: {
    bg: "#0a0e13",          // graphite
    surface: "#10161e",     // panel
    raised: "#161e28",      // table header, inputs
    line: "#223040",
    ink: "#e4ebf2",
    muted: "#8496a8",
    accent: "#8fa8ff",      // periwinkle: focus, selection, links
    bullish: "#3ddc97",
    bearish: "#ff6b8b",
    neutral: "#a7b4c2",
    stale: "#e8b04a",
    unavailable: "#5d6e80",
    simulated: "#b39dff",
    actual: "#5fd4e8",
    warning: "#ffb347",
  },
  light: {
    bg: "#f3f6fa",
    surface: "#ffffff",
    raised: "#eaf0f6",
    line: "#cfd9e3",
    ink: "#0d1722",
    muted: "#506274",
    accent: "#3a5bd9",
    bullish: "#0b7d4f",
    bearish: "#c0274a",
    neutral: "#4f5f70",
    stale: "#8a5a00",
    unavailable: "#7a8896",
    simulated: "#6a4fd1",
    actual: "#0a7287",
    warning: "#a35a00",
  },
} as const;

export const font = {
  sans: '"Inter", ui-sans-serif, system-ui, sans-serif',
  mono: '"JetBrains Mono", ui-monospace, monospace',
} as const;

export const typeScale = {        // px / line-height
  "2xs": ["10px", "14px"],
  xs: ["11px", "16px"],
  sm: ["12px", "18px"],
  base: ["13px", "20px"],
  lg: ["15px", "22px"],
  xl: ["18px", "26px"],
} as const;

export const space = { "0": "0px", "1": "2px", "2": "4px", "3": "6px", "4": "8px", "5": "12px", "6": "16px", "7": "24px", "8": "32px" } as const;
export const radius = { none: "0px", sm: "2px", md: "4px", lg: "6px" } as const;
export const shadow = { panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 24px -16px rgba(0,0,0,0.6)", pop: "0 8px 28px -8px rgba(0,0,0,0.55)" } as const;
export const size = { tooltip: "360px", control: "28px", scroll: "320px", chart: "360px", chartSmall: "160px" } as const;
export const motion = { fast: "90ms", base: "160ms", ease: "cubic-bezier(.2,.7,.2,1)" } as const;

export type ColorName = keyof typeof color.dark;
