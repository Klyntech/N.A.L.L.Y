---
name: design
description: Design decisions: tokens, typography, color, spacing, components, accessibility, responsive design, pattern libraries. Use when designing interfaces, reviewing UI, building design systems, or making visual/UX choices.
allowed-tools: read_file file_ops
---

**IMPORTANT:** Only use this skill when the user is explicitly asking you to CREATE or IMPROVE a frontend page or design system. If the user is asking a QUESTION about a project (pricing, timeline, tech stack), ANSWER THE QUESTION — don't start building anything.

# Design

Unified skill for UI/UX design, design tokens, component libraries, and pattern documentation.

## Phase 1: Understand the Context

- **Who** is the user? (developer, customer, admin)
- **What** are they trying to accomplish?
- **Where** are they? (mobile, desktop, tablet)
- **When** do they use it? (quick glance, deep work, on-the-go)
- **Existing system?** Is there a design system already? What's its condition?

## Phase 2: Design Tokens

Design decisions stored as CSS variables, not hardcoded values.

```css
:root {
  /* Colors — Primary */
  --color-primary-50:  #EEF2FF;
  --color-primary-100: #E0E7FF;
  --color-primary-200: #C7D2FE;
  --color-primary-500: #6366F1;
  --color-primary-600: #4F46E5;
  --color-primary-700: #4338CA;

  /* Colors — Semantic */
  --color-success: #10B981;
  --color-warning: #F59E0B;
  --color-error:   #EF4444;
  --color-info:    #3B82F6;

  /* Colors — Neutral */
  --color-gray-50:  #F9FAFB;
  --color-gray-100: #F3F4F6;
  --color-gray-200: #E5E7EB;
  --color-gray-500: #6B7280;
  --color-gray-900: #111827;

  /* Typography */
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
  --text-xs:   0.75rem;   /* 12px */
  --text-sm:   0.875rem;  /* 14px */
  --text-base: 1rem;      /* 16px */
  --text-lg:   1.125rem;  /* 18px */
  --text-xl:   1.25rem;   /* 20px */
  --text-2xl:  1.5rem;    /* 24px */
  --text-3xl:  1.875rem;  /* 30px */
  --text-4xl:  2.25rem;   /* 36px */

  /* Spacing (8px base) */
  --space-1:  0.25rem;  /* 4px */
  --space-2:  0.5rem;   /* 8px */
  --space-3:  0.75rem;  /* 12px */
  --space-4:  1rem;     /* 16px */
  --space-6:  1.5rem;   /* 24px */
  --space-8:  2rem;     /* 32px */
  --space-12: 3rem;     /* 48px */
  --space-16: 4rem;     /* 64px */

  /* Borders & Radii */
  --radius-sm:  0.25rem;
  --radius-md:  0.5rem;
  --radius-lg:  0.75rem;
  --radius-xl:  1rem;
  --radius-full: 9999px;

  /* Shadows */
  --shadow-sm:  0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md:  0 4px 6px rgba(0, 0, 0, 0.1);
  --shadow-lg:  0 10px 15px rgba(0, 0, 0, 0.1);
}
```

**Rule:** Tokens over hardcoded values — always.

## Phase 3: Layout & Hierarchy

### Visual Hierarchy
1. **Size** — larger = more important
2. **Color** — brighter/saturated = more attention
3. **Spacing** — more whitespace = more emphasis
4. **Position** — top-left gets read first (LTR)

### Grid System
```
Desktop:  12 columns, 8px spacing
Tablet:    8 columns, 8px spacing
Mobile:    4 columns, 8px spacing

Max content width: 1200px
Side padding: 16px (mobile), 24px (tablet), 32px (desktop)
```

### Layout Patterns
- **Single column** — mobile, reading-focused
- **Sidebar + content** — dashboards, admin panels
- **Grid** — product listings, galleries
- **Split screen** — login, comparison pages

## Phase 4: Typography

### Font Pairing
- **Sans-serif** for UI (Inter, system-ui)
- **Monospace** for code (JetBrains Mono)
- Max 2 font families per project

### Readability Rules
- Contrast ratio >= 4.5:1 (normal text), >= 3:1 (large text)
- Line length: 50-75 characters (max 80)
- Use `max-width: 65ch` for text blocks
- Left-align body text (never justify long paragraphs)
- Letter-spacing: 0 for body, slight positive for uppercase

## Phase 5: Color

### Color Rules
- Use grays for 80% of the interface
- Use color only for actions and feedback
- Never use color alone to convey meaning (add icons/text)
- Test for colorblindness (red-green is most common)

## Phase 6: Components

