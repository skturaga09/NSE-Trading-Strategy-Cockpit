// Design isolation (D1–D6) as grep tests: scoped CSS, prefixed classes, untouched global style files, module-only fonts,
// tokens CSS == token file.
// @vitest-environment node
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import * as T from "../fo-design-tokens";

const MOD = join(__dirname, ".."), WEB = join(MOD, "..");
const files = (dir: string, ext: RegExp): string[] => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? (f === "tests" ? [] : files(p, ext)) : ext.test(f) ? [p] : [];
});

function topLevelSelectors(css: string): string[] {
  css = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const out: string[] = [];
  let depth = 0, buf = "";
  for (const ch of css) {
    if (ch === "{") { if (depth === 0) out.push(buf.trim()); depth++; buf = ""; }
    else if (ch === "}") { depth--; buf = ""; }
    else if (ch === ";" && depth === 0) buf = "";       // @import / @config / @tailwind statements
    else if (depth === 0) buf += ch;
  }
  return out;
}

describe("CSS is scoped to the module root", () => {
  for (const f of files(MOD, /\.css$/)) {
    it(f.slice(MOD.length + 1), () => {
      for (const sel of topLevelSelectors(readFileSync(f, "utf8"))) {
        for (const part of sel.split(",")) expect(part.trim(), `unscoped selector in ${f}: ${sel}`).toMatch(/^\[data-fo-engine\]/);
      }
    });
  }
  it("tailwind module config: prefix, scoped important, preflight off, own content only", async () => {
    const cfg = (await import("../tailwind.fo.config.js")).default as unknown as
      { prefix: string; important: string; corePlugins: { preflight: boolean }; content: string[] };
    expect(cfg.prefix).toBe("fo-");
    expect(cfg.important).toBe("[data-fo-engine]");
    expect(cfg.corePlugins.preflight).toBe(false);
    expect(cfg.content.every((c: string) => c.includes("fo-engine"))).toBe(true);
  });
});

describe("every class in the module is fo- prefixed", () => {
  const ok = /^([a-z0-9-]+:)*fo-[^\s]+$/;
  for (const f of files(MOD, /\.tsx$/)) {
    it(f.slice(MOD.length + 1), () => {
      const src = readFileSync(f, "utf8");
      const lists = [...src.matchAll(/className="([^"]*)"/g)].map((m) => m[1])
        .concat([...src.matchAll(/["`]([^"`$]*\bfo-[^"`$]*)["`]/g)].map((m) => m[1]).filter((x) => !/[/.[\]]/.test(x)));
      for (const list of lists) for (const tok of list.split(/\s+/).filter(Boolean)) expect(tok, `${f}: "${list}"`).toMatch(ok);
    });
  }
});

describe("the app's global styling is untouched", () => {
  it("no diff in global style / theme / font files", () => {
    const out = execFileSync("git", ["diff", "--name-only", "HEAD", "--", "src/index.css", "tailwind.config.js", "postcss.config.js",
      "index.html", "src/main.tsx", "src/components/Header.tsx"], { cwd: WEB }).toString().trim();
    expect(out).toBe("");
  });
  it("existing-file edits are limited to the route and nav entry", () => {
    const out = execFileSync("git", ["diff", "--name-only", "HEAD", "--", "src"], { cwd: WEB }).toString().trim().split("\n").filter(Boolean);
    // + Phase 15 owner-requested plumbing fixes (lot size from the instrument master, not a hardcoded 75)
    expect(out.sort()).toEqual(["dashboard/web/src/App.tsx", "dashboard/web/src/components/SystemCheck.tsx",
      "dashboard/web/src/components/TabNav.tsx", "dashboard/web/src/tabs/FnoPlanner.tsx"]);
  });
  it("fonts load only in the module chunk", () => {
    const src = files(join(WEB, "src"), /\.(tsx?|css)$/).map((f) => readFileSync(f, "utf8")).join("\n");
    expect(src).not.toMatch(/fontsource|"Inter"|JetBrains Mono/);
    expect(readFileSync(join(MOD, "FoEngineTab.tsx"), "utf8")).toMatch(/@fontsource\/inter/);
  });
});

describe("tokens: fo-tokens.css mirrors fo-design-tokens.ts", () => {
  const css = readFileSync(join(MOD, "fo-tokens.css"), "utf8");
  const block = (sel: RegExp) => Object.fromEntries([...(css.match(sel)![1].matchAll(/--fo-([\w-]+):\s*([^;]+);/g))].map((m) => [m[1], m[2].trim()]));
  const light = block(/\[data-fo-engine\] \{([\s\S]*?)\}/), dark = block(/\[data-fo-theme="dark"\] \{([\s\S]*?)\}/);
  it("colours (light and dark)", () => {
    for (const [k, v] of Object.entries(T.color.light)) expect(light[k], k).toBe(v);
    for (const [k, v] of Object.entries(T.color.dark)) expect(dark[k], k).toBe(v);
  });
  it("type, space, radius, size, motion", () => {
    for (const [k, [s, l]] of Object.entries(T.typeScale)) { expect(light[`text-${k}`]).toBe(s); expect(light[`leading-${k}`]).toBe(l); }
    for (const [k, v] of Object.entries(T.space)) expect(light[`space-${k}`]).toBe(v);
    for (const [k, v] of Object.entries(T.radius)) expect(light[`radius-${k}`]).toBe(v);
    for (const [k, v] of Object.entries(T.size)) expect(light[`size-${k}`]).toBe(v);
    for (const [k, v] of Object.entries(T.motion)) expect(light[`motion-${k}`]).toBe(v);
    expect(light["font-mono"]).toBe(T.font.mono);
  });
  it("semantic tokens exist in both themes", () => {
    for (const k of ["bullish", "bearish", "neutral", "stale", "unavailable", "simulated", "actual", "warning"])
      expect(light[k] && dark[k], k).toBeTruthy();
  });
});
