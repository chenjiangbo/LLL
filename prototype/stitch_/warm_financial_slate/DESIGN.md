---
name: Warm Financial Slate
colors:
  surface: '#fbf9f3'
  surface-dim: '#dcdad4'
  surface-bright: '#fbf9f3'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f3ed'
  surface-container: '#f0eee8'
  surface-container-high: '#eae8e2'
  surface-container-highest: '#e4e2dd'
  on-surface: '#1b1c18'
  on-surface-variant: '#414943'
  inverse-surface: '#30312d'
  inverse-on-surface: '#f3f1eb'
  outline: '#717972'
  outline-variant: '#c1c8c1'
  surface-tint: '#3e674e'
  primary: '#2b543c'
  on-primary: '#ffffff'
  primary-container: '#436c53'
  on-primary-container: '#beebcc'
  inverse-primary: '#a4d1b3'
  secondary: '#a73354'
  on-secondary: '#ffffff'
  secondary-container: '#ff7797'
  on-secondary-container: '#750630'
  tertiary: '#434c54'
  on-tertiary: '#ffffff'
  tertiary-container: '#5b646d'
  on-tertiary-container: '#d8e1eb'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#c0edce'
  primary-fixed-dim: '#a4d1b3'
  on-primary-fixed: '#002111'
  on-primary-fixed-variant: '#264f38'
  secondary-fixed: '#ffd9de'
  secondary-fixed-dim: '#ffb2bf'
  on-secondary-fixed: '#3f0016'
  on-secondary-fixed-variant: '#88193d'
  tertiary-fixed: '#dae3ee'
  tertiary-fixed-dim: '#bec7d1'
  on-tertiary-fixed: '#141d24'
  on-tertiary-fixed-variant: '#3f4850'
  background: '#fbf9f3'
  on-background: '#1b1c18'
  surface-variant: '#e4e2dd'
typography:
  display-hero:
    fontFamily: inter
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
  body-lg:
    fontFamily: inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  body-md:
    fontFamily: inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-sm:
    fontFamily: inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  tabular-metric-lg:
    fontFamily: inter
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.01em
  tabular-metric-md:
    fontFamily: inter
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
  label-badge:
    fontFamily: inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
  label-micro:
    fontFamily: inter
    fontSize: 10px
    fontWeight: '400'
    lineHeight: 12px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  space-2xs: 0.125rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-base: 1rem
  space-lg: 1.25rem
  space-xl: 1.5rem
  space-2xl: 2rem
  container-padding: 1.25rem
  table-cell-py: 0.625rem
  table-cell-px: 0.75rem
---

## Brand & Style

This design system embodies a modern, intellectual, and high-precision financial analytics workbench. Tailored for quantitative traders, market researchers, and equities analysts, it replaces standard cold, aggressive fintech interfaces with a warm, organic, and calm editorial palette balanced with sharp institutional utility.

The core aesthetic draws upon **Modern Editorial Minimalism** infused with **Tactile Data Surfaces**:
- **Warm Grounding:** An earthy, warm paper tone serves as the foundation, reducing eye fatigue during intense multi-hour market monitoring.
- **Disciplined Categorical Color:** Rich, deep saturation is reserved exclusively for high-signal categorical triage: forest slate green for active discovery/momentum, dark charcoal slate for preparatory status, and deep crimson/burgundy for alerts, completed waves, or exit criteria.
- **High-Density Legibility:** Clean structural division, crisp white cards, hairline warm borders, and compact tabular metrics designed to convey multi-factor market signals without visual chaos.

## Colors

The palette establishes an intentional hierarchy where semantic data states emerge cleanly over an organic, off-white background.

### Core Palettes
- **Surface Canvas (Base Background):** `#F4F2EC` (Warm muted stone/sand). Provides zero-glare, comfortable background contrast.
- **Surface Elevation (Cards & Panels):** `#FFFFFF` (Crisp stark white) layered over the beige-grey base, bounded by subtle hairline borders (`#E5E2D9`).
- **Primary (Positive Momentum / Active Focus):** `#436C53` (Deep forest sage). Used for active tab selections, primary discovery summary cards, and positive market states.
- **Secondary (Exit / Warning / Alert):** `#8C1D40` (Deep crimson/wine burgundy). Highlights exhausted momentum, risk warnings, or strict exit parameters.
- **Tertiary (Neutral Observation / Grounded):** `#363F47` (Slate charcoal). Serves base preparatory stages, waiting states, and dark status headers.

### Semantic Badges & Data Chips
- **Theme Tags (Pastel Violet):** Background `#EDE9FE`, Border `#DDD6FE`, Text `#6D28D9`.
- **Favorable Growth (Pastel Mint):** Background `#DCFCE7`, Border `#BBF7D0`, Text `#15803D`.
- **Risk & Alert (Pastel Crimson):** Background `#FEE2E2`, Border `#FECACA`, Text `#B91C1C`.
- **Neutral Indicator (Muted Slate):** Background `#F1F5F9`, Border `#E2E8F0`, Text `#475569`.

### Typography Neutrals
- **Text Strong (Titles, Primary Metrics):** `#1E242B`
- **Text Body (Standard table data, active tabs):** `#333333`
- **Text Muted (Subtext, labels, timestamps):** `#71787E`
- **Border / Divider:** `#E5E2D9`

## Typography

The type system prioritizes high-density numerical scanability and pristine dual-script harmony across Latin numerals and CJK characters (pairing cleanly with PingFang SC / Noto Sans SC in runtime).

