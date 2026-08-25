---
name: design_assembly
description: Fetch components from curated design source websites and assemble them into projects. Use when building UIs that need animations, cursors, gradients, waves, shadows, patterns, borders, or reusable components. Always fetch before writing from scratch.
allowed-tools: design_sources design_fetch read_file file_ops
---

# Design Assembly

Fetch real components from 40+ curated design source websites, adapt them to your project, and assemble everything into a cohesive file.

## When to Use This Skill

- Building any frontend page (landing page, dashboard, portfolio, etc.)
- Need CSS animations, cursor effects, gradients, wave dividers, glassmorphism, etc.
- User asks for "fancy", "cinematic", "modern", "clean" UI
- Any task involving visual components that exist on design source sites

## The 5-Step Workflow

### Step 1: IDENTIFY — What components does this project need?

Before writing any code, list every visual component the project requires:

```
Example for a landing page:
- Hero section with gradient background
- Wave divider between sections
- Animated cursor effect
- Glassmorphism cards
- CSS hover animations on buttons
- SVG pattern background
- Custom blob border-radius on images
```

### Step 2: FETCH — Get code from the right design source

For each component, use `design_fetch` to get real, working code:

```
design_fetch(category="gradients", query="dark purple to blue")
design_fetch(category="waves", query="wave divider")
design_fetch(category="cursors", query="rainbow trail")
design_fetch(category="shadows", query="glassmorphism card")
design_fetch(category="animations", query="fade in up")
design_fetch(category="patterns", query="dots background")
design_fetch(category="borders", query="blob shape")
design_fetch(category="components", query="toggle switch")
```

**Priority order (fastest to slowest):**
1. API sources (Grabient JSON, obfus.link MCP) — instant, structured
2. GitHub/npm sources (UIverse, cursor-effects) — reliable, flat files
3. DOM scraping (Animista, Haikei) — works but slower

**Best source per category:**
- Cursors: `90s Cursor Effects` (npm, MIT license, clean JS)
- Animations: `Animista` (662+ animations, tweakable)
- Components: `UIverse` (3800+ elements, GitHub mirror, MIT)
- Gradients: `Grabient` (JSON API, 867 palettes, no auth needed)
- Waves: `FWD Tools` (SVG/CSS/React export, 4 edges)
- Shadows: `obfus.link` (MCP server, glassmorphism/neumorphism/aurora)
- Patterns: `Hero Patterns` (SVG patterns, Steve Schoger)
- Borders: `Fancy Border Radius` (8-value syntax, blob shapes)

### Step 3: ADAPT — Match the project's theme

After fetching, adapt the code to the project:

1. **Color matching** — Replace the source's default colors with the project's color palette
2. **Naming** — Rename CSS classes to match the project's naming convention
3. **Integration** — Make sure the component fits the existing HTML structure
4. **Dependencies** — Check if the fetched code needs external libraries
5. **Cleanup** — Remove any comments, debugging code, or unnecessary markup

### Step 4: ASSEMBLE — Combine into a coherent file

Build the complete HTML/CSS/JS file:

1. Start with the HTML structure (semantic, accessible)
2. Add CSS custom properties (project colors, fonts, spacing)
3. Insert fetched CSS components (adapted to project theme)
4. Add fetched JavaScript effects
5. Make sure everything works together (no conflicts)

### Step 5: VERIFY — Test that everything works

1. Open the file in a browser
2. Check all animations work
3. Check responsive design (mobile, tablet, desktop)
4. Check accessibility (keyboard nav, focus states, contrast)
5. Check performance (no jank, smooth animations)

## Design Source Categories

### Cursors
Sites: csscursors.colorion.co, cursorx.felixau.in, tholman.com/cursor-effects, tgomilar/mouse-animations, cursor-orb
Best: `90s Cursor Effects` — npm package, 3988 stars, MIT license

### Animations
Sites: animista.net, keyframepad.com, genanimate.com, animxyz.com, ianlunn/Hover
Best: `Animista` — 662+ animations, tweak easing/delay/duration

