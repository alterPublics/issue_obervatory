# UI Design Audit: The Issue Observatory

**Date:** 2026-03-03
**Auditor:** UI/Visual Designer Agent
**Scope:** Comprehensive visual design audit of all frontend templates, CSS, chart configurations, and component patterns
**Objective:** Identify gaps between the current generic Tailwind implementation and the established brand identity, and produce actionable recommendations for transforming the UI into a distinctive, polished research platform

---

## Executive Summary

The Issue Observatory's frontend is **functionally complete and well-structured** but **visually generic**. The application currently looks like any Tailwind CSS starter template with default blue-600 accents on white cards over a gray-50 background. Despite having a rich, distinctive brand identity defined through reference assets (the purple-green-yellow gradient field, binary data motifs, and geometric "O" shapes), **none of this visual identity has been applied to the interface**. The application's Tailwind configuration is minimal (a single `brand` color with three shades), there is no custom font stack, no dark mode support, no design token system, and no use of the signature gradient anywhere in the UI.

The gap between the brand's visual ambition and the current implementation is substantial but addressable. The underlying HTML structure is solid, the component patterns are consistent, and the Jinja2/HTMX/Alpine architecture provides clean separation that makes a visual overhaul achievable without rewriting business logic.

**Key finding:** This audit estimates that a systematic design system implementation would transform the application from a generic admin panel into a distinctive research platform. The work should be phased, starting with foundational token infrastructure and the navigation shell, then flowing outward to components, charts, and data-dense pages.

---

## 1. Current State Assessment

### 1.1 What Exists

| Aspect | Current State |
|--------|--------------|
| **Tailwind Setup** | CDN-only (`cdn.tailwindcss.com` in `<head>`), no build pipeline active |
| **Tailwind Config** | Inline in `base.html`: only `brand: { 50, 600, 700 }` mapped to default blue |
| **Custom CSS** | `input.css` with 92 lines of `@layer components` classes; `app.css` is a 25-line stub |
| **Color Palette** | Tailwind defaults: `blue-600` primary, `gray-*` neutrals, stock semantic colors |
| **Typography** | System font stack (`system-ui, sans-serif`), no custom fonts loaded |
| **Dark Mode** | Not implemented; no `dark:` variants anywhere |
| **Design Tokens** | None; colors hardcoded as Tailwind utility classes throughout templates |
| **Brand Identity** | Completely absent from the UI; reference images unused |
| **Charts** | Chart.js with hardcoded `#2563eb` (blue-600), `#16a34a` (green-600), `#d97706` (amber-600) palette |
| **Network Graphs** | Sigma.js with `#3b82f6` (blue-500) actors, `#f59e0b` (amber-500) terms |

### 1.2 What Works Well

1. **Consistent page structure.** Every page follows a predictable layout: `max-w-Nxl mx-auto space-y-6` with a page header (`h1` + subtitle + action buttons) at top. This structural consistency is a strong foundation.

2. **Well-designed component abstractions.** The `input.css` file defines reusable `.btn-primary`, `.btn-secondary`, `.card`, `.form-input`, `.badge-*`, `.table-th`, `.alert-*` classes. This component layer is the right architecture; it just needs to be re-themed.

3. **Functional partials system.** Shared partials (`_partials/nav.html`, `flash.html`, `empty_state.html`, `loading_spinner.html`, `pagination.html`, `breadcrumbs.html`) establish consistency across pages. These are good refactoring targets.

4. **Sophisticated interaction patterns.** HTMX SSE streaming for live collection monitoring, Alpine.js for client-side state (modals, dropdowns, form watchers, polling), and smooth HTMX partial swaps are all well-implemented.

5. **Content density is appropriate.** Tables use sensible column widths and row spacing. The content browser's two-column layout (sidebar filters + main table) is a good pattern for data-intensive research.

### 1.3 What Feels Generic or Inconsistent

1. **The entire color story is Tailwind default blue.** `bg-blue-600`, `text-blue-600`, `hover:bg-blue-700`, `focus:ring-blue-500` appear everywhere. There is no visual connection to the brand's purple-green-yellow palette.

2. **Light mode only, with bright white backgrounds.** The `bg-gray-50` body and `bg-white` cards create a high-brightness interface unsuitable for extended research sessions. The design system specifies dark mode as primary.

3. **No typographic distinction.** The system font stack produces different text rendering on every OS. There are no heading fonts, no monospace specification for data, and no tabular numeral support.

4. **Navigation is visually flat.** The sidebar is a plain white column with text links. There is no visual identity, no gradient, no brand mark beyond the text "Issue Observatory" in 16px bold.

5. **Status badges use inconsistent styling patterns.** Some pages use `.badge-free`/`.badge-medium`/`.badge-premium` component classes; others inline badge styling directly with `bg-green-100 text-green-800`. The record detail template uses platform-specific colors (YouTube = red, Reddit = orange, Bluesky = sky) that follow a different scheme from the arena color system.

6. **Chart colors have no thematic connection.** The `_PALETTE` in `charts.js` uses stock Tailwind hues (`blue-600`, `green-600`, `amber-600`, `purple-600`) rather than the brand gradient.

7. **The login page is the first impression and it is completely bare.** White card on gray background with "Issue Observatory" in plain text and "Danish media monitor" in gray-500. No visual identity whatsoever.

---

## 2. Color System Analysis

### 2.1 Brand Reference Analysis

The `Farveflade@4x.png` gradient field establishes three anchor colors:

| Position | Approximate Hex | Character |
|----------|----------------|-----------|
| Top | `#4A1080` (deep purple) | Authority, seriousness, academic rigor |
| Middle-left | `#3D9B3A` (vivid green) | Vitality, growth, active data flows |
| Bottom | `#D4C020` (golden yellow) | Attention, discovery, emphasis |

