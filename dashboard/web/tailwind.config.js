/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        panel: "var(--bg-2)",
        raised: "var(--bg-3)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        line: "var(--line)",
        gold: "var(--gold)",
        "gold-dim": "var(--gold-dim)",
        cyan: "var(--cyan)",
        signalgreen: "var(--green)",
        signalred: "var(--red)",
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', "ui-sans-serif", "sans-serif"],
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
