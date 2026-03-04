# UI Designer Agent Memory

## Brand Identity
- Palette reference: `/design/references/Farveflade@4x.png` -- gradient from deep purple (#4A1080) through green (#3D9B3A) to gold (#D4C020)
- Brand assets include binary data motifs (0s and 1s), QR-code pattern, and geometric "O" circles in purple/green/yellow/black
- Individual color samples: Asset 10 = purple O, Asset 6 = green O, Asset 8 = yellow O

## Current Frontend State (as of 2026-03-03)
- NO brand colors applied yet; entire UI uses Tailwind default blue-600
- Tailwind via CDN only (no build pipeline, no tailwind.config.js file)
- Inline config in base.html: only `brand: { 50, 600, 700 }` mapped to blue
- No custom fonts loaded (system-ui only)
- No dark mode support
- No CSS custom properties / design tokens
- `input.css` has 92 lines of component classes (btn-primary, card, form-input, badges, etc.)
- `app.css` is a 25-line stub (HTMX indicator + Alpine x-cloak only)

## Key Files
- Templates: `/src/issue_observatory/api/templates/`
- CSS: `/src/issue_observatory/api/static/css/input.css` (components), `app.css` (stub)
- Charts: `/src/issue_observatory/api/static/js/charts.js` (9 chart types, Chart.js 4)
- Network: `/src/issue_observatory/api/static/js/network_preview.js` (Sigma.js v3)
- App JS: `/src/issue_observatory/api/static/js/app.js` (HTMX handlers, Alpine components)
- Nav partial: `_partials/nav.html`
- Base template: `templates/base.html`
- Auth base: `templates/base_auth.html`

## Design Audit
- Full audit written: `/docs/research_reports/ui_design_audit_2026_03_03.md`
- 5-tier prioritized recommendation plan (Foundation -> Core Pages -> Component Polish -> Dark Mode -> Polish)
- Proposed Tailwind config with full color system, fonts, tokens
- Proposed CSS custom properties in globals.css
- Arena color assignment scheme: news=purple, social=purple-green, fringe=green-yellow, search=yellow

## Template Count
- ~50 HTML templates total across 12 directories
- Largest templates: query_designs/editor.html (~1200 lines), analysis/index.html (~1100 lines), content/browser.html (~600 lines), actors/list.html (~500 lines)
- All pages use consistent max-w + space-y-6 layout pattern

## Styling Architecture Decisions (proposed, not yet implemented)
- Dark mode as primary theme (class-based: `.dark` on `<html>`)
- Sidebar stays dark in both themes
- Fonts: Space Grotesk (headings), Inter (body), JetBrains Mono (code/IDs)
- Chart palette derived from brand gradient: [#7C3AED, #3D9B3A, #D4C020, #A855F7, #16A34A, #EAB308, #581C87, #65A30D]