### Components
Sites: uiverse.io, codepen.io, 21st.dev, reui.io, uinest.in
Best: `UIverse` — 3800+ elements, GitHub galaxy repo, MIT license

### Gradients
Sites: grabient.com, anygradient.com, cssgradient.io, colorzilla.com, cssgenie.com
Best: `Grabient` — JSON API, 867 palettes, seed-addressable URLs

### Waves/Shapes
Sites: haikei.app, fwdtools.com, geratools.com, boxtool.app
Best: `FWD Tools` — SVG/CSS/React export, 4 edges, 18 presets

### Shadows/Effects
Sites: obfus.link, neumorphism.io, jkit.tools, design.dev
Best: `obfus.link` — MCP server, glassmorphism/neumorphism/aurora/noise/mesh-gradient

### Patterns
Sites: heropatterns.com, magicpattern.design, pattern.monster, svgbackgrounds.com
Best: `Hero Patterns` — Steve Schoger's classic SVG patterns

### Borders
Sites: 9elements.github.io/fancy-border-radius, clippy, fwdtools.com, frontendgeek.com
Best: `Fancy Border Radius` — 8-value syntax, blob shapes

## Quick Reference

### Available Tools
- `design_sources` — List all available design sources by category
- `design_fetch` — Extract CSS/HTML/JS code from a design source

### Tool Usage
```
# List all sources for a category
design_sources(category="gradients")

# List sources by extraction method
design_sources(method="api")

# Fetch code from the best source for a category
design_fetch(category="gradients", query="sunset colors")

# Fetch from a specific source
design_fetch(category="components", source_name="UIverse", query="toggle switch")

# Fetch in a specific format
design_fetch(category="animations", query="fade in", format="css")
```

## Example: Building a Landing Page

### 1. Identify components needed
```
- Gradient hero background (dark purple to blue)
- Wave divider after hero
- Animated cursor trail
- Glassmorphism feature cards
- Fade-in animations on scroll
- Dot pattern background
```

### 2. Fetch each component
```
design_fetch(category="gradients", query="dark purple to blue")
design_fetch(category="waves", query="wave divider")
design_fetch(category="cursors", query="rainbow trail")
design_fetch(category="shadows", query="glassmorphism")
design_fetch(category="animations", query="fade in up")
design_fetch(category="patterns", query="dots")
```

### 3. Adapt colors to project theme
Replace source colors with project colors:
```css
/* Source: linear-gradient(135deg, #667eea, #764ba2) */
/* Adapted: */
background: linear-gradient(135deg, var(--primary), var(--secondary));
```

### 4. Assemble into the file
Combine HTML structure + adapted CSS + adapted JS.

### 5. Verify
Open in browser, test responsive, test accessibility, test performance.

## Anti-Patterns (Don't Do This)

1. **Don't write from scratch when a source exists** — Always fetch first
2. **Don't skip adaptation** — Raw fetched code rarely matches your theme
3. **Don't dump all fetched code into one file** — Organize it properly
4. **Don't skip verification** — Always test in a browser
5. **Don't use incompatible licenses** — Check license before using in commercial projects

## License Awareness

Most design source sites offer MIT or CC0 licenses. Always check:
- UIverse: MIT
- cursor-effects: MIT
- Animista: MIT
- Grabient: Free to use
- Hero Patterns: CC BY 4.0
- obfus.link: Free to use

## Performance Tips

1. **Use CSS transforms** for animations (GPU-accelerated)
2. **Use requestAnimationFrame** for JS animations
3. **Throttle scroll handlers** (max 60fps)
4. **Use CSS custom properties** for colors (easy theming)
5. **Minimize DOM queries** (cache selectors)
6. **Use will-change** for animated elements
7. **Prefer CSS animations over JS** when possible

## Emoji Policy

- NEVER use emojis in generated code files (HTML, CSS, JS, etc.)
- NEVER use emojis in source code comments
- NEVER use emojis in file names
- Use text labels, SVG icons, or CSS content instead
