"""Design Source Registry — Curated list of websites for CSS/HTML/JS code.

Nally uses this registry to browse, fetch, and assemble components from
design source websites. Each entry includes extraction metadata so the
fetcher knows how to pull code programmatically.

Categories: cursors, animations, components, gradients, waves, shadows, patterns, borders
"""

from typing import Any, Dict, List, Optional

# ── Extraction methods ──────────────────────────────────
# api       — Site has a JSON/REST API (fastest, most reliable)
# mcp       — Site has an MCP server for direct tool calls
# github    — Code is in a GitHub repo (reliable, flat files)
# npm       — Package available via npm (install and import)
# playwright — Need browser automation to extract from DOM
# static    — Simple static pages, easy DOM scraping
# redirect  — Site redirects to another URL

DESIGN_SOURCES: Dict[str, List[Dict[str, Any]]] = {
    # ── CURSORS ──────────────────────────────────────────
    "cursors": [
        {
            "name": "CSS Cursors",
            "url": "https://csscursors.colorion.co",
            "description": "Collection of pure CSS cursor definitions using custom images/SVGs",
            "extract_method": "static",
            "code_formats": ["css"],
            "requires_interaction": False,
            "code_selector": "style, pre, code",
            "reliability": "medium",
        },
        {
            "name": "CursorX",
            "url": "https://cursorx.felixau.in",
            "github": "https://github.com/Felix-au/CursorX-Interactive-Cursor-Effects",
            "description": "24 custom cursor effects with live previews, slider customization",
            "extract_method": "playwright",
            "code_formats": ["html", "css", "javascript"],
            "requires_interaction": True,
            "code_selector": "pre code, .code-block",
            "reliability": "medium",
        },
        {
            "name": "90s Cursor Effects",
            "url": "https://tholman.com/cursor-effects/",
            "github": "https://github.com/tholman/cursor-effects",
            "npm": "cursor-effects",
            "description": "Classic 90s-style cursor effects (rainbow, emoji rain, ghost, trails). MIT license.",
            "extract_method": "github",
            "code_formats": ["javascript", "html", "css"],
            "requires_interaction": False,
            "reliability": "high",
            "highlights": "3988 stars, npm package, clean JS modules per effect",
        },
        {
            "name": "mouse-animations",
            "url": "https://tgomilar.github.io/mouse-animations/",
            "github": "https://github.com/tgomilar/mouse-animations",
            "npm": "mouse-animations",
            "description": "Trail, ripple, magnetic, particles, parallax, tilt effects. Zero deps, under 5kB.",
            "extract_method": "npm",
            "code_formats": ["typescript", "javascript"],
            "requires_interaction": False,
            "reliability": "high",
        },
        {
            "name": "cursor-orb",
            "url": "https://cursor-orb.netlify.app/",
            "github": "https://github.com/dmitry-conquer/cursor-orb",
            "npm": "cursor-orb",
            "description": "Animated cursor orb with velocity stretch, click pulse, magnetic movement",
            "extract_method": "npm",
            "code_formats": ["typescript", "javascript"],
            "requires_interaction": False,
            "reliability": "high",
        },
    ],

    # ── ANIMATIONS ───────────────────────────────────────
    "animations": [
        {
            "name": "Animista",
            "url": "https://animista.net",
            "description": "662+ CSS animations across categories (fade, scale, rotate, attention)",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "code_selector": ".code-block code, pre code",
            "reliability": "high",
            "highlights": "Tweak easing, delay, duration. Copy class name + keyframes.",
        },
        {
            "name": "KeyframePad",
            "url": "https://keyframepad.com",
            "description": "Visual timeline editor with 90+ easing presets, multi-format export",
            "extract_method": "playwright",
            "code_formats": ["css", "tailwind", "react"],
            "requires_interaction": True,
            "code_selector": ".css-output, pre code",
            "reliability": "high",
        },
        {
            "name": "GenAnimate",
            "url": "https://genanimate.com",
            "description": "40+ copy-paste CSS animations with customization",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": False,
            "code_selector": "pre code, .code-output",
            "reliability": "medium",
        },
        {
            "name": "AnimXYZ",
            "url": "https://animxyz.com",
            "npm": "vue-anime",
            "description": "Composable CSS animation toolkit. No custom keyframes needed.",
            "extract_method": "playwright",
            "code_formats": ["css", "react", "vue"],
            "requires_interaction": False,
            "code_selector": "pre code",
            "reliability": "high",
        },
        {
            "name": "Hover.css",
            "url": "https://ianlunn.github.io/Hover/",
            "github": "https://github.com/ianlunn/Hover",
            "npm": "hover.css",
            "description": "Library of CSS3 hover effects (glows, pulses, slides)",
            "extract_method": "github",
            "code_formats": ["css"],
            "requires_interaction": False,
            "reliability": "high",
        },
    ],

    # ── COMPONENTS ───────────────────────────────────────
    "components": [
        {
            "name": "UIverse",
            "url": "https://uiverse.io",
            "github": "https://github.com/uiverse-io/galaxy",
            "description": "3800+ UI elements (buttons, cards, toggles, loaders, inputs)",
            "extract_method": "github",
            "code_formats": ["html", "css", "react", "vue"],
            "requires_interaction": False,
            "reliability": "very high",
            "highlights": "Largest open-source UI library. GitHub mirror has flat HTML files. MIT license.",
            "categories": {
                "Buttons": 1231,
                "Cards": 726,
                "Loaders": 718,
                "Toggles": 260,
                "Inputs": 226,
                "Forms": 180,
                "Checkboxes": 171,
            },
        },
        {
            "name": "CodePen",
            "url": "https://codepen.io",
            "description": "Millions of user-created CSS/JS demos. oEmbed + raw code APIs.",
            "extract_method": "api",
            "api_endpoints": {
                "oembed": "https://codepen.io/api/oembed?format=json&url={pen_url}",
                "raw_css": "{pen_url}.css",
                "raw_js": "{pen_url}.js",
                "raw_html": "{pen_url}.html",
            },
            "code_formats": ["html", "css", "javascript", "react", "vue", "svelte"],
            "requires_interaction": False,
            "reliability": "very high",
        },
        {
            "name": "21st.dev",
            "url": "https://21st.dev",
            "description": "12000+ React components with AI-agent-ready prompts",
            "extract_method": "playwright",
            "code_formats": ["react", "tailwind"],
            "requires_interaction": False,
            "reliability": "high",
        },
        {
            "name": "ReUI",
            "url": "https://reui.io",
            "description": "1072 free shadcn/ui components with MCP server",
            "extract_method": "mcp",
            "mcp_url": "https://reui.io/mcp",
            "code_formats": ["react", "tailwind"],
            "requires_interaction": False,
            "reliability": "very high",
        },
        {
            "name": "Uinest",
            "url": "https://uinest.in",
            "description": "Modern UIverse alternative. React + Tailwind focus.",
            "extract_method": "playwright",
            "code_formats": ["react", "tailwind", "css"],
            "requires_interaction": False,
            "reliability": "high",
        },
    ],

    # ── GRADIENTS ────────────────────────────────────────
    "gradients": [
        {
            "name": "Grabient",
            "url": "https://grabient.com",
            "description": "867 curated gradient palettes with full JSON API",
            "extract_method": "api",
            "api_endpoints": {
                "palette_json": "/{seed}.json",
                "search": "/api/search.json?query={q}&limit={n}",
                "list": "/api/palettes?sort=popular&limit=24",
                "png": "/{seed}.png?w=1600&h=400",
            },
            "code_formats": ["css"],
            "requires_interaction": False,
            "reliability": "very high",
            "highlights": "BEST for programmatic access. Seed-addressable URLs. robots.txt welcomes AI crawlers.",
        },
        {
            "name": "AnyGradient",
            "url": "https://anygradient.com",
            "description": "One gradient exported to 10+ platforms (CSS, Tailwind, React, SwiftUI, Flutter)",
            "extract_method": "playwright",
            "code_formats": ["css", "tailwind", "react"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "ColorZilla Gradient Editor",
            "url": "https://www.colorzilla.com/gradient-editor/",
            "description": "Photoshop-like gradient editor. 135+ presets. Cross-browser output.",
            "extract_method": "playwright",
            "code_formats": ["css", "scss"],
            "requires_interaction": True,
            "reliability": "very high",
        },
        {
            "name": "CSS Gradient",
            "url": "https://cssgradient.io",
            "description": "Visual gradient builder with live preview",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "CSS Genie Gradient",
            "url": "https://cssgenie.com/gradient-generator",
            "description": "Linear + radial gradients with readability lab for WCAG contrast",
            "extract_method": "playwright",
            "code_formats": ["css", "tailwind", "svg"],
            "requires_interaction": True,
            "reliability": "high",
        },
    ],

    # ── WAVES / SHAPES ───────────────────────────────────
    "waves": [
        {
            "name": "Haikei",
            "url": "https://haikei.app",
            "description": "15+ SVG generators (waves, blobs, peaks, grids, scatter)",
            "extract_method": "playwright",
            "code_formats": ["svg", "css"],
            "requires_interaction": True,
            "reliability": "high",
            "generators": ["Blob", "Wave", "Layered Waves", "Stacked Waves", "Peaks", "Steps", "Low Poly Grid"],
        },
        {
            "name": "FWD Tools SVG Wave",
            "url": "https://fwdtools.com/svg-wave-generator/",
            "description": "Layered wave dividers. 4 edges. SVG + CSS data-URI + React export.",
            "extract_method": "playwright",
            "code_formats": ["svg", "css", "react"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "Gera Tools SVG Wave",
            "url": "https://geratools.com/svg-wave-generator",
            "description": "Up to 8 layers, SMIL animation, 3 wave shapes",
            "extract_method": "playwright",
            "code_formats": ["svg"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "BoxTool SVG Wave",
            "url": "https://boxtool.app/en/tools/svg-wave-generator/",
            "description": "5 styles, 10 presets, gradient fill, CSS data-URI export",
            "extract_method": "playwright",
            "code_formats": ["svg", "css"],
            "requires_interaction": True,
            "reliability": "high",
        },
    ],

    # ── SHADOWS / EFFECTS ────────────────────────────────
    "shadows": [
        {
            "name": "obfus.link CSS Effect Generator",
            "url": "https://obfus.link/tool/css-effect-generator",
            "description": "Glassmorphism, neumorphism, aurora, noise, mesh-gradient",
            "extract_method": "mcp",
            "mcp_url": "https://obfus.link/mcp",
            "code_formats": ["css", "tailwind", "react"],
            "requires_interaction": False,
            "reliability": "very high",
            "highlights": "BEST for programmatic access. MCP server returns CSS + Tailwind + React simultaneously.",
            "effects": ["glassmorphism", "neumorphism", "aurora", "noise", "mesh-gradient"],
        },
        {
            "name": "Neumorphism.io",
            "url": "https://neumorphism.io",
            "description": "Classic neumorphism generator. Adjust base color, distance, shadow intensity.",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "code_selector": "#result code, .output code",
            "reliability": "high",
        },
        {
            "name": "J-Kit Glassmorphism",
            "url": "https://jkit.tools/en/tools/glassmorphism-generator",
            "description": "Glassmorphism + Neumorphism in one tool. CSS + Tailwind output.",
            "extract_method": "playwright",
            "code_formats": ["css", "tailwind"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "design.dev Liquid Glass",
            "url": "https://design.dev/tools/liquid-glass-generator/",
            "description": "Ultra-realistic liquid glass. Multi-layer shadows, specular highlights.",
            "extract_method": "playwright",
            "code_formats": ["css", "tailwind"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "CSS Genie Box Shadow",
            "url": "https://cssgenie.com/box-shadow-generator",
            "description": "Multi-layer box shadows with elevation presets",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "reliability": "high",
        },
    ],

    # ── PATTERNS / BACKGROUNDS ───────────────────────────
    "patterns": [
        {
            "name": "Hero Patterns",
            "url": "https://heropatterns.com",
            "description": "Classic repeatable SVG background patterns by Steve Schoger",
            "extract_method": "static",
            "code_formats": ["svg", "css"],
            "requires_interaction": False,
            "code_selector": "pre code, .pattern-code",
            "reliability": "high",
        },
        {
            "name": "MagicPattern CSS Backgrounds",
            "url": "https://www.magicpattern.design/tools/css-backgrounds",
            "description": "50+ pure CSS background patterns (no images)",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "Pattern Monster",
            "url": "https://pattern.monster",
            "description": "SVG pattern generator with customizable patterns",
            "extract_method": "playwright",
            "code_formats": ["svg", "css"],
            "requires_interaction": True,
            "reliability": "medium",
        },
        {
            "name": "SVG Backgrounds",
            "url": "https://svgbackgrounds.com",
            "description": "Large collection of SVG background patterns with color customization",
            "extract_method": "playwright",
            "code_formats": ["svg", "css"],
            "requires_interaction": True,
            "reliability": "high",
        },
    ],

    # ── BORDERS ──────────────────────────────────────────
    "borders": [
        {
            "name": "Fancy Border Radius",
            "url": "https://9elements.github.io/fancy-border-radius/",
            "github": "https://github.com/9elements/fancy-border-radius",
            "description": "THE classic blob border-radius generator. 8-value syntax.",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "code_selector": "#output code, pre code",
            "reliability": "high",
        },
        {
            "name": "Clippy (CSS Clip-Path)",
            "url": "https://davidix.github.io/CSS-clip-path-generator/",
            "github": "https://github.com/davidix/CSS-clip-path-generator",
            "description": "Classic CSS clip-path maker. Polygon, circle, ellipse, inset.",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "FWD Tools Clip-Path",
            "url": "https://fwdtools.com/css-clip-path-generator/",
            "description": "18 presets, drag vertices, 4 shape modes",
            "extract_method": "playwright",
            "code_formats": ["css"],
            "requires_interaction": True,
            "reliability": "high",
        },
        {
            "name": "FrontendGeek Border Radius",
            "url": "https://www.frontendgeek.com/tools/css/css-border-radius-generator",
            "description": "80+ presets (blob, bubble, lens, stamp). Cross-browser CSS + Tailwind.",
            "extract_method": "playwright",
            "code_formats": ["css", "tailwind"],
            "requires_interaction": True,
            "reliability": "high",
        },
    ],
}


def get_sources_by_category(category: str) -> List[Dict[str, Any]]:
    """Get all design sources for a category."""
    return DESIGN_SOURCES.get(category, [])


def get_source_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Find a design source by name (case-insensitive)."""
    name_lower = name.lower()
    for category_sources in DESIGN_SOURCES.values():
        for source in category_sources:
            if name_lower in source["name"].lower():
                return source
    return None


def get_sources_by_method(method: str) -> List[Dict[str, Any]]:
    """Get all sources that use a specific extraction method."""
    results = []
    for category_sources in DESIGN_SOURCES.values():
        for source in category_sources:
            if source.get("extract_method") == method:
                results.append(source)
    return results


def get_all_categories() -> List[str]:
    """Get all available category names."""
    return list(DESIGN_SOURCES.keys())


def format_for_prompt() -> str:
    """Format the registry as a concise prompt for the LLM."""
    lines = ["DESIGN SOURCE LIBRARY — Available for fetching CSS/HTML/JS components:"]
    lines.append("")

    for category, sources in DESIGN_SOURCES.items():
        lines.append(f"[{category.upper()}]")
        for s in sources:
            method = s["extract_method"]
            formats = ", ".join(s["code_formats"])
            lines.append(f"  - {s['name']}: {s['description']} ({method}, {formats})")
        lines.append("")

    lines.append("Use the design_fetch tool to browse and extract code from these sources.")
    lines.append("Always fetch from the BEST source for each category before writing code from scratch.")

    return "\n".join(lines)


def get_quick_picks() -> Dict[str, str]:
    """Get the single best source per category for quick access."""
    return {
        "cursors": "90s Cursor Effects (tholman.com) — npm package, clean JS, MIT license",
        "animations": "Animista (animista.net) — 662+ animations, tweakable",
        "components": "UIverse (uiverse.io) — 3800+ elements, GitHub mirror, MIT",
        "gradients": "Grabient (grabient.com) — JSON API, 867 palettes, no auth",
        "waves": "FWD Tools (fwdtools.com) — SVG/CSS/React export, 4 edges",
        "shadows": "obfus.link — MCP server, glassmorphism/neumorphism/aurora",
        "patterns": "Hero Patterns (heropatterns.com) — SVG patterns, Steve Schoger",
        "borders": "Fancy Border Radius (9elements) — 8-value syntax, blob shapes",
    }