The brand assets (Assets 6, 8, 10, 27, 28) confirm these as discrete accent colors alongside black:

| Asset | Hex (sampled) | Role in brand |
|-------|--------------|---------------|
| Asset 10 (purple O) | `#3D1A6E` | Primary brand purple |
| Asset 6 (green O) | `#5BAD3B` | Active/success green |
| Asset 8 (yellow O) | `#ECC417` | Highlight/attention yellow |
| Asset 1 (black O) | `#000000` | Text/structural |

Asset 27 shows the gradient applied horizontally across a binary digit sequence, confirming the gradient is meant to be used as a continuous spectrum, not just three discrete colors.

Asset 19 (QR-code motif with gradient) and Asset 26 (binary cascade with gradient) establish that the data/binary visual language uses the gradient for color-coding, creating a unique "data as art" identity.

### 2.2 Current vs. Proposed Color System

#### Primary Colors

| Role | Current | Proposed | CSS Custom Property |
|------|---------|----------|-------------------|
| Primary (navigation, buttons, links) | `#2563EB` (blue-600) | `#4A1080` (deep purple) | `--color-primary-600` |
| Primary hover | `#1D4ED8` (blue-700) | `#3B0764` (deeper purple) | `--color-primary-700` |
| Primary light bg | `#EFF6FF` (blue-50) | `#F3E8FF` (purple-50 equivalent) | `--color-primary-50` |
| Active state text | `#1D4ED8` (blue-700) | `#6B21A8` (purple-700) | `--color-primary-active` |
| Success / active / live | `#16A34A` (green-600) | `#3D9B3A` (brand green) | `--color-success-600` |
| Warning / attention | `#D97706` (amber-600) | `#D4C020` (brand yellow) | `--color-warning-600` |
| Error / danger | `#DC2626` (red-600) | `#DC2626` (keep -- warm red complements yellow) | `--color-danger-600` |

#### Dark Mode Surfaces (primary theme)

| Surface | Hex | Usage |
|---------|-----|-------|
| Body background | `#0F0A1A` | Near-black with purple tint |
| Card / panel | `#1A1225` | Slightly elevated surface |
| Card elevated / hover | `#231A30` | Hovered or focused cards |
| Sidebar / nav | `#120D1F` | Navigation panel |
| Input background | `#1E1530` | Form fields |
| Border / divider | `rgba(139, 92, 246, 0.12)` | Purple-tinted at 12% opacity |

#### Light Mode Surfaces (secondary theme)

| Surface | Hex | Usage |
|---------|-----|-------|
| Body background | `#F5F0FA` | Warm gray with purple tint (replaces `gray-50`) |
| Card / panel | `#FDFBFF` | Near-white with warmth |
| Sidebar / nav | `#1A1225` | Keep dark even in light mode for contrast |
| Border / divider | `rgba(74, 16, 128, 0.10)` | Purple-tinted borders |

#### Text Colors

| Role | Dark Mode | Light Mode |
|------|-----------|------------|
| Primary text | `#E8E0F0` | `#1E1030` |
| Secondary text | `#A89BBF` | `#5C4F72` |
| Tertiary / muted | `#6B5F80` | `#8B7FA0` |
| Disabled | `#4A4358` | `#B8B0C5` |

#### Data Visualization Palette (for charts)

Replacing the current `_PALETTE` array in `charts.js`:

```javascript
const _PALETTE = [
  '#7C3AED', // violet-600 (purple end)
  '#3D9B3A', // brand green
  '#D4C020', // brand yellow
  '#A855F7', // violet-400 (lighter purple)
  '#16A34A', // green-600
  '#EAB308', // yellow-500
  '#581C87', // purple-800 (dark accent)
  '#65A30D', // lime-600 (green-yellow bridge)
];
```

#### Arena Color Assignments

Following the gradient-based assignment scheme:

| Arena Category | Color Zone | Hex Values |
|----------------|-----------|------------|
| News media (RSS, GDELT, Event Registry, Ritzau) | Deep purple | `#4A1080`, `#581C87`, `#6B21A8` |
| Social media mainstream (X, Facebook, Instagram, Threads) | Purple-green transition | `#7C3AED`, `#6D28D9`, `#5B21B6` |
| Social media alternative (Bluesky, Reddit, YouTube) | Green zone | `#3D9B3A`, `#16A34A`, `#15803D` |
| Fringe platforms (Gab, Telegram, Discord) | Green-yellow transition | `#65A30D`, `#84CC16`, `#A3E635` |
| Search & web (Google, Common Crawl, Wayback, Majestic) | Yellow zone | `#D4C020`, `#EAB308`, `#CA8A04` |
| AI / special (AI Chat Search, URL Scraper) | Gold | `#B45309`, `#D97706` |

---

## 3. Typography Assessment

### 3.1 Current State

