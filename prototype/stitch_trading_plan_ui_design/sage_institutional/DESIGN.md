---
name: Sage Institutional
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#404943'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#707973'
  outline-variant: '#bfc9c1'
  surface-tint: '#2c694e'
  primary: '#0f5238'
  on-primary: '#ffffff'
  primary-container: '#2d6a4f'
  on-primary-container: '#a8e7c5'
  inverse-primary: '#95d4b3'
  secondary: '#116c4a'
  on-secondary: '#ffffff'
  secondary-container: '#a1f4c8'
  on-secondary-container: '#1b724f'
  tertiary: '#713638'
  on-tertiary: '#ffffff'
  tertiary-container: '#8d4d4e'
  on-tertiary-container: '#ffcfce'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#b1f0ce'
  primary-fixed-dim: '#95d4b3'
  on-primary-fixed: '#002114'
  on-primary-fixed-variant: '#0e5138'
  secondary-fixed: '#a1f4c8'
  secondary-fixed-dim: '#86d7ad'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#ffdad9'
  tertiary-fixed-dim: '#ffb3b3'
  on-tertiary-fixed: '#390b0e'
  on-tertiary-fixed-variant: '#6f3537'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
  background-cream: '#f8f9fa'
  text-slate-deep: '#1b262c'
  text-slate-muted: '#52616b'
  semantic-negative: '#ae2012'
  semantic-positive: '#2d6a4f'
  semantic-warning: '#e67e22'
  real-account-badge: '#9b2226'
  border-subtle: '#dee2e6'
  k-line-red: '#ef5350'
  k-line-green: '#26a69a'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  mono-data:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  container-margin: 24px
  gutter: 16px
---

## Brand & Style

The design system is engineered for the high-stakes environment of institutional trading and risk management. The brand personality is **Professional, Methodical, and Authoritative**, striking a balance between modern fintech aesthetics and the rigorous reliability required for financial decision-making.

The visual style is a hybrid of **Modern Corporate** and **Minimalism**. It prioritizes information density without sacrificing clarity, using a "Quiet UI" approach that allows data—not the interface—to take center stage. Key characteristics include:

- **Refined Data Density:** Using intentional whitespace and subtle borders to manage complex trading tables and multi-step plan forms.
- **Sophisticated Warmth:** Moving away from sterile "cold" financial blues toward a more organic, grounded sage and cream palette, inspired by classic research journals.
- **Tactile Clarity:** Utilizing soft rounded corners (12px+) and depth-based layering to make the interface feel modern and approachable, reducing the cognitive load associated with high-risk trading.

## Colors

The palette is anchored by a deep **Sage Green** that signifies growth and stability. Unlike traditional financial apps, this system uses a warm **Cream** background to reduce eye strain during long trading sessions.

- **Primary & Success:** The Sage Green (#2d6a4f) serves as the primary brand color and the indicator for positive metrics/success.
- **Negative & Risk:** A distinct, high-contrast Red (#ae2012) is reserved for risk alerts, price decreases, and blocking errors.
- **Surface Strategy:** Use `background-cream` for the main canvas. Use white (#FFFFFF) for card surfaces to create a clear "lifted" hierarchy.
- **Real-Account Identity:** Transactions involving real capital must be flagged with `real-account-badge` to prevent accidental execution.

## Typography

This design system utilizes **Inter** for its exceptional legibility in data-heavy contexts and its neutral, professional tone. 

- **Numerical Data:** For prices, quantities, and tickers in tables, use a monospaced variant or `JetBrains Mono` to ensure digits align vertically, aiding quick comparison.
- **Hierarchy:** Use `headline-md` for card titles and `label-md` (uppercase) for table headers.
- **Mobile Considerations:** On smaller screens, `headline-lg` should scale to 20px to maintain layout integrity within multi-column data views.

## Layout & Spacing

The layout follows a **12-column fluid grid** for desktop, optimized for a 1440px wide viewport. It uses an 8px base rhythm with 4px increments for tight component internals.

- **The Trade Dashboard:** Utilizes a "Main-Sidebar" split (8:4 ratio). The left (8 columns) houses the K-line and primary charts; the right (4 columns) contains the execution form and risk calculation results.
- **Data Grids:** High-density tables use 8px vertical padding per row to maximize visible data points, while keeping horizontal padding at 16px for readability.
- **Breakpoints:**
  - **Desktop (1200px+):** Full 12-column view.
  - **Tablet (768px - 1199px):** Stacks the Trade Sidebar below the K-line; 8-column grid.
  - **Mobile (<767px):** Single column; 16px margins; navigation collapses into a bottom-bar or hamburger menu.

## Elevation & Depth

Visual hierarchy is managed through **Tonal Layers** and **Subtle Ambient Shadows**.

- **Level 0 (Base):** The `background-cream` surface.
- **Level 1 (Cards):** White surfaces with a very soft, 15% opacity shadow (Blur: 12px, Y: 4px). This level is used for the main data containers and K-line area.
- **Level 2 (Popovers/Modals):** Use a slightly more aggressive shadow (Blur: 20px, Y: 8px) and a 1px `border-subtle` to distinguish from the background.
- **Depth Cues:** Interactive elements like inputs use a 1px inset border on focus, rather than heavy shadows, to keep the UI feeling "flat" and precise.

## Shapes

The shape language is defined by **Soft Roundedness**.

- **Cards & Primary Containers:** 12px (rounded-lg) to 16px (rounded-xl) for large layout blocks.
- **Buttons & Inputs:** 8px (rounded-md) for a professional, yet modern look.
- **Badges & Status Indicators:** Use a full pill-shape (999px) for status indicators (e.g., "Active", "Completed") to distinguish them from interactive buttons.

## Components

### Buttons
- **Primary:** Solid `primary_color_hex` with white text. High emphasis.
- **Secondary:** Transparent background with `primary_color_hex` 1px border. Used for "Create Plan" or "Adjust Price."
- **Ghost:** No border or background. Used for utility actions like "Refresh" or "View History."
- **Danger:** Solid `semantic-negative` for "Clearance" or "Cancel All."

### Tables (Trading & Positions)
- **Header:** Sticky headers with `label-md` typography and a light grey bottom border.
- **Rows:** Alternating subtle zebra striping or highlight on hover.
- **Cells:** Numeric values are right-aligned; text labels are left-aligned. Use `semantic-positive` and `semantic-negative` for price changes.

### Input Fields
- **Pickers:** Specialized inputs for "Price Picking" from K-lines should have a "Target" icon and a distinct active state (Sage border) when the mouse is in "Picking Mode."
- **Validation:** Real-time validation for "Risk Proportions" should display "Blocking" warnings in Red and "Suggestions" in Orange.

### Cards & Status Badges
- **Trading Overview Cards:** Feature a large `mono-data` font for primary metrics (Total Assets) with a small sparkline background.
- **Account Status:** A persistent status bar in the top navigation using semantic colors for "Connected" (Green) vs "Disconnected" (Red).