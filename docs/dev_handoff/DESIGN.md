---
name: Insight Kinetic
colors:
  surface: '#1A1A2E'
  surface-dim: '#111221'
  surface-bright: '#373849'
  surface-container-lowest: '#0c0d1c'
  surface-container-low: '#191a2a'
  surface-container: '#1d1e2e'
  surface-container-high: '#282939'
  surface-container-highest: '#323344'
  on-surface: '#e1e0f6'
  on-surface-variant: '#c8c5cc'
  inverse-surface: '#e1e0f6'
  inverse-on-surface: '#2e2f40'
  outline: '#929096'
  outline-variant: '#47464c'
  surface-tint: '#c7c5d5'
  primary: '#c7c5d5'
  on-primary: '#302f3b'
  primary-container: '#0f0f1a'
  on-primary-container: '#7c7b89'
  inverse-primary: '#5e5d6b'
  secondary: '#c6bfff'
  on-secondary: '#2900a0'
  secondary-container: '#4029ba'
  on-secondary-container: '#b4abff'
  tertiary: '#d5c4ac'
  on-tertiary: '#392f1e'
  tertiary-container: '#170f03'
  on-tertiary-container: '#897a65'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e3e0f1'
  primary-fixed-dim: '#c7c5d5'
  on-primary-fixed: '#1b1a26'
  on-primary-fixed-variant: '#464552'
  secondary-fixed: '#e4dfff'
  secondary-fixed-dim: '#c6bfff'
  on-secondary-fixed: '#160066'
  on-secondary-fixed-variant: '#4029ba'
  tertiary-fixed: '#f2e0c7'
  tertiary-fixed-dim: '#d5c4ac'
  on-tertiary-fixed: '#231a0b'
  on-tertiary-fixed-variant: '#514533'
  background: '#111221'
  on-background: '#e1e0f6'
  surface-variant: '#323344'
  surface-hover: '#22223A'
  elevated: '#24243D'
  border: '#2A2A42'
  border-hover: '#3A3A5C'
  text-primary: '#E8E8F0'
  text-muted: '#5C5C70'
  status-pending: '#5C5C70'
  status-processing: '#F5A623'
  status-done: '#2ECC71'
  status-failed: '#E74C3C'
  accent-soft: rgba(108, 92, 231, 0.1)
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.6'
  card-title:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  metadata-mono:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  tab-label:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  rail-width: 56px
  sidebar-width: 400px
  gutter: 1px
  container-padding: 1.5rem
  card-gap: 0.75rem
  element-spacing-sm: 0.5rem
  element-spacing-md: 1rem
---

## Brand & Style

The design system is engineered for high-density information processing, prioritizing "signal over noise." It adopts a **Tool-like / Modern** aesthetic, heavily influenced by developer-centric and high-productivity interfaces like Linear and Readwise Reader. 

The personality is calm, professional, and utilitarian. It treats data as the primary interface element, using a strictly dark-mode environment to reduce eye strain during long research sessions. The emotional response should be one of "effortless mastery" over large volumes of content. Visual flair is suppressed in favor of structural clarity, using precise borders and systematic spacing rather than shadows or decorative gradients.

**Key Stylistic Pillars:**
- **Monochromatic Base:** A deep, near-black foundation that allows content to recede or advance through tonal shifts.
- **Strategic Accentuation:** A single violet accent used exclusively for interactivity and state-signaling.
- **Information Density:** Minimized whitespace within components to maximize visible data, balanced by generous margins between major layout containers.
- **Technical Typography:** Mixing humanist sans-serifs for readability with monospace elements for data-heavy strings (timestamps, IDs).

## Colors

The palette is anchored by `#0F0F1A`, providing a deep, low-glare canvas. The system relies on a **Tonal Layering** strategy:
- **Primary Background (`#0F0F1A`):** Used for the app shell and icon rail.
- **Surface (`#1A1A2E`):** Used for cards and secondary panels to create subtle depth without shadows.
- **Accent (`#6C5CE7`):** Reserved for active states, primary actions, and progress indicators. Use `accent-soft` (10% opacity) for background highlights on selected items.

**Status Colors:**
Used for the processing pipeline. Use at 15% opacity for backgrounds of status pills and 100% opacity for text/icons within those pills. 
- **Pending:** Muted grey.
- **Processing:** Amber (signal of active energy).
- **Done:** Success green.
- **Failed:** Error red.

