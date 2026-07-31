---
name: design-system
description: Design tokens, component libraries, style guides, pattern documentation. Use when building or maintaining a design system, creating component libraries, or documenting design patterns.
allowed-tools: read_file file_ops
---

# Design System

Build and maintain reusable design tokens, components, and patterns.

## Phase 1: Assess Current State

- Is there an existing design system? What's its condition?
- What components are used repeatedly?
- What inconsistencies exist across the app?
- What's the team size and skill level?

## Phase 2: Design Tokens

### What Are Tokens?
Design decisions stored as variables, not hardcoded values.

### Token Categories

**Colors:**
```css
:root {
  /* Primary */
  --color-primary-50:  #EEF2FF;
  --color-primary-100: #E0E7FF;
  --color-primary-200: #C7D2FE;
  --color-primary-500: #6366F1;
  --color-primary-600: #4F46E5;
  --color-primary-700: #4338CA;
  
  /* Semantic */
  --color-success: #10B981;
  --color-warning: #F59E0B;
  --color-error:   #EF4444;
  --color-info:    #3B82F6;
  
  /* Neutral */
  --color-gray-50:  #F9FAFB;
  --color-gray-100: #F3F4F6;
  --color-gray-200: #E5E7EB;
  --color-gray-500: #6B7280;
  --color-gray-900: #111827;
}
```

**Typography:**
```css
:root {
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
  
  --font-normal: 400;
  --font-medium: 500;
  --font-bold:   700;
}
```

**Spacing:**
```css
:root {
  --space-1:  0.25rem;  /* 4px */
  --space-2:  0.5rem;   /* 8px */
  --space-3:  0.75rem;  /* 12px */
  --space-4:  1rem;     /* 16px */
  --space-5:  1.25rem;  /* 20px */
  --space-6:  1.5rem;   /* 24px */
  --space-8:  2rem;     /* 32px */
  --space-10: 2.5rem;   /* 40px */
  --space-12: 3rem;     /* 48px */
  --space-16: 4rem;     /* 64px */
}
```

**Borders & Radii:**
```css
:root {
  --radius-sm:  0.25rem;  /* 4px */
  --radius-md:  0.5rem;   /* 8px */
  --radius-lg:  0.75rem;  /* 12px */
  --radius-xl:  1rem;     /* 16px */
  --radius-full: 9999px;
  
  --border-thin: 1px solid var(--color-gray-200);
  --border-thick: 2px solid var(--color-gray-200);
}
```

**Shadows:**
```css
:root {
  --shadow-sm:  0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md:  0 4px 6px rgba(0, 0, 0, 0.1);
  --shadow-lg:  0 10px 15px rgba(0, 0, 0, 0.1);
  --shadow-xl:  0 20px 25px rgba(0, 0, 0, 0.15);
}
```

## Phase 3: Component Library

### Component Structure
```
components/
├── Button/
│   ├── Button.tsx
│   ├── Button.module.css
│   ├── Button.stories.tsx  (Storybook)
│   ├── Button.test.tsx
│   └── index.ts
├── Input/
├── Card/
├── Modal/
└── index.ts  (barrel export)
```

### Component Documentation
Each component needs:
1. **Description** — what it does
2. **Props** — name, type, default, required, description
3. **Usage examples** — common patterns
4. **Do / Don't** — when to use, when not to use
5. **Accessibility** — keyboard, ARIA, focus management

### Example: Button Component
```typescript
interface ButtonProps {
  children: React.ReactNode;
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  loading?: boolean;
  onClick?: () => void;
}

// Props table:
// | Prop     | Type    | Default    | Description |
// |----------|---------|------------|-------------|
// | children | ReactNode | required | Button content |
// | variant  | string  | 'primary' | Visual style |
// | size     | string  | 'md'      | Button size |
// | disabled | boolean | false     | Disable interaction |
// | loading  | boolean | false     | Show spinner |
// | onClick  | () => void | -     | Click handler |

// Do: Use primary for main actions, secondary for alternatives
// Don't: Use more than 2 buttons side by side
// Do: Use loading state for async operations
// Don't: Disable buttons without also showing loading
```

### Component Checklist
- [ ] Renders correctly at all sizes
- [ ] Keyboard accessible (Enter/Space to activate)
- [ ] Focus visible with clear indicator
- [ ] Loading/disabled states handled
- [ ] Error states documented
- [ ] Responsive (works on mobile)
- [ ] ARIA attributes for screen readers
- [ ] Unit tests for all props
- [ ] Storybook stories for all variants

## Phase 4: Pattern Library

### Common Patterns

**Empty State:**
- Icon/illustration
- Title ("No results found")
- Description ("Try adjusting your search")
- Action button ("Clear filters")

**Loading State:**
- Skeleton screens (not spinners) for content
- Progress bar for determinate operations
- Spinner for indeterminate operations

**Error State:**
- Icon (red exclamation)
- Title ("Something went wrong")
- Description (what happened)
- Action ("Try again" or "Contact support")

**Form Pattern:**
- Labels above inputs
- Helper text below labels (optional)
- Error messages below inputs
- Required fields marked with asterisk
- Submit button on the right

**Navigation Pattern:**
- Top nav for primary actions
- Sidebar for nested navigation
- Bottom nav for mobile primary actions
- Breadcrumbs for deep hierarchies

## Phase 5: Documentation