### Typographic Principles
- **Tabular Figures (`tnum`):** All financial tickers, quant scores, volume counts, and timestamps enforce proportional monospace behavior to prevent horizontal jitter across table updates.
- **Metric Anchor Units:** Numerical magnitudes (e.g., `537`, `4918`) sit in bold heavyweight styles immediately flanked by lighter, smaller Chinese quantification glyphs (`只`, `分`, `亿`).
- **Hierarchy Stacking:** Table cells use dual-tier vertical stacking: primary entity/metric bolded on top with subsidiary contextual badges nested below.

## Layout & Spacing

The layout is built for expansive, continuous horizontal workspaces typical of trading terminals and multi-column equity tables.

### Structural Flow
- **Shell Structure:** Top fixed global navigation bar (height: 52px) on warm canvas, followed by an operational secondary breadcrumb/tab utility rail, an executive triage metric bar (3-column summary cards), an actionable inline filter bar, and finally the comprehensive data grid.
- **Grid Strategy:** 
  - Metric Header Cards: 3-column equal-split grid (`grid-cols-3`) with a 16px (`1rem`) gap.
  - Data Workspace: 100% fluid full-width table container with explicit horizontal overflow protection and auto-docked operational columns on the far right.
- **Rhythm & Density:** Standard UI paddings are compact (8px to 12px) to optimize above-the-fold visible record counts while maintaining breathable cell isolation via deliberate vertical dividers and subtle background cards.

## Elevation & Depth

This system avoids heavy drop shadows and exaggerated glass blurs in favor of **low-contrast outline separation** and **subtle surface stacking**.

### Depth Layers
- **Ground Zero (Canvas):** Tone `#F4F2EC`. Represents the universal workspace backplane.
- **Level 1 (Data Cards & Worksheets):** Solid `#FFFFFF` surfaces with a 1px solid hairline border in `#E5E2D9`. Shadows are strictly ambient or omitted: `0 1px 2px 0 rgba(0, 0, 0, 0.03)`.
- **Level 2 (Pill Filters & Interactive Popovers):** Pure white floating controls bounded by `#D5D1C6`, featuring an ultra-soft resting shadow: `0 2px 6px -1px rgba(50, 45, 35, 0.06)`.
- **Level 3 (Modal Analysis & Tooltips):** Sharp micro-elevations with `0 8px 16px -4px rgba(0, 0, 0, 0.08)`.

### Highlighted State Depth
Metric cards in dominant shades (Charcoal `#363F47`, Sage `#436C53`, Crimson `#8C1D40`) use solid color fields without gradients, using 15% opacity white badge fills for internal tags to achieve clear internal hierarchy.

## Shapes

The design uses a **moderate rounded** visual language (`border-radius: 8px to 10px`) paired with **pill-shaped chips** for interactive tags, delivering a modern software experience that softens high-stress trading data.

### Corner Radius Standards
- **Containers & Big Cards:** 8px to 10px (`rounded-lg`).
- **Standard Action Buttons & Input Fields:** 6px to 8px (`rounded-md`).
- **Filter Pills, Navigation Tab Indicators & Status Chips:** 9999px (`rounded-full`).
- **Mini Badges & Sub-tags:** 4px (`rounded-sm`).

## Components

### 1. Navigation & System Bar
- **Global Header:** Warm background `#F4F2EC`. Left side contains the brand mark and bold label. Center-left holds main navigation items.
- **Nav Tabs:** Unselected tabs display `#333333` on hover with transparent backgrounds. Selected tab features a solid `#436C53` pill with crisp white text.
- **Top Utility Icons:** Circular icon buttons with white backgrounds and `#E5E2D9` hairline borders.

### 2. Category / Metric Header Cards
- **Architecture:** 3 primary hero metric cards representing system pipeline states (e.g., Base Preparation, Strong Momentum Window, Wave Completed/Exit).
- **Structure:** 
  - Top row: Stage icon + Stage name (left), pill badge indicator with 15% white fill (right).
  - Center: Tabular hero metric (e.g., `537`) with adjacent small Chinese unit label (`只`).
  - Bottom: Subtitle explanatory caption in muted white/tinted text.
- **Colorways:**
  - Charcoal Slate: Background `#363F47`, border none, text white.
  - Sage Momentum: Background `#436C53`, border none, text white.
  - Crimson Alert: Background `#8C1D40`, border none, text white.

### 3. Filter Controls & Search Bar
- **Search Input:** White field with search icon prefix, muted placeholder, and compact height (34px-36px).
- **Tabbed Pill Groups:** Enclosed segmented controls where unselected segments are transparent and active segments are solid dark slate `#363F47` with inverted white text.
- **Color Accent Filters:** Specialized filter pills with subtle colored borders and text indicating category counts (e.g., green for positive, red for alert).

### 4. Data Tables
- **Table Card Wrapper:** Clean `#FFFFFF` background, 10px border radius, hairline `#E5E2D9` perimeter border.
- **Header Row:** Flat, borderless warm beige-tinted or pure white header with medium gray text (`#71787E`), uppercase/13px regular.
- **Row Styling:** Hover state provides a subtle warm tint (`#FAF9F6`). Row heights are compact (48px-56px).
- **Categorical Badges:** Clustered horizontal pills (`gap-1.5`) featuring soft pastel fills (e.g., lavender `#EDE9FE` with deep violet text `#6D28D9`).
- **Action Buttons in Grid:** White background with subtle green or purple hairline borders and tinted icons (e.g., AI pool analysis, individual stock data exports).