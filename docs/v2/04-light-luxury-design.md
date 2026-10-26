# 04 — Light Luxury design (proposal)

## Reference research — honest status
| Reference | Status | What was done |
|---|---|---|
| kexsio.com/animations | **NOT VERIFIED** | Not fetched in Phase 0 (WebFetch not run; no screenshots). Intent only: card transitions, glass nav. |
| threeui.com/browse | **NOT VERIFIED** | Not fetched. Intent only: optional WebGL accents, never in tables/editor. |
| kitbitz.art | **NOT VERIFIED** | Not fetched; no component names claimed. |
All designs below are original and derived from the prompt's brief, not from those sites. Owner approval of Gate 0 may include "fetch the references now".

## Tokens (CSS custom properties; contrast computed with WCAG formula)
| Token | Value | Use | Contrast |
|---|---|---|---|
| `--bg` | `#F8FAFF` | page | — |
| `--surface` | `#FFFFFF` (glass: `rgba(255,255,255,.72)` + `backdrop-filter: blur(14px)`) | cards/nav | — |
| `--lavender-100/300` | `#EEEAFE` / `#C9C0FA` | soft fills, selection | decorative |
| `--ice-100/300` | `#E6F2FB` / `#BFDDF3` | secondary fills | decorative |
| `--ink` | `#1B2140` | body text | 15.0 on bg |
| `--ink-muted` | `#4A5173` | secondary text | 7.4 on bg |
| `--ink-subtle` | `#5E6687` | hints | 5.4 on bg |
| `--accent` | `#5B4BDB` | primary buttons/links | 5.8 on bg, white text on it 6.0 |
| `--info` | `#0B6FA8` | info | 5.5 on white |
| `--ok` / `--warn` / `--danger` | `#067647` / `#B54708` / `#B42318` | status (always with icon + text) | 5.7 / 5.4 / 6.6 on white |
| `--border` | `#E3E7F5` | hairlines | decorative |
| shadow | `0 1px 2px rgba(27,33,64,.06), 0 8px 24px rgba(91,75,219,.08)` | elevation | |
Rejected: `#6B7394` muted (4.46 — fails AA), `#8B7CF6` accent text (3.19). Light only; `color-scheme: light`; no dark theme in scope. Final re-validation by an automated contrast test at Gate 1.

Type: system UI stack + `ui-monospace` for SQL; scale 12/14/16/20/28; spacing 4-pt grid; radius 12 (cards) / 8 (inputs).

## Motion spec (proposals, values to approve)
- Page entry: opacity+translateY(8px) 220 ms `cubic-bezier(.2,.8,.2,1)`; list stagger ≤ 30 ms × 8.
- Hover/focus: 120 ms lift + border tint; visible 2 px focus ring `--accent` (never removed).
- Run status change: 240 ms colour cross-fade + icon swap; progress bar determinate with 300 ms ease.
- Pipeline edges: dashed stroke-dashoffset animation **only while node run state = running**, stops at completion.
- Optional ambient lavender/ice gradient drift on login/dashboard header only; none behind tables/editor/canvas content. No WebGL in Phase 0–4 (optional later, feature-flagged, with static fallback).
- `prefers-reduced-motion: reduce` → durations ≈ 0, no dash animation (static arrows + text status), no parallax.
- Perf budget: INP < 200 ms, 60 fps on 500-row virtualised table / 200-node canvas on a mid laptop (measured in Phase 4, not assumed).

## Screens and navigation
Shell: left glass sidebar (collapses to icons < 1024 px, bottom sheet menu < 640 px) + top bar (workspace switcher, user menu, run indicator).
1. **Login / Workspace picker** 2. **Dashboard** (recent runs, pending approvals, connection health) 3. **Infrastructure Settings** (tabs: SPICE REST · Flight SQL/ODBC · Redis · PostgreSQL · vLLM *(Coming in Phase 5, disabled)*) – secret fields write-only with "••• set / rotate" 4. **SPICE Connections** (list, status chips, capability flags with "Unsupported" shown explicitly) 5. **Catalog / Preview** (tree + column table + bounded sample, freshness badge) 6. **Dataset Wizard** (name → source objects → grain/keys → target → quality → review) 7. **Pipeline Studio** (tabs Visual | SQL; schema browser left, canvas/editor centre, inspector right, validation panel bottom; "Opaque SQL node" badge when not convertible) 8. **Review / Approval** (revision diff, checksum, validation evidence, approve/reject with comment) 9. **Jobs / Monitoring** (table + detail: attempts, events, safe logs, retry/cancel) 10. **Dataset Registry** (datasets, generations, lineage) 11. **AI Assistant** placeholder card: "Coming in Phase 5", no inputs.
Wireframes: to be drawn as low-fi HTML/SVG in Phase 1 for Gate-0 sign-off if requested (text-level layout above is the Phase 0 content).

## Accessibility
Semantic landmarks, labelled form controls, error text associated via `aria-describedby`, status never colour-only, keyboard-operable canvas (node focus, arrow-key move, Enter to edit, Delete with confirm) with a list-view alternative of the same graph, `aria-live=polite` for run updates, 44 px touch targets, tested with axe + manual keyboard/screen-reader pass in Phase 4.

## Security in UI
React escaping only; no `dangerouslySetInnerHTML`, no inline handlers; CSP `default-src 'self'`; no secrets in localStorage (only UI prefs).
