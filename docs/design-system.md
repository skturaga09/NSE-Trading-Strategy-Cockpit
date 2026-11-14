# F&O Engine design system

Phase 10, 2026-11-07. This is the visual system of the F&O Engine tab: `dashboard/web/fo-engine/`.

- It is a separate design system from the rest of the dashboard, and it cannot affect the existing app.
- All of it lives inside the module, so it can be adopted app-wide later (§6).
- Owner decisions and assumptions are in [questions-ledger.md](questions-ledger.md), rows Q-10-*.

## 1. Principles

- **A dense, readable trading terminal.** Small type, tight spacing, tabular numerals for every number.
- **Colour is never the only signal.**
  - Bullish/bearish always carry ▲ / ▼ and a word.
  - STALE adds a hatch, a STALE label and the age.
  - SIMULATED is a dashed ◇ chip; ACTUAL is a solid ◆ chip.
  - UNAVAILABLE is a "—" whose tooltip gives the reason.
- **Every number is a backend field.**
  - The UI only formats (paise → ₹, ns → IST clock). It never computes a trading value and never shows a placeholder number.
  - The Option chain area is deliberately empty until Phase 11.
- **Honest language.** "Positioning hypothesis", never "institutions are buying".

## 2. Tokens: `fo-design-tokens.ts` (single source)

| Group | Tokens |
|---|---|
| Colour (light / dark) | `bg` `surface` `raised` `line` `ink` `muted` `accent` |
| Semantic colour | `bullish` `bearish` `neutral` `stale` `unavailable` `simulated` `actual` `warning` |
| Font | `sans` = Inter (UI), `mono` = JetBrains Mono (all numbers, tabular, slashed zero) |
| Type scale (px / line-height) | `2xs` 10/14 · `xs` 11/16 · `sm` 12/18 · `base` 13/20 · `lg` 15/22 · `xl` 18/26 |
| Space | `0` 0 · `1` 2 · `2` 4 · `3` 6 · `4` 8 · `5` 12 · `6` 16 · `7` 24 · `8` 32 (px) |
| Radius | `none` 0 · `sm` 2 · `md` 4 · `lg` 6 |
| Shadow | `panel`, `pop` |
| Size | `tooltip` 360 · `control` 28 · `scroll` 320 · `chart` 360 · `chartSmall` 160 |
| Motion | `fast` 90 ms · `base` 160 ms · `ease` |

Palette:
- **Dark:** graphite `#0a0e13` with a periwinkle accent `#8fa8ff`. Bullish `#3ddc97`, bearish `#ff6b8b`, stale amber `#e8b04a`, simulated violet `#b39dff`, actual cyan `#5fd4e8`.
- **Light:** `#f3f6fa` paper with accent `#3a5bd9`. Bullish `#0b7d4f`, bearish `#c0274a`, and darker semantic tones for contrast.
- **Contrast with the app:** the existing app is warm black `#0b0a08` with gold `#f4b942` and cyan, in SF / IBM Plex.

How the tokens are used:
- `fo-tokens.css` turns the tokens into CSS variables (`--fo-*`), scoped to `[data-fo-engine]`. Light is the default; `[data-fo-engine][data-fo-theme="dark"]` holds dark.
- `fo-engine/tests/isolation.test.ts` fails if any value in the CSS differs from the token file.
- `tailwind.fo.config.js` maps the Tailwind theme only to these variables, so components use tokens and never raw values. The isolation test also rejects any unprefixed class.

## 3. Isolation mechanics

