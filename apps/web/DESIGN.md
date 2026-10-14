# Design System: Business X-Ray Console

Single source of truth for every screen in `apps/web`. Product console
(ops cockpit), not a marketing page — landing-page patterns are banned here.

## 1. Visual Theme & Atmosphere

A calm, minimal, paper-light operating console. Warm-stone neutrals, generous
whitespace, hairline borders instead of shadows. One deep-pine accent that
only ever means "graph truth / go". Motion is near-invisible — fast ease-out
transitions and short staggered entrances, never choreography.
Dials: Variance 5, Motion 3, Density 6. One locked light theme, no mode flip
mid-page.

## 2. Color Palette & Roles

- **Paper Canvas** (#FAFAF9) — app background. Never pure white page + white cards without borders.
- **Pure Surface** (#FFFFFF) — cards, panels, table surfaces.
- **Well Fill** (#F5F5F4) — wells, inspector rows, formula chips.
- **Hairline** (#E7E5E4) — 1px structural borders.
- **Ink** (#1C1917) — primary text. Secondary #57534E, muted #A8A29E.
- **Deep Pine** (#047857, hover #065F46, tint #ECFDF5) — THE single accent.
  CTAs (white text, ≈4.9:1), focus rings, active nav (reversed: stone-900 fill),
  approved formulas, hot graph edges.
- **Amber Risk** (#D97706) — semantic only: suppliers, secondary impact.
- **Red Fault** (#DC2626) — semantic only: direct impact, errors.
- Banned: purple/blue neon, gradients on text, outer glows, warm/cool gray mixing.

## 3. Typography Rules

- **Display:** Space Grotesk 500–700, tracking-tight, `text-wrap: balance`. Page
  titles 44px/1.05; panel titles `text-xl` / `text-[15px]`.
- **Body:** Inter 400–600, relaxed leading, 65ch max width, stone-500 secondary.
- **Mono:** JetBrains Mono for ALL numbers, formulas (`Type.property`),
  timestamps, deltas. Always `tnum` (tabular-nums).
- **Banned:** Inter as display face, any serif in the console, meta-label
  eyebrows (max 1 small-caps label per page — the hero only).

## 4. Component Stylings

- **Buttons:** solid pine-700 + white text (≈4.9:1), stone ghost with hairline.
  Specific-property transitions only, custom `--ease-out`; press = `scale(0.98)`.
  Labels 1–3 words, one line, one intent per page. AA contrast audited.
- **Cards:** `rounded-2xl`, stone-200 hairline, white fill, near-flat. Hover =
  pine-tinted border + soft pine shadow + `-translate-y-px` under
  `@media (hover:hover)`. Dense metrics use border/divide strips, not boxes.
- **Inputs:** label above, error below, hairline border on white/paper fill,
  pine focus ring. No placeholder-as-label.
- **Loaders:** skeleton blocks matching layout shape. No spinners.
- **Empty states:** composed dashed-panel with the exact next action.
- **Graph nodes:** white rects on a dot grid, zinc type dots (amber = supplier,
  pine = production), mono property line, staggered enter (≤60ms steps).

## 5. Layout Principles

Grid-first, `max-w-[1440px]` containment, asymmetric splits over equal
columns (upload 3fr + stack 2fr — never 3 equal cards). Workspace is a
3-column console (240px explorer / fluid canvas / 360px copilot) collapsing
to single column under 1024px. Full-height canvas uses `min-h-[60dvh]`,
never `h-screen`.

## 6. Motion & Interaction

Custom `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)` everywhere; UI stays
under 300ms; entrances `translateY(8px) + opacity` with ≤190ms cascades;
press feedback on every clickable. Transform/opacity only. All motion gated
behind `prefers-reduced-motion`. No scroll listeners, no GSAP on this
surface — motion must signal state, never decorate.

## 7. Anti-Patterns (Banned)

No emojis. No Inter display. No pure black. No neon/outer glow. No gradient
text. No custom cursors. No 3-equal-card rows. No centered marketing hero.
No "SECTION 01" meta-labels. No AI clichés (Elevate, Seamless, Unleash,
Next-Gen, Delve). No generic names in demo copy. No fake-precise invented
numbers. No silently-applied AI edits — every proposal carries
Apply/Edit/Reject.
