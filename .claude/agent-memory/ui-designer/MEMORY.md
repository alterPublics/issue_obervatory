# UI Designer Agent Memory

## Brand Identity
- Palette reference: `/design/references/Farveflade@4x.png` -- gradient from deep purple (#4A1080) through green (#3D9B3A) to gold (#D4C020)
- Brand assets include binary data motifs (0s and 1s), QR-code pattern, and geometric "O" circles in purple/green/yellow/black
- Individual color samples: Asset 10 = purple O, Asset 6 = green O, Asset 8 = yellow O
- NOTE: design/references directory does not exist on the linux dev machine; palette ref images may only be on macOS workstation

## Current Frontend State (as of 2026-03-14)
- Tailwind via CDN only (no build pipeline, no tailwind.config.js file)
- Inline config in base.html with full brand palette: brand (purple), brand-green, brand-gold, surface colors
- Fonts loaded: Space Grotesk (headings), Inter (body), JetBrains Mono (data) via Google Fonts
- No dark mode support yet
- `input.css` has component classes (btn-primary, card, form-input, badges, table-th/td, alerts, etc.)
- `app.css` is a stub (HTMX indicator + Alpine x-cloak + tabular-nums + brand-gradient-bar)
- Nav sidebar is fully styled with dark theme and brand gradient accent bar

## Key Files
- Templates: `/src/issue_observatory/api/templates/`
- CSS: `/src/issue_observatory/api/static/css/input.css` (components), `app.css` (stub)
- Charts: `/src/issue_observatory/api/static/js/charts.js` (9 chart types, Chart.js 4)
- Network: `/src/issue_observatory/api/static/js/network_preview.js` (Sigma.js v3)
- App JS: `/src/issue_observatory/api/static/js/app.js` (HTMX handlers, Alpine components)
- Nav partial: `_partials/nav.html`
- Base template: `templates/base.html`

## Styled Components
- **networks/index.html** - Filter toolbar restyled (2026-03-14): grouped into Scope (purple tint), Source (green tint), Type (gold tint) sections with labeled borders; gradient Build button; brand-tinted stats bar with monospace numbers; improved empty/loading states

## Design Audit
- Full audit written: `/docs/research_reports/ui_design_audit_2026_03_03.md`
- Arena color assignment scheme: news=purple, social=purple-green, fringe=green-yellow, search=yellow

## Template Count
- ~50 HTML templates total across 12 directories
- Largest templates: query_designs/editor.html (~1200 lines), analysis/index.html (~1100 lines)

## Styling Architecture Decisions
- Dark mode as primary theme (planned, not yet implemented; class-based `.dark` on `<html>`)
- Sidebar stays dark in both themes (implemented)
- Fonts: Space Grotesk (headings), Inter (body), JetBrains Mono (code/IDs)
- Chart palette derived from brand gradient: [#7C3AED, #3D9B3A, #D4C020, #A855F7, #16A34A, #EAB308, #581C87, #65A30D]

## Design Patterns Established
- Filter toolbar grouping pattern: semantically related controls wrapped in tinted rounded panels with uppercase 10px tracking-widest section labels and internal separators
- Color-coding for filter groups: purple=scope/project, green=data source, gold=network type/mode
- Active filter state: section-colored badge count pill, tinted background, ring highlight with shadow-sm
- Build/action buttons: gradient `from-brand-600 via-brand-500 to-brand-green-600` with shadow-md