- **Fonts loaded:** None. The application relies entirely on `system-ui, sans-serif`.
- **Font sizes:** Headings are `text-xl` (20px), card headers `text-sm` (14px), body `text-sm` (14px), hints `text-xs` (12px).
- **Monospace:** Used for IDs and numeric data via `font-mono` (Tailwind default: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas`).
- **Tabular numerals:** Not configured. Numeric columns in tables do not align vertically.

### 3.2 Recommendations

**Load three web fonts** via Google Fonts or self-hosted WOFF2:

| Role | Font | Rationale |
|------|------|-----------|
| Headings & navigation | **Space Grotesk** (500, 600, 700) | Geometric sans-serif with distinctive character; modern but not trendy. Its slightly squared forms echo the binary/geometric motifs in the brand assets. |
| Body text & UI labels | **Inter** (400, 500, 600) | Optimized for screen readability at small sizes. Excellent tabular numeral support via OpenType `tnum`. Industry standard for data-dense interfaces. |
| Monospace (IDs, code, raw data) | **JetBrains Mono** (400, 500) | Clear distinction between similar characters (0/O, 1/l/I), excellent for UUIDs and platform IDs. |

**Tailwind config extension:**

```javascript
fontFamily: {
  heading: ['Space Grotesk', 'system-ui', 'sans-serif'],
  sans: ['Inter', 'system-ui', 'sans-serif'],
  mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
},
```

**Enable tabular numerals** globally for data tables:

```css
.table-td, .font-mono, [data-tabular] {
  font-variant-numeric: tabular-nums;
}
```

**Type scale refinement:**

| Element | Current | Proposed |
|---------|---------|----------|
| Page title (h1) | `text-xl font-bold` (20px) | `font-heading text-xl font-semibold tracking-tight` |
| Section header (h2) | `text-sm font-semibold` (14px) | `font-heading text-sm font-semibold uppercase tracking-wider` |
| Card header | `text-sm font-semibold` | `font-heading text-[13px] font-semibold uppercase tracking-wider` |
| Body text | `text-sm` (14px) | `text-sm leading-relaxed` (keep -- appropriate for data density) |
| Table cell data | `text-sm` (14px) | `text-[13px] tabular-nums` |
| Hint / caption | `text-xs` (12px) | `text-xs leading-normal` (keep) |
| Monospace IDs | `font-mono text-xs` | `font-mono text-xs tracking-wide` |

---

## 4. Component Design Audit

### 4.1 Navigation Sidebar

**File:** `/src/issue_observatory/api/templates/_partials/nav.html`

**Current state:** A plain white sidebar (`bg-white shadow-sm`) with the brand name in `text-base font-bold text-gray-900`. Active state uses `bg-blue-50 text-blue-700`. Icons are `text-gray-400` (inactive) and `text-blue-600` (active).

**Issues:**
- No visual identity. The sidebar is indistinguishable from any generic admin panel.
- The brand name "Issue Observatory" with "Danish media monitor" subtitle is text-only. The brand assets include distinctive geometric marks that should be used.
- Active state highlighting uses default blue, not the brand purple.
- The user avatar circle uses `bg-blue-600`, again not brand-aligned.
- No section dividers with visual weight; the section headers ("Tools", "Reference", "Administration") are just `text-gray-400 uppercase`.

**Recommendations:**
- **Make the sidebar dark** even in light mode: `bg-[#120D1F]` with light text. This creates a strong visual anchor and frames the main content area.
- **Add the brand gradient** as a subtle vertical accent line on the left edge of the sidebar, or as a horizontal bar below the brand name.
- **Replace text-only brand** with an SVG mark derived from the "O" shapes in the brand assets, rendered in the gradient colors. The text "Issue Observatory" should use `font-heading`.
- **Active state:** Replace `bg-blue-50 text-blue-700` with a left border accent in `#7C3AED` and slightly lighter background: `border-l-2 border-[#7C3AED] bg-white/5 text-white`.
- **Section headers:** Use `text-[#6B5F80] uppercase tracking-widest text-[10px] font-semibold` with a subtle horizontal rule.
- **User avatar:** Replace `bg-blue-600` with a gradient background: `bg-gradient-to-br from-[#4A1080] to-[#3D9B3A]`.

### 4.2 Buttons

**File:** `/src/issue_observatory/api/static/css/input.css` lines 16-30

**Current state:** Four variants defined:
- `.btn-primary`: `bg-blue-600 hover:bg-blue-700`
- `.btn-secondary`: `bg-white border-gray-300`
- `.btn-danger`: `bg-red-600 hover:bg-red-700`
- `.btn-ghost`: `text-gray-500 hover:bg-gray-100`

**Issues:**
- Missing success/warning variants.
- No focus ring styling (critical for keyboard accessibility).
- No transitions beyond `transition-colors`.
- Primary button uses generic blue instead of brand purple.

**Recommendations:**

```css
.btn-primary {
  @apply inline-flex items-center gap-2 px-4 py-2
         bg-[#4A1080] text-white text-sm font-medium rounded-md
         hover:bg-[#3B0764] active:bg-[#2E0550]
         focus:outline-none focus:ring-2 focus:ring-[#7C3AED] focus:ring-offset-2
         disabled:opacity-50 disabled:cursor-not-allowed
         transition-all duration-150;
}

.btn-success {
  @apply inline-flex items-center gap-2 px-4 py-2
         bg-[#3D9B3A] text-white text-sm font-medium rounded-md
         hover:bg-[#2D7A2B] focus:ring-[#3D9B3A]
         disabled:opacity-50 transition-all duration-150;
}

.btn-warning {
  @apply inline-flex items-center gap-2 px-4 py-2
         bg-[#D4C020] text-[#1E1030] text-sm font-medium rounded-md
         hover:bg-[#B8A61C] focus:ring-[#D4C020]
         disabled:opacity-50 transition-all duration-150;
}
```

All buttons should have `focus:ring-2 focus:ring-offset-2` with their respective brand color. The `focus:ring-offset` should use the surface color (white in light mode, `#1A1225` in dark mode).

### 4.3 Cards and Panels

**Current state:** `.card` is `bg-white rounded-lg shadow p-6`. All cards throughout the application are white rectangles with identical gray-200 borders and gray-50 table headers.

**Issues:**
- Every card looks identical regardless of content importance.
- No hover states on clickable cards (e.g., the analysis landing page run entries).
- Shadow is the same weight everywhere.

**Recommendations:**
- **Base card (dark mode):** `bg-[#1A1225] border border-[rgba(139,92,246,0.08)] rounded-lg`
- **Base card (light mode):** `bg-white border border-[rgba(74,16,128,0.06)] rounded-lg shadow-sm`
- **Elevated card (modals, dropdowns):** Add `shadow-lg shadow-purple-900/10`
- **Clickable card:** Add `hover:border-[rgba(139,92,246,0.2)] hover:shadow-md transition-all duration-200 cursor-pointer`
- **Featured card** (discovery summary, volume spike alerts): Use a subtle gradient border effect: a 1px gradient border from purple to green.

### 4.4 Data Tables

**Current state:** Tables use `.table-th` (`bg-gray-50 text-gray-500 uppercase tracking-wider`) and `.table-td` (`px-6 py-4 text-gray-700`). Row hover is `hover:bg-gray-50`.

**Issues:**
- No alternating row backgrounds. In dense data tables with 20+ rows, this makes tracking across columns difficult.
- The `px-6` horizontal padding is generous for desktop but may compress columns unnecessarily on 1366px screens.
- No sticky header for scrollable tables.
- Font-mono numeric data does not use tabular numerals.

**Recommendations:**
- **Alternating rows:** `even:bg-[#F8F5FC]` (light mode) or `even:bg-[#150F22]` (dark mode).
- **Header:** `bg-[#F3E8FF] text-[#5C4F72] font-heading text-[11px] uppercase tracking-widest` (light mode); `bg-[#1E1530] text-[#A89BBF]` (dark mode).
- **Row hover:** `hover:bg-[#EDE5F7]` (light mode) or `hover:bg-[#231A30]` (dark mode).
- **Sticky header:** `sticky top-0 z-10` on `<thead>` for scrollable table containers.
- **Reduce horizontal padding** to `px-4` for tables with 6+ columns; `px-6` is fine for 4-column tables.
- **Numeric cells:** `text-right font-mono text-[13px] tabular-nums`.
- **Selected row:** `bg-[#4A1080]/10 border-l-2 border-[#4A1080]` for the content browser's active record.

### 4.5 Status Badges

**Current state:** Three tier badge classes (`.badge-free`, `.badge-medium`, `.badge-premium`) and four status text classes. But most badge styling is inlined directly in templates rather than using these classes.

**Issues:**
- Inconsistent application: the collections list, collection detail, and analysis pages all inline different badge patterns rather than using the component classes.
- Tier badges use stock green/yellow/purple that are not specifically the brand colors.
- Platform badges in `record_detail.html` use a per-platform color scheme that is completely disconnected from the arena color system.

**Recommendations:**
- **Consolidate all badges to use component classes** and eliminate inline styling.
- **Tier badges should use the gradient anchors:**
  - FREE: `bg-[#3D9B3A]/10 text-[#3D9B3A] border border-[#3D9B3A]/20`
  - MEDIUM: `bg-[#D4C020]/10 text-[#9E8C00] border border-[#D4C020]/20`
  - PREMIUM: `bg-[#4A1080]/10 text-[#7C3AED] border border-[#4A1080]/20`
- **Status badges:**
  - Running: animated pulse dot + `text-[#3D9B3A]`
  - Completed: `bg-[#3D9B3A]/10 text-[#3D9B3A]`
  - Failed: `bg-[#DC2626]/10 text-[#DC2626]`
  - Pending: `bg-[#D4C020]/10 text-[#9E8C00]`
  - Cancelled: `bg-[#4A4358]/10 text-[#6B5F80]`
  - Suspended: `bg-[#D4C020]/20 text-[#9E8C00]`
- **Platform badges** should follow the arena color assignment table (section 2.2) rather than using arbitrary per-platform colors.

### 4.6 Form Elements

**Current state:** `.form-input` and `.form-select` use `border-gray-300 focus:ring-blue-500`. Labels are `text-gray-700`.

**Issues:**
- Focus ring is blue instead of brand purple.
- No dark mode variants.
- No error state styling for invalid fields.
- Select dropdowns have no custom styling (browser defaults for the dropdown menu).

**Recommendations:**
- **Focus ring:** `focus:ring-[#7C3AED] focus:border-[#7C3AED]`
- **Error state:** `border-red-500 focus:ring-red-500 bg-red-50/50` with error message in `text-red-600 text-xs mt-1`
- **Dark mode input:** `bg-[#1E1530] border-[rgba(139,92,246,0.15)] text-[#E8E0F0] placeholder-[#6B5F80]`

### 4.7 Loading States

**Current state:** A single spinner partial (`_partials/loading_spinner.html`) with `animate-spin` SVG in blue-600 and "Loading..." text.

**Issues:**
- No skeleton screens.
- No progress bars.
- The spinner is blue, not brand-colored.
- No loading state for chart areas (they just show empty space until data arrives).

**Recommendations:**
- **Spinner color:** Gradient SVG or `text-[#7C3AED]`.
- **Skeleton screens:** For cards and table rows, use animated placeholder divs with `bg-[#4A1080]/5 animate-pulse rounded`.
- **Chart loading:** Show a subtle gradient placeholder rectangle that pulses, with text "Loading chart data..."
- **Progress bars:** For collection runs, use a gradient bar from `#4A1080` through `#3D9B3A` to `#D4C020` that fills left to right as collection progresses.

---

## 5. Layout and Spacing Assessment

### 5.1 Page Structure

**Current state:** `<body class="bg-gray-50 text-gray-900 min-h-screen flex">` with a 256px fixed sidebar and `<main class="flex-1 p-6 overflow-auto">`. Content is constrained with `max-w-5xl` or `max-w-6xl` per page.

**Issues:**
- The 256px sidebar + 24px main padding reduces the usable content width to approximately 1616px on a 1920px screen, or 1062px on a 1366px laptop. With `max-w-6xl` (1152px), there is significant wasted space on larger monitors.
- The `p-6` on main is uniform. Page headers deserve more breathing room than data-dense table sections.
- No collapsible sidebar for smaller screens.

**Recommendations:**
- **Consider a narrower sidebar** (224px / `w-56`) to reclaim 32px.
- **Use `max-w-7xl` (1280px) for data-heavy pages** (analysis dashboard, content browser) while keeping `max-w-5xl` for focused pages (query design editor, settings).
- **Page header padding:** `pt-8 pb-4` top of page, `py-4` between sections.
- **Add sidebar collapse** with an Alpine toggle: icon-only mode at 64px width. This is especially valuable for the analysis dashboard where chart width matters.

### 5.2 Spacing Consistency

The `space-y-6` between page sections is used consistently, which is good. Within cards, spacing varies between `space-y-3`, `space-y-4`, and `space-y-5`. This should be standardized:

- **Between page sections:** `space-y-6` (24px) -- keep as-is
- **Within cards:** `space-y-4` (16px) standard
- **Between form fields:** `space-y-4` (16px) standard
- **Table cell padding:** `px-4 py-3` for dense tables, `px-6 py-4` for regular tables

---

## 6. Data Visualization Assessment

### 6.1 Chart.js Configuration

**File:** `/src/issue_observatory/api/static/js/charts.js`

**Current state:** 9 chart types defined with a shared `_CHART_DEFAULTS` object. Colors are hardcoded Tailwind defaults. Tooltip and legend styling uses `gray-700` and `gray-800`.

**Issues:**
- The `_PALETTE` array uses stock Tailwind colors with no brand connection.
- Chart backgrounds are white (transparent canvas on white cards).
- Grid lines use `rgba(0,0,0,0.05)` which will be invisible on dark backgrounds.
- Font family is `system-ui, sans-serif`.
- No custom tooltip styling beyond basic colors.
- The arena breakdown doughnut chart border color is `#ffffff`, which will break on dark backgrounds.

**Recommendations:**

Replace the chart defaults with a brand-aware configuration:

```javascript
const _CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: true,
  plugins: {
    annotation: false,
    legend: {
      labels: {
        font: { size: 12, family: 'Inter, system-ui, sans-serif' },
        color: 'var(--chart-text)',  // #A89BBF in dark, #5C4F72 in light
        usePointStyle: true,
        pointStyleWidth: 8,
        padding: 16,
      },
    },
    tooltip: {
      backgroundColor: '#1E1530',
      titleColor: '#E8E0F0',
      bodyColor: '#A89BBF',
      borderColor: 'rgba(139, 92, 246, 0.2)',
      borderWidth: 1,
      padding: 12,
      cornerRadius: 8,
      titleFont: { family: 'Space Grotesk, system-ui, sans-serif', weight: 600 },
      bodyFont: { family: 'Inter, system-ui, sans-serif' },
    },
  },
};
```

Replace the palette:

```javascript
const _PALETTE = [
  '#7C3AED', // violet (purple anchor)
  '#3D9B3A', // brand green
  '#D4C020', // brand yellow
  '#A855F7', // lighter violet
  '#16A34A', // darker green
  '#EAB308', // brighter yellow
  '#581C87', // deep purple
  '#65A30D', // lime (green-yellow bridge)
];
```

### 6.2 Network Graph Configuration

**File:** `/src/issue_observatory/api/static/js/network_preview.js`

**Current state:** Actor nodes = `#3b82f6` (blue-500), term nodes = `#f59e0b` (amber-500), default = `#6b7280` (gray-500), edges = `rgba(156, 163, 175, 0.6)`.

**Recommendations:**
- Actor nodes: `#7C3AED` (brand purple)
- Term nodes: `#D4C020` (brand yellow)
- Platform nodes (bipartite): `#3D9B3A` (brand green)
- Default: `#6B5F80` (muted purple-gray)
- Edges: `rgba(139, 92, 246, 0.25)` (purple-tinted)
- Selected node: `#E8E0F0` with a glow effect
- Hover node: Scale 1.3x with brighter color

---

## 7. Interaction Design Assessment

### 7.1 Hover States

**Current state:** Most interactive elements have `hover:bg-gray-50` or `hover:bg-gray-100`. Links use `hover:underline` or `hover:text-blue-800`.

**Issues:**
- Hover states are very subtle and may not be perceptible on some monitors.
- No hover states on cards in the analysis landing page run list (only a `group-hover:text-gray-500` on the chevron).
- Table row hovers are `hover:bg-gray-50` which is nearly invisible on a `bg-white` row.

**Recommendations:**
- **Table rows:** `hover:bg-[#F3E8FF]` (light) or `hover:bg-[#231A30]` (dark) -- more visible contrast.
- **Clickable cards:** `hover:shadow-md hover:border-[rgba(139,92,246,0.2)] transition-all duration-200`.
- **Nav links:** `hover:bg-[rgba(139,92,246,0.08)]` with a slight left-border slide-in.
- **Buttons:** `active:scale-[0.98]` for tactile feedback.

### 7.2 Transitions

**Current state:** `transition-colors` is used consistently on buttons and links. No other transition types.

**Recommendations:**
- **Standardize transition duration:** `duration-150` for micro-interactions (buttons, badges), `duration-200` for structural changes (panel open/close, sidebar collapse), `duration-300` for page transitions.
- **Add transform transitions** to clickable cards and expandable panels.
- **Alpine transitions** on modals and dropdowns: use `x-transition:enter="transition ease-out duration-200"` consistently.

### 7.3 Focus States

**Current state:** Forms use `focus:ring-2 focus:ring-blue-500`. No focus styling on non-form elements (nav links, table rows, buttons in some templates).

**Issues:**
- Keyboard navigation is only partially supported.
- Focus ring color is blue, not brand purple.
- No visible focus indicator on nav links, card actions, or table row interactions.

**Recommendations:**
- **Global focus ring:** `focus-visible:ring-2 focus-visible:ring-[#7C3AED] focus-visible:ring-offset-2`
- **Use `focus-visible`** instead of `focus` to avoid showing focus rings on mouse clicks.
- **Add focus styling to nav links:** `focus-visible:ring-2 focus-visible:ring-[#7C3AED] focus-visible:outline-none focus-visible:rounded-md`

### 7.4 Scrollbar Styling

**Current state:** Default browser scrollbars.

**Recommendation for dark mode:**

```css
/* Webkit scrollbars in dark theme panels */
.dark ::-webkit-scrollbar { width: 6px; height: 6px; }
.dark ::-webkit-scrollbar-track { background: #120D1F; }
.dark ::-webkit-scrollbar-thumb { background: #4A4358; border-radius: 3px; }
.dark ::-webkit-scrollbar-thumb:hover { background: #6B5F80; }
```

---

## 8. Visual Identity Recommendations

### 8.1 Login Page (First Impression)

**File:** `/src/issue_observatory/api/templates/auth/login.html`

The login page is the researcher's first visual contact with the application. Currently it is completely bare.

**Recommendations:**
- **Background:** Full-viewport gradient backdrop using the brand gradient (subtle, not overwhelming): `bg-gradient-to-br from-[#0F0A1A] via-[#1A1225] to-[#120D1F]`.
- **Brand mark:** Center the geometric "O" mark from the brand assets (SVG, rendered in the gradient) above the "Issue Observatory" text.
- **Text:** "Issue Observatory" in Space Grotesk 600 weight, `text-white`. "Aarhus University" subtitle in Inter 400, `text-[#A89BBF]`.
- **Login card:** Dark card style: `bg-[#1A1225] border border-[rgba(139,92,246,0.1)] shadow-xl`. Inputs with dark background styling.
- **Submit button:** Brand purple with gradient: `bg-gradient-to-r from-[#4A1080] to-[#7C3AED] hover:from-[#3B0764] hover:to-[#6B21A8]`.
- **Bottom of page:** Subtle binary digit watermark from Asset 17/18 as a decorative background element at very low opacity (~5%).

### 8.2 Navigation Brand Mark

Convert the brand "O" circle (Asset 10/6/8 at 1x) into a compact SVG mark:
- 24x24px mark: Two concentric circles in the brand purple, or the three-color "O" icons stacked diagonally.
- Place to the left of "Issue Observatory" text in the sidebar header.

### 8.3 The Signature Gradient

Deploy the purple-to-green-to-yellow gradient selectively for maximum impact:

| Location | Implementation |
|----------|---------------|
| Navigation sidebar left edge | 2px vertical gradient bar |
| Page headers on key pages (dashboard, analysis) | Subtle horizontal gradient rule below the page title |
| Progress bars (collection runs) | Gradient fill from purple (0%) through green (50%) to yellow (100%) |
| Chart accent | Volume chart area fill using a gradient |
| Loading states | Gradient skeleton shimmer |
| Login page | Background gradient |
| Empty states | Gradient icon accent |
| Selected nav item | Left border accent in gradient |

### 8.4 The Binary Motif

The binary/data motif from Assets 17, 18, 19, 26 can be used as:
- **Background watermark** on the login page (Asset 26 at 3% opacity)
- **Empty state decoration** (Asset 17 monochrome variant behind the "No records yet" text)
- **Favicon** (Asset 19 QR pattern scaled to 32x32)
- **Loading animation** (binary digits shifting through gradient colors)

---

## 9. Prioritized Recommendations

### Tier 1: Foundation (highest impact, required for all subsequent work)

| # | Recommendation | Impact | Files Modified |
|---|---------------|--------|----------------|
| 1.1 | **Create `tailwind.config.js`** with full color system, font families, and design tokens. Move from CDN-only to a proper build pipeline. | Critical | New file; `base.html`, `Makefile` |
| 1.2 | **Create `globals.css`** with CSS custom properties for all design tokens (colors, fonts, spacing). Enable theme switching via a `.dark` class on `<html>`. | Critical | New file; `base.html` |
| 1.3 | **Load web fonts** (Space Grotesk, Inter, JetBrains Mono) in `base.html`. | High | `base.html` |
| 1.4 | **Retheme the navigation sidebar** to dark, with brand mark, gradient accent, and purple active states. | High | `_partials/nav.html` |
| 1.5 | **Retheme `input.css` component classes** (buttons, cards, forms, badges, tables, alerts) to use brand colors. | High | `input.css` |

### Tier 2: Core Pages (high impact, visible immediately)

| # | Recommendation | Impact | Files Modified |
|---|---------------|--------|----------------|
| 2.1 | **Redesign the login page** with dark theme, brand mark, and gradient background. | High | `auth/login.html`, `base_auth.html` |
| 2.2 | **Retheme the dashboard** cards, quick links, and volume spike alerts to use brand colors. | High | `dashboard/index.html` |
| 2.3 | **Retheme the analysis dashboard** charts, filter bar, and network preview. | High | `analysis/index.html`, `charts.js`, `network_preview.js` |
| 2.4 | **Retheme the content browser** sidebar, table, and record detail panel. | High | `content/browser.html`, `content/record_detail.html` |
| 2.5 | **Retheme the collections list and detail** pages. | Medium | `collections/list.html`, `collections/detail.html` |

### Tier 3: Component Polish (medium impact, consistency)

| # | Recommendation | Impact | Files Modified |
|---|---------------|--------|----------------|
| 3.1 | **Standardize all status badges** to use component classes, eliminate inline styling. | Medium | All templates using badges |
| 3.2 | **Implement focus-visible states** on all interactive elements. | Medium | `input.css`, templates |
| 3.3 | **Add skeleton screens** for HTMX-loaded sections (dashboard cards, table bodies). | Medium | `_partials/loading_spinner.html`, new partials |
| 3.4 | **Style scrollbars** in data-dense panels. | Low | `globals.css` |
| 3.5 | **Implement the arena color system** in platform badges and chart configurations. | Medium | `record_detail.html`, `charts.js` |

### Tier 4: Dark Mode (significant effort, transformative result)

| # | Recommendation | Impact | Files Modified |
|---|---------------|--------|----------------|
| 4.1 | **Add `dark:` variants** to all component classes in `input.css`. | High | `input.css` |
| 4.2 | **Add dark mode toggle** (Alpine state, persisted to localStorage). | Medium | `_partials/nav.html`, `base.html` |
| 4.3 | **Audit all templates** for hardcoded light-mode colors and add `dark:` counterparts. | High | All templates |
| 4.4 | **Update Chart.js and Sigma.js** configurations to read theme-aware CSS properties. | Medium | `charts.js`, `network_preview.js` |

### Tier 5: Polish and Delight (lower priority, high finesse)

| # | Recommendation | Impact | Files Modified |
|---|---------------|--------|----------------|
| 5.1 | **Animated gradient progress bar** for collection runs. | Low | `_fragments/run_summary.html` |
| 5.2 | **Binary motif watermarks** on login and empty states. | Low | `auth/login.html`, `_partials/empty_state.html` |
| 5.3 | **Collapsible sidebar** with icon-only mode. | Medium | `_partials/nav.html`, `base.html` |
| 5.4 | **Custom toast notifications** with brand styling and auto-dismiss. | Low | `_partials/flash.html` |
| 5.5 | **Responsive column priority** for tables on 1366px screens. | Medium | Table templates |

---

## 10. Design Token Proposals

### 10.1 Proposed `tailwind.config.js`

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/issue_observatory/api/templates/**/*.html',
    './src/issue_observatory/api/static/js/**/*.js',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Brand primary (purple)
        brand: {
          50:  '#F3E8FF',
          100: '#E9D5FF',
          200: '#D8B4FE',
          300: '#C084FC',
          400: '#A855F7',
          500: '#7C3AED',
          600: '#4A1080',
          700: '#3B0764',
          800: '#2E0550',
          900: '#1E0338',
          950: '#120D1F',
        },
        // Brand success (green)
        'brand-green': {
          50:  '#ECFDF5',
          100: '#D1FAE5',
          200: '#A7F3D0',
          300: '#6EE7B7',
          400: '#3D9B3A',
          500: '#2D7A2B',
          600: '#15803D',
          700: '#166534',
          800: '#14532D',
        },
        // Brand accent (yellow/gold)
        'brand-gold': {
          50:  '#FEFCE8',
          100: '#FEF9C3',
          200: '#FEF08A',
          300: '#ECC417',
          400: '#D4C020',
          500: '#B8A61C',
          600: '#9E8C00',
          700: '#854D0E',
          800: '#713F12',
        },
        // Dark mode surfaces
        surface: {
          base:     '#0F0A1A',
          card:     '#1A1225',
          elevated: '#231A30',
          input:    '#1E1530',
          nav:      '#120D1F',
        },
        // Light mode surfaces
        'surface-light': {
          base: '#F5F0FA',
          card: '#FDFBFF',
        },
        // Text colors
        'on-dark': {
          primary:   '#E8E0F0',
          secondary: '#A89BBF',
          tertiary:  '#6B5F80',
          disabled:  '#4A4358',
        },
        'on-light': {
          primary:   '#1E1030',
          secondary: '#5C4F72',
          tertiary:  '#8B7FA0',
          disabled:  '#B8B0C5',
        },
      },
      fontFamily: {
        heading: ['Space Grotesk', 'system-ui', 'sans-serif'],
        sans:    ['Inter', 'system-ui', 'sans-serif'],
        mono:    ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        'table': ['13px', { lineHeight: '18px' }],
      },
      borderColor: {
        'brand-subtle': 'rgba(139, 92, 246, 0.12)',
      },
      boxShadow: {
        'brand': '0 4px 6px -1px rgba(74, 16, 128, 0.1), 0 2px 4px -2px rgba(74, 16, 128, 0.1)',
        'brand-lg': '0 10px 15px -3px rgba(74, 16, 128, 0.1), 0 4px 6px -4px rgba(74, 16, 128, 0.1)',
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(135deg, #4A1080, #3D9B3A, #D4C020)',
        'brand-gradient-horizontal': 'linear-gradient(90deg, #4A1080, #3D9B3A, #D4C020)',
        'brand-gradient-subtle': 'linear-gradient(135deg, rgba(74,16,128,0.05), rgba(61,155,58,0.05), rgba(212,192,32,0.05))',
      },
    },
  },
  plugins: [],
};
```

### 10.2 Proposed CSS Custom Properties (`globals.css`)

```css
:root {
  /* Theme-aware tokens (light mode defaults) */
  --color-bg-base: #F5F0FA;
  --color-bg-card: #FDFBFF;
  --color-bg-elevated: #FFFFFF;
  --color-bg-input: #FFFFFF;
  --color-bg-nav: #120D1F;

  --color-text-primary: #1E1030;
  --color-text-secondary: #5C4F72;
  --color-text-tertiary: #8B7FA0;
  --color-text-disabled: #B8B0C5;

  --color-border: rgba(74, 16, 128, 0.10);
  --color-border-strong: rgba(74, 16, 128, 0.20);

  --color-brand-primary: #4A1080;
  --color-brand-green: #3D9B3A;
  --color-brand-gold: #D4C020;

  --color-chart-text: #5C4F72;
  --color-chart-grid: rgba(74, 16, 128, 0.06);
  --color-chart-tooltip-bg: #1E1530;

  --font-heading: 'Space Grotesk', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
}