### Buttons
```
Primary:    filled, bold color, white text
Secondary:  outline or ghost, gray border
Tertiary:   text only, link style

Sizes:  sm (32px) / md (40px) / lg (48px)
States: Default -> Hover (darker) -> Active (darkest) -> Disabled (50% opacity)
```

### Forms
- Labels above inputs (not placeholders)
- Error messages below inputs, red text
- Required fields: asterisk (*) on label
- Input height: 40px minimum
- Focus ring: 2px primary color, 2px offset

### Cards
- Background: white, Border: 1px gray-200, Border-radius: 8px
- Padding: 16px or 24px
- Shadow: 0 1px 3px rgba(0,0,0,0.1)
- Hover: subtle shadow increase or border color change

### Component Checklist
- [ ] Renders correctly at all sizes
- [ ] Keyboard accessible (Enter/Space to activate)
- [ ] Focus visible with clear indicator
- [ ] Loading/disabled states handled
- [ ] Error states documented
- [ ] Responsive (works on mobile)
- [ ] ARIA attributes for screen readers
- [ ] Unit tests for all props

## Phase 7: Pattern Library

**Empty State:** icon + title + description + action button
**Loading State:** skeleton screens (not spinners) for content
**Error State:** icon + title + description + retry action
**Navigation:** top nav (primary), sidebar (nested), bottom nav (mobile)

## Phase 8: Accessibility (WCAG 2.1)

- **Color contrast**: 4.5:1 for text, 3:1 for large text
- **Keyboard navigation**: all interactive elements reachable via Tab
- **Focus visible**: clear `:focus-visible` style on every interactive element
- **Alt text**: all images have descriptive alt (or `aria-hidden="true"` for decorative)
- **ARIA labels**: icons and interactive elements without visible text
- **Tab order**: logical, follows visual flow
- **Skip link**: "Skip to main content" for keyboard users
- Cards that look clickable are `<button>`/`<a>` or have `tabindex="0"`
- No information conveyed by color alone (add icons/text)

### Focus States Pattern
```css
/* outline + offset (zero layout shift) */
.btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
/* box-shadow for cards/links */
.nav-link:focus-visible { box-shadow: 0 0 0 2px var(--accent); }
```
**Do:** `outline` or `box-shadow` (zero layout shift). **Don't:** `border` (causes shift).

### SVG Accessibility
Decorative icons: `aria-hidden="true"`. Meaningful SVGs: `role="img"` + `<title>`.

## Phase 9: Responsive Design

### Breakpoints (mobile-first)
```css
@media (min-width: 640px)  { /* tablet */  }
@media (min-width: 768px)  { /* desktop */ }
@media (min-width: 1024px) { /* large */   }
```

### Mobile Rules
- Touch targets >= 44px x 44px
- No hover-only interactions
- Stack layout vertically
- Bottom navigation for primary actions

## Performance Checklist
- [ ] `transition` specifies exact properties (never `transition: all`)
- [ ] Scroll/mouse handlers throttled with `requestAnimationFrame`
- [ ] DOM queries cached (not re-queried on every event)
- [ ] No `overflow-x: hidden` on `<body>` (breaks iOS)
- [ ] Mobile uses `100dvh` not `100vh` (browser chrome)
- [ ] Hover effects use `box-shadow` or `outline` (not `border`)
- [ ] Animations use `transform` and `opacity` only (GPU-accelerated)

## Common Pitfalls

1. **CSS/JS Agreement** — every CSS selector must have a matching element in HTML or JS that creates it
2. **Browser Compat** — use `rgba()` not 8-digit hex; provide fallbacks for `100dvh`
3. **XSS/Security** — never build inline handlers with string interpolation; use `addEventListener` + `textContent`
4. **Dynamic Content** — never hardcode chart data in HTML; generate from JS data arrays
5. **Form State** — save drafts to `localStorage` so users don't lose progress
6. **Mobile/Safari** — `overflow-x: hidden` on body breaks rubber-banding; `100vh` includes URL bar

## Project Structure
- Directories: `css/`, `js/`, `images/` — never flat files in root
- CSS architecture: tokens.css, base.css, components.css, themes.css
- Every project needs a config file as single source of truth
- Include: README.md, semantic HTML (header/main/footer/nav), skip-to-content link
- Use data-* attributes for JS wiring, not inline event handlers

## Emoji Policy
- NEVER use emojis in generated code files, source comments, or file names
- Use text labels, SVG icons, or CSS content instead

## Guidelines
- Design for the user's goal, not your feature list
- Consistency beats novelty — reuse patterns
- Components should be composable, not monolithic
- Document WHY, not just WHAT
- Test with real content, not lorem ipsum
- Accessibility is not optional — it's a requirement