| Rule | How |
|---|---|
| D1: no edits to global CSS, Tailwind config, theme, fonts or shared components | Edits to existing files: one lazy import + route in `src/App.tsx`, one nav row in `src/components/TabNav.tsx`. Test: `git diff` on the global files is empty |
| D2: one root, no global selectors | Everything renders inside `<div data-fo-engine>`. Every top-level CSS selector starts with `[data-fo-engine]` (test), except `@font-face`, which declares the font and applies it nowhere |
| D3: separate Tailwind config | `@config "./tailwind.fo.config.js"` in `fo-engine.css`. Settings: `prefix: "fo-"`, `important: "[data-fo-engine]"`, `corePlugins.preflight: false`, and content limited to `fo-engine/**`. The app's config does not scan this folder, so **the app's compiled CSS is byte-identical** (sha256 `25dad898…` before and after) |
| D4: portals inside the root | `FoRoot` renders `<div data-fo-portal>` inside the root, and `Tip` portals there. Chart overlays (lightweight-charts) are canvas inside their container (test: the tooltip's ancestors include `[data-fo-engine]`) |
| D5: module-only fonts | `@fontsource/inter` and `@fontsource/jetbrains-mono` are imported only by `FoEngineTab.tsx`, inside the lazy chunk, and applied only under the root. They are served from the bundle, with no external font request. The app's `body` font is unchanged |
| Theme | `FoRoot` observes the app's `html[data-theme]` (read-only) and mirrors it into `data-fo-theme` |

Root padding is set in CSS on `[data-fo-engine]` itself. Scoped utilities (`[data-fo-engine] .fo-*`) match only descendants, so they can't style the root.

## 4. Components (`core.tsx`)

| Component | Contract |
|---|---|
| `FoRoot` | Scope root, theme mirror, portal container |
| `V` | One backend value. A number or string is formatted in mono tabular. `{UNAVAILABLE: reason}` (or null) renders "—" with an accessible label and a tooltip carrying the reason |
| `Panel` | Frame for every panel. The header shows `AgeTag`: status chip (OK / STALE / UNAVAILABLE), age, REPLAY chip, and a tooltip with source plus observation, receive and processing times, the view time and the config version. A STALE panel gets the stale border and hatch. An UNAVAILABLE panel with no data shows its reason instead of content. `data-status` mirrors the status |
| `Tip` | Tooltip in the scoped portal; works on hover and keyboard focus (`aria-describedby`) |
| `Chip`, `Dir`, `LedgerBadge` | Status chip; ▲/▼ direction; SIMULATED (dashed ◇) / ACTUAL (solid ◆) |
| formatters | `inr` (paise → ₹), `rupees`, `pct`, `num`, `ist`, `istFull`, `fmtAge` — display only |

Panels (`panels/`):
- Overview (A)
- Radar (B)
- Positioning (C)
- OptionChain (D, empty by design)
- SignalDetail (E)
- Trades (F)
- Performance (G)
- Journal (H)
- Health

## 5. Data contract the components rely on

Every GET returns an envelope from `engine/dashboard.py`:
- `status`, `reason`, `age_s` and `stale_after_s` (config v12 `dashboard.stale_after_s`)
- `mode` (LIVE / REPLAY) and `now_ns`
- `provenance` (`source`, `observed_ns`, `received_ns`, `processed_ns`, tz)
- `config_version` and `data`

An observation later than the view time is look-ahead: the envelope turns UNAVAILABLE and withholds the data. Values follow the engine's `jsonable` convention: a plain value or `{"UNAVAILABLE": reason}`.

## 6. Adopting this design app-wide later (step by step)

1. **Move the tokens.** Move `fo-design-tokens.ts` and `fo-tokens.css` to `src/design/`. Change the CSS scope from `[data-fo-engine]` to the app root. The token test moves with them.
2. **Switch the Tailwind config.** Make `tailwind.fo.config.js` the app's config.
   - Either keep `prefix: "fo-"` (no class collisions while both systems coexist), or drop it in a separate codemod once every tab is migrated.
   - Keep `preflight: false` until the old tabs are migrated, so the old tabs keep their look during the switch.
3. **Load the fonts once.** Import the `@fontsource` CSS in `main.tsx` instead of `FoEngineTab.tsx`, and apply `--fo-font-sans` / `--fo-font-mono` at the app root.
4. **Lift the shared components.** Move `core.tsx` (`V`, `Panel`, `Tip`, `Chip`, `LedgerBadge`) to `src/components/fo/`. Hoist the portal container to the app root, and give `Tip` that portal.
5. **Migrate one tab at a time.** Wrap the tab in the new root and replace its classes with `fo-*` tokens. Re-run `fo-engine/tests/existing-tabs.spec.ts`; the screenshots of the other tabs must stay identical. Re-baseline with `--update-snapshots` only for the tab just migrated.
6. **Replace the global theme last.** Once no tab uses the old classes, replace `src/index.css` `:root` variables and the `body` background with the token file. Remove the old `tailwind.config.js` colours. Then `important: "[data-fo-engine]"` and the prefix can go.
7. **Keep the guards.** The isolation and token tests run at app level after the move: no raw values, no unprefixed classes during the migration, and tokens equal to CSS.