### Style Guide Structure
1. **Design Principles** — 3-5 core beliefs
2. **Color** — palette, usage, accessibility
3. **Typography** — fonts, scale, rules
4. **Spacing** — grid, padding, margins
5. **Components** — catalog with examples
6. **Patterns** — common UI patterns
7. **Content** — voice, tone, writing style

### Maintenance
- Version the design system (semver)
- Changelog for every update
- Breaking changes clearly documented
- Migration guides for major versions
- Regular audits for inconsistencies

## Common Pitfalls (Learned from Real Projects)

### 1. CSS/JS Agreement
Every CSS selector must have a matching element in the HTML or JS that creates it.

BAD:
```css
.mp-lipstick .mp-cap { background: #1A1A1A; }
```
```js
// JS creates empty container — .mp-cap never exists
`<div class="mini-product mp-lipstick"></div>`
```

GOOD:
```css
.mp-lipstick .mp-cap { background: #1A1A1A; }
```
```js
// JS injects the children CSS expects
`<div class="mini-product mp-lipstick"><div class="mp-cap"></div><div class="mp-body"></div></div>`
```

Or use pseudo-elements (::before, ::after) instead of real children.

### 2. Performance
- NEVER use `transition: all` — specify exact properties: `transition: transform 0.3s ease, opacity 0.3s ease`
- Throttle scroll/mouse handlers with `requestAnimationFrame`
- Cache DOM queries — don't `querySelectorAll` on every event
- Use `100dvh` instead of `100vh` on mobile (includes browser chrome)
- Don't use `overflow-x: hidden` on body (breaks iOS Safari)

### 3. Accessibility
- Every interactive element needs: visible label or `aria-label`, `focus-visible` style, keyboard access
- Forms: every `<input>`, `<select>`, `<textarea>` needs a `<label>` or `aria-label` and a `name` attribute
- Don't rely on color alone for meaning — add icons or text
- Editorial/card elements that look clickable must be `<button>` or `<a>`, or have `tabindex="0"` and `role="button"`

### 4. Browser Compatibility
- Use `rgba()` for colors with alpha, never 8-digit hex (`#RRGGBBAA`)
- Don't concatenate hex after CSS variable references (`var(--x)44` is fragile)
- Provide fallbacks for newer CSS features (e.g., `100vh` fallback before `100dvh`)

### 5. XSS/Security
- Never build inline event handlers with string interpolation: `onclick="fn('${x}')"` breaks if `x` contains quotes
- Use `addEventListener` instead of inline handlers
- If using `innerHTML`, escape all dynamic values or use `textContent`
- For user-generated content, use DOM APIs (`createElement`, `textContent`) instead of template strings

### 6. Code Quality
- Use `addEventListener` in JS, not inline `onclick` in HTML
- For filtering/toggling, change `display`/`hidden` on existing elements — don't destroy and recreate the entire DOM
- Persist state in `localStorage` (cart, preferences, form drafts)
- Stack notifications vertically with offset, don't place all at same `top` position
- Use `box-shadow` or `outline` for hover borders (zero layout shift), not `border` (causes shift)

### 7. HTML Semantics
- Every form element needs `name`, `value` (on options), and a label
- Use real `<button>` for actions, `<a>` for navigation — never `<div onclick>`
- Replace placeholder content (phone numbers, links, images) before marking as complete

### 8. Mobile/Safari
- `overflow-x: hidden` on `<body>` breaks iOS rubber-banding and `position: fixed`
- `100vh` on mobile includes the URL bar — use `100dvh` with `100vh` fallback
- Touch targets must be at least 44x44px

### 9. Dynamic Charts
Never hardcode chart data in HTML. Generate chart markup from JS data arrays.

```html
<!-- BAD: static bars in HTML -->
<div class="bar" style="height: 80%"></div>
<div class="bar" style="height: 60%"></div>

<!-- GOOD: empty container, JS fills it -->
<div class="chart-bars" id="chartBars"></div>
```

```js
// Generate bars from data
const data = [320, 380, 290, 420, 350, 480];
const max = Math.max(...data);
container.innerHTML = data.map(v =>
    `<div class="bar" style="height: ${(v/max)*100}%"></div>`
).join('');

// Animate with IntersectionObserver
const observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
        if (e.isIntersecting) {
            e.target.querySelectorAll('.bar').forEach((bar, i) => {
                setTimeout(() => bar.classList.add('visible'), i * 60);
            });
            observer.unobserve(e.target);
        }
    });
}, { threshold: 0.3 });
observer.observe(container);
```

### 10. Form State Persistence
Save form drafts to localStorage so users don't lose progress on accidental navigation.

```js
// Save on input
form.querySelectorAll('input, select, textarea').forEach(el => {
    el.addEventListener('input', () => {
        localStorage.setItem(`form-${el.name}`, el.value);
    });
});

// Restore on load
window.addEventListener('DOMContentLoaded', () => {
    form.querySelectorAll('input, select, textarea').forEach(el => {
        const saved = localStorage.getItem(`form-${el.name}`);
        if (saved) el.value = saved;
    });
});

// Clear on successful submit
form.addEventListener('submit', (e) => {
    e.preventDefault();
    // ... process form
    form.querySelectorAll('input, select, textarea').forEach(el => {
        localStorage.removeItem(`form-${el.name}`);
    });
    form.reset();
});
```

## Guidelines
- Tokens over hardcoded values — always
- Components should be composable, not monolithic
- Document WHY, not just WHAT
- Test with real content, not lorem ipsum
- Accessibility is not optional — it's a requirement