## Typography

The typography system balances the warmth of **Inter** for prose with the technical precision of **JetBrains Mono** for metadata.

- **Headlines:** Use tight tracking and semi-bold weights to maintain a professional "app" feel rather than a "website" feel.
- **Section Labels:** Implement `label-caps` for all non-interactive structural headers (e.g., "DOCUMENT TAGS"). 
- **Data Strings:** Timestamps, durations, and counts must use `metadata-mono` to ensure numeric alignment and visual distinction from surrounding body text.
- **Hierarchy:** High density is achieved by keeping the base body size at 14px. Do not scale up font sizes for larger screens; maintain the tool-like compact nature.

## Layout & Spacing

This design system uses a **Fixed-Fluid Hybrid Grid**.

- **Icon Rail:** A 56px vertical strip on the far left for core navigation.
- **Left Pane (List):** Fixed width (400px). Contains the searchable video library and processing queue.
- **Right Pane (Detail):** Fluid width. Contains the multi-tab insight panels.
- **Dividers:** Use 1px borders (`#2A2A42`) instead of margins to separate major panes, mimicking a multi-pane IDE or professional reader.

**Spacing Rhythm:**
- Use a **4px base unit**.
- Major panels are separated by 0px (border-only separation), but content within those panels should respect a `container-padding` of 24px (1.5rem).
- Component-internal spacing should be tight (8px or 12px) to maintain high information density.

## Elevation & Depth

In this design system, depth is communicated through **Tonal Stepping** and **Outline Definition** rather than shadows.

- **Level 0 (Background):** `#0F0F1A` - The lowest layer.
- **Level 1 (Surface):** `#1A1A2E` - Card backgrounds and secondary panels. This creates a visible lift against the background.
- **Level 2 (Active/Hover):** `#22223A` - Used to indicate hover states.
- **Level 3 (Overlay):** `#24243D` - Modals and dropdown menus. These may use a very subtle, 10% opacity black shadow (blur 8px) just to define edges when overlapping text.

**Borders:**
Every card and pane boundary uses a crisp 1px border. This "boxed" approach reinforces the tool-like aesthetic and provides clear hit targets in a dense UI.

## Shapes

The shape language is **Soft (0.25rem)**. 

- **Cards & Inputs:** 4px (0.25rem) radius.
- **Thumbnails:** 6px radius to feel slightly softer than the containers they sit within.
- **Status Pills:** Fully rounded (pill-shaped) to distinguish them from functional buttons and cards.
- **Buttons:** 4px radius to match the tool-like, structural theme. Avoid large rounded corners which feel too consumer-oriented.

## Components

### Video Cards
The primary list unit. Must include:
- A 64x64px thumbnail with 6px rounding.
- A **Bottom Progress Bar**: When a video is in "Processing" state, a 2px tall bar of `#6C5CE7` sits at the very bottom edge of the card.
- Selected state: Background becomes `accent-soft` with a 2px solid `#6C5CE7` left border.

### Status Pills
Small, compact badges.
- **Layout:** Icon (8px) + Label (11px Uppercase).
- **Styling:** Background at 15% opacity of the status color, text at 100% opacity. No border.

### Tabs
- **Style:** Underline-only. No background fill for the tab bar.
- **Active State:** Text color `#E8E8F0` with a 2px bottom border in `#6C5CE7`.
- **Inactive State:** Text color `#9494A8`.
- **Count Badges:** Small circles to the right of the label with `#6C5CE7` background and white text.

### Insight Cards (Detail View)
- **Structure:** Index number (top-left), Timestamp (top-right, clickable), Title, Body, and Tags (bottom).
- **Timestamps:** Must be styled in `metadata-mono`. They are interactive; on hover, they should show a subtle underline.

### Input Fields
- **Search:** Background `#1A1A2E`, border `#2A2A42`. On focus, the border changes to `#6C5CE7`.
- **Chat Input:** Pinned to the bottom of the right pane. Minimalist design, single-line by default, expanding to 4 lines max.

### Buttons
- **Primary:** Background `#6C5CE7`, text white. Used sparingly for main CTAs.
- **Secondary/Ghost:** Border `#2A2A42`, text `#9494A8`. Used for "Re-process", "Export", and "Retry". On hover, background becomes `#22223A`.