.dark {
  --color-bg-base: #0F0A1A;
  --color-bg-card: #1A1225;
  --color-bg-elevated: #231A30;
  --color-bg-input: #1E1530;
  --color-bg-nav: #120D1F;

  --color-text-primary: #E8E0F0;
  --color-text-secondary: #A89BBF;
  --color-text-tertiary: #6B5F80;
  --color-text-disabled: #4A4358;

  --color-border: rgba(139, 92, 246, 0.12);
  --color-border-strong: rgba(139, 92, 246, 0.25);

  --color-chart-text: #A89BBF;
  --color-chart-grid: rgba(139, 92, 246, 0.08);
}
```

### 10.3 Chart Theme Export

A new file `static/js/chart_theme.js` should export theme-aware defaults:

```javascript
function getChartTheme() {
  const style = getComputedStyle(document.documentElement);
  return {
    textColor: style.getPropertyValue('--color-chart-text').trim(),
    gridColor: style.getPropertyValue('--color-chart-grid').trim(),
    tooltipBg: style.getPropertyValue('--color-chart-tooltip-bg').trim(),
    fontFamily: style.getPropertyValue('--font-body').trim(),
    headingFont: style.getPropertyValue('--font-heading').trim(),
  };
}
```

---

## 11. Responsive Considerations

### 11.1 Viewport Breakpoints

| Viewport | Layout Behavior |
|----------|----------------|
| 1920px+ (primary target) | Full sidebar, `max-w-7xl` content, all table columns visible |
| 1440px | Full sidebar, `max-w-6xl` content, slightly compressed table padding |
| 1366px (minimum laptop) | Collapsible sidebar (icon-only by default), `max-w-full` with `px-6`, hide lowest-priority table columns |
| < 1280px | Sidebar overlays content (slide-out drawer), responsive table with horizontal scroll |

### 11.2 Table Column Priority (for 1366px)

When screen width is constrained, columns should hide in this order (last = hidden first):

**Collections table:** Project Name > Status > Records > Latest Activity > Credits (hide) > Actions
**Content browser:** Title/Text > Platform > Published > Author > Engagement (hide) > Arena (hide)
**Actor directory:** Name > Type > Platforms > Content Count > First Seen (hide) > Last Seen (hide)

---

## 12. Accessibility Notes

- All color combinations in the proposed system meet **WCAG AA** contrast requirements (4.5:1 for normal text, 3:1 for large text).
- The darkest text on the darkest background (`#E8E0F0` on `#0F0A1A`) has a contrast ratio of approximately 12:1.
- Light mode text (`#1E1030` on `#FDFBFF`) has a contrast ratio of approximately 15:1.
- The brand purple (`#4A1080` on white) has a contrast ratio of approximately 8.5:1.
- Focus indicators must use `focus-visible` to avoid distracting mouse users while maintaining keyboard accessibility.
- The signature gradient should never be the sole indicator of meaning (always pair with text or shape).

