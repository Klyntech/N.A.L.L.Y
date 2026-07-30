---
name: ui-design
description: UI/UX design decisions: layout, typography, color, spacing, accessibility, responsive design, user flows, wireframes. Use when designing interfaces, reviewing UI, or making design choices.
allowed-tools: read_file
---

# UI Design

Design principles, layout, color, typography, and accessibility.

## Phase 1: Understand the Context

- **Who** is the user? (developer, customer, admin)
- **What** are they trying to accomplish?
- **Where** are they? (mobile, desktop, tablet)
- **When** do they use it? (quick glance, deep work, on-the-go)

## Phase 2: Layout & Hierarchy

### Visual Hierarchy Rules
1. **Size** — larger = more important
2. **Color** — brighter/saturated = more attention
3. **Spacing** — more whitespace = more emphasis
4. **Position** — top-left gets read first (LTR languages)

### Grid System
```
Desktop:  12 columns, 8px spacing
Tablet:    8 columns, 8px spacing
Mobile:    4 columns, 8px spacing

Max content width: 1200px
Side padding: 16px (mobile), 24px (tablet), 32px (desktop)
```

### Spacing Scale (8px base)
```
4px   — tight (inline elements)
8px   — default (between related items)
16px  — section gap
24px  — between sections
32px  — major sections
48px  — page margins
64px  — hero sections
```

### Layout Patterns
- **Single column** — mobile, reading-focused
- **Sidebar + content** — dashboards, admin panels
- **Grid** — product listings, galleries
- **Split screen** — login, comparison pages

## Phase 3: Typography

### Font Pairing
- **Sans-serif** for UI (Inter, system-ui, sans-serif)
- **Monospace** for code (JetBrains Mono, monospace)
- Max 2 font families per project

### Type Scale
```
xs:    12px / 1.5  — captions, labels
sm:    14px / 1.5  — secondary text
base:  16px / 1.5  — body text
lg:    18px / 1.5  — lead paragraphs
xl:    20px / 1.3  — subheadings
2xl:   24px / 1.3  — section titles
3xl:   30px / 1.2  — page titles
4xl:   36px / 1.1  — hero headlines
```

### Line Length
- **Optimal**: 50-75 characters per line
- **Maximum**: 80 characters
- Use `max-width: 65ch` for text blocks

### Readability Rules
- Contrast ratio ≥ 4.5:1 (normal text), ≥ 3:1 (large text)
- Don't center long paragraphs
- Left-align body text (never justify)
- Letter-spacing: 0 for body, slight positive for uppercase

## Phase 4: Color

### Color System
```
Primary:    #2563EB (blue-600)   — CTAs, links, active states
Secondary:  #6B7280 (gray-500)   — secondary actions
Success:    #10B981 (green-500)  — positive feedback
Warning:    #F59E0B (amber-500)  — caution
Error:      #EF4444 (red-500)    — errors, destructive
Info:       #3B82F6 (blue-500)   — informational

Gray scale:
  50:   #F9FAFB  — backgrounds
  100:  #F3F4F6  — card backgrounds
  200:  #E5E7EB  — borders
  300:  #D1D5DB  — disabled
  400:  #9CA3AF  — placeholder text
  500:  #6B7280  — secondary text
  600:  #4B5563  — primary text
  700:  #374151  — headings
  800:  #1F2937  — high contrast
  900:  #111827  — maximum contrast
```

### Color Rules
- Use grays for 80% of the interface
- Use color only for actions and feedback
- Never use color alone to convey meaning (add icons/text)
- Test for colorblindness (red-green is most common)

## Phase 5: Components

### Buttons
```
Primary:    filled, bold color, white text
Secondary:  outline or ghost, gray border
Tertiary:   text only, link style

Sizes:
  sm: 32px height, 12px font, 8px 16px padding
  md: 40px height, 14px font, 10px 20px padding
  lg: 48px height, 16px font, 12px 24px padding

States:
  Default → Hover (darker) → Active (darkest) → Disabled (50% opacity)
```

### Forms
- Labels above inputs (not placeholders)
- Error messages below inputs, red text
- Required fields: asterisk (*) on label
- Input height: 40px minimum
- Border: 1px solid gray-300
- Focus ring: 2px primary color, 2px offset

### Cards
- Background: white
- Border: 1px gray-200
- Border-radius: 8px
- Padding: 16px or 24px
- Shadow: 0 1px 3px rgba(0,0,0,0.1)
- Hover: subtle shadow increase or border color change

## Phase 6: Accessibility

### WCAG 2.1 Requirements
- **Color contrast**: 4.5:1 for text, 3:1 for large text
- **Keyboard navigation**: all interactive elements reachable
- **Focus visible**: clear focus indicator
- **Alt text**: all images have descriptive alt
- **ARIA labels**: icons, interactive elements without text
- **Tab order**: logical, follows visual flow
- **Error identification**: errors linked to form fields
- **Skip link**: "Skip to main content" for keyboard users

### Quick Audit
```html
<!-- Missing alt text -->
<img src="logo.png">              ✗
<img src="logo.png" alt="Logo">   ✓

<!-- Missing label -->
<input type="email">                        ✗
<label for="email">Email</label>            ✓
<input type="email" id="email">             ✓

<!-- No keyboard focus -->
<div onclick="submit()">Click</div>         ✗
<button onclick="submit()">Click</button>   ✓
```

## Phase 7: Responsive Design

### Breakpoints
```css
/* Mobile first */
@media (min-width: 640px)  { /* tablet */  }
@media (min-width: 768px)  { /* desktop */ }
@media (min-width: 1024px) { /* large */   }
@media (min-width: 1280px) { /* xl */      }
```

### Mobile Rules
- Touch targets ≥ 44px × 44px
- No hover-only interactions
- Stack layout vertically
- Bottom navigation for primary actions
- Pull-to-refresh for content updates

### Common Patterns
- **Hamburger menu** — hidden nav on mobile
- **Bottom sheet** — modal on mobile, dialog on desktop
- **Stacked cards** → grid on desktop
- **Full-width buttons** on mobile, auto-width on desktop

## Guidelines
- Design for the user's goal, not your feature list
- Consistency beats novelty — reuse patterns
- When in doubt, use browser defaults for forms
- Test with real users, not just yourself