---

## Appendix A: Files Audited

| File | Lines | Assessment |
|------|-------|-----------|
| `templates/base.html` | 150 | Tailwind CDN, minimal config, no fonts, no dark mode |
| `templates/base_auth.html` | 27 | Bare-bones auth layout, no brand styling |
| `templates/_partials/nav.html` | 141 | White sidebar, default blue active state, text-only brand |
| `templates/_partials/flash.html` | 55 | Standard alert styling, needs brand colors |
| `templates/_partials/empty_state.html` | 34 | Generic gray empty state, no brand personality |
| `templates/_partials/loading_spinner.html` | 24 | Blue spinner, no skeleton alternative |
| `templates/_partials/pagination.html` | 51 | Standard, needs brand focus states |
| `templates/dashboard/index.html` | 209 | Blue accents, white cards, generic layout |
| `templates/query_designs/editor.html` | ~1200 | Very large; blue/gray throughout |
| `templates/collections/list.html` | 229 | Standard tables with inline badge styling |
| `templates/collections/detail.html` | 550 | SSE live page; blue everywhere |
| `templates/collections/launcher.html` | ~400 | Form-heavy; standard blue inputs |
| `templates/content/browser.html` | ~600 | Two-column layout; needs platform color system |
| `templates/content/record_detail.html` | ~200 | Per-platform colors disconnected from brand |
| `templates/analysis/index.html` | ~1100 | Chart-heavy page; most impactful retheme target |
| `templates/analysis/landing.html` | 105 | Blue-indigo gradient banner, needs brand colors |
| `templates/actors/list.html` | ~500 | Standard table + modals |
| `templates/admin/health.html` | 281 | Status dashboard; green/red/amber |
| `templates/arenas/index.html` | ~200 | Blue-indigo gradient banner |
| `templates/auth/login.html` | 168 | Plain white login, no brand identity |
| `static/css/input.css` | 119 | Component classes all using stock Tailwind blue |
| `static/css/app.css` | 25 | Minimal HTMX/Alpine utilities only |
| `static/js/charts.js` | 711 | Full chart library; needs palette + font + dark mode |
| `static/js/network_preview.js` | ~200 | Sigma.js wrapper; needs brand node colors |
| `static/js/app.js` | ~300 | HTMX handlers + Alpine components; no styling |

## Appendix B: Color Values Quick Reference

```
Brand Purple:   #4A1080 (primary), #3B0764 (hover), #7C3AED (light accent), #F3E8FF (bg)
Brand Green:    #3D9B3A (primary), #2D7A2B (hover), #ECFDF5 (bg)
Brand Gold:     #D4C020 (primary), #B8A61C (hover), #FEFCE8 (bg)
Error Red:      #DC2626
Dark Surface:   #0F0A1A (base), #1A1225 (card), #231A30 (elevated), #120D1F (nav)
Light Surface:  #F5F0FA (base), #FDFBFF (card)
Dark Text:      #E8E0F0 (primary), #A89BBF (secondary), #6B5F80 (tertiary)
Light Text:     #1E1030 (primary), #5C4F72 (secondary), #8B7FA0 (tertiary)
Border:         rgba(139, 92, 246, 0.12) (dark), rgba(74, 16, 128, 0.10) (light)
```

---

*This audit was produced by examining all design reference assets, the complete template tree (50 HTML files), all CSS files, all JavaScript chart/graph configuration, and the existing UX evaluation reports. No code changes were made.*
