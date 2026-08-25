"""Design Fetch Tool — Browse and extract code from curated design source websites.

Given a category (cursors, animations, components, gradients, waves, shadows, patterns, borders)
and an optional search query, Nally fetches the best source and extracts CSS/HTML/JS code.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from .registry import Tool

logger = logging.getLogger("nally.tools.design_fetch")

# Re-import the registry data
try:
    from .design_sources import (
        DESIGN_SOURCES,
        get_all_categories,
        get_quick_picks,
        get_source_by_name,
        get_sources_by_category,
        get_sources_by_method,
    )
except ImportError:
    DESIGN_SOURCES = {}
    get_all_categories = lambda: []
    get_quick_picks = lambda: {}
    get_source_by_name = lambda n: None
    get_sources_by_category = lambda c: []
    get_sources_by_method = lambda m: []


# ── Extraction helpers ──────────────────────────────────

def _fetch_url_text(url: str, timeout: float = 15.0) -> str:
    """Fetch a URL and return raw text content."""
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.warning(f"Fetch failed for {url}: {e}")
        return ""


def _extract_css_from_html(html: str, selectors: str = None) -> str:
    """Extract CSS code blocks from HTML content."""
    blocks = []

    # Look for <style> tags
    style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL | re.IGNORECASE)
    blocks.extend(style_blocks)

    # Look for <code> and <pre> blocks that look like CSS
    code_blocks = re.findall(r"<(?:code|pre)[^>]*>(.*?)</(?:code|pre)>", html, re.DOTALL | re.IGNORECASE)
    for block in code_blocks:
        cleaned = re.sub(r"<[^>]+>", "", block).strip()
        if any(kw in cleaned for kw in ["{", "}", "::", "@keyframes", "animation", "background", "color:", "border", "font", "display", "position", "transition"]):
            blocks.append(cleaned)

    # Clean up HTML entities
    result = "\n\n".join(blocks)
    result = result.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    result = result.replace("&#39;", "'").replace("&quot;", '"')

    return result.strip()


def _extract_json_from_html(html: str) -> Optional[Any]:
    """Try to extract JSON data embedded in HTML."""
    # Look for <script type="application/json"> or similar
    json_blocks = re.findall(
        r'<script[^>]*type="application/(?:json|ld\+json)"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    for block in json_blocks:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue

    # Look for window.__DATA__ or similar patterns
    data_patterns = re.findall(r'window\.__\w+__\s*=\s*({.*?});', html, re.DOTALL)
    for pattern in data_patterns:
        try:
            return json.loads(pattern)
        except json.JSONDecodeError:
            continue

    return None


def _extract_svg_patterns(html: str) -> List[str]:
    """Extract SVG patterns from HTML content."""
    svgs = re.findall(r"<svg[^>]*>.*?</svg>", html, re.DOTALL | re.IGNORECASE)
    # Filter for patterns (small, repeatable)
    patterns = []
    for svg in svgs:
        if len(svg) < 10000:  # Skip huge SVGs
            # Check if it looks like a pattern (has pattern, defs, or small size)
            if "pattern" in svg.lower() or "defs" in svg.lower() or len(svg) < 5000:
                patterns.append(svg)
    return patterns


def _extract_code_blocks(html: str) -> List[Dict[str, str]]:
    """Extract labeled code blocks from HTML (e.g., CodePen format)."""
    blocks = []

    # Look for data-lang or language-class code blocks
    code_blocks = re.findall(
        r'<code[^>]*(?:data-lang="(\w+)"|class="[^"]*(?:language-|lang-)(\w+)")[^>]*>(.*?)</code>',
        html, re.DOTALL | re.IGNORECASE
    )
    for lang, _, content in code_blocks:
        lang = lang or "unknown"
        cleaned = re.sub(r"<[^>]+>", "", content).strip()
        if cleaned:
            blocks.append({"language": lang, "code": cleaned})

    return blocks


# ── Source-specific extraction ──────────────────────────

def _extract_from_grabient(seed: str = None, query: str = None) -> str:
    """Extract gradients from Grabient's JSON API."""
    import httpx

    try:
        if seed:
            url = f"https://grabient.com/{seed}.json"
            resp = httpx.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return _format_gradient(data)

        if query:
            url = f"https://grabient.com/api/search.json?query={query}&limit=3"
            resp = httpx.get(url, timeout=10)
            if resp.status_code == 200:
                results = resp.json()
                outputs = []
                for item in results[:3]:
                    outputs.append(_format_gradient(item))
                return "\n\n---\n\n".join(outputs)

        # Default: get popular gradients
        url = "https://grabient.com/api/palettes?sort=popular&limit=3"
        resp = httpx.get(url, timeout=10)
        if resp.status_code == 200:
            results = resp.json()
            outputs = []
            for item in results[:3]:
                outputs.append(_format_gradient(item))
            return "\n\n---\n\n".join(outputs)

    except Exception as e:
        logger.warning(f"Grabient extraction failed: {e}")

    return ""


def _format_gradient(data: dict) -> str:
    """Format a Grabient gradient JSON as CSS."""
    colors = data.get("colors", [])
    angle = data.get("angle", 90)
    if not colors:
        return str(data)

    stops = ", ".join(colors)
    css = f"background: linear-gradient({angle}deg, {stops});"
    return css


def _extract_from_obfus_mcp(query: str = None) -> str:
    """Try to use obfus.link MCP for effects (stub — actual MCP call goes through client)."""
    # MCP calls happen through the MCP client, not here.
    # This is a fallback for direct HTTP access.
    return ""


# ── Main extraction pipeline ────────────────────────────

def fetch_from_source(
    source: Dict[str, Any],
    query: str = None,
    format_filter: str = None,
) -> str:
    """Fetch code from a design source using the appropriate extraction method.

    Args:
        source: Source dict from the registry
        query: Optional search/filter query
        format_filter: Optional format to filter for (css, html, react, tailwind, svg)

    Returns:
        Extracted code as a string
    """
    method = source.get("extract_method", "playwright")
    url = source.get("url", "")
    name = source.get("name", "")

    logger.info(f"Fetching from {name} via {method}")

    # ── API extraction (fastest) ──
    if method == "api":
        api_endpoints = source.get("api_endpoints", {})
        if "search" in api_endpoints and query:
            search_url = api_endpoints["search"].replace("{q}", query).replace("{n}", "3")
            if not search_url.startswith("http"):
                search_url = url.rstrip("/") + search_url
            result = _fetch_url_text(search_url)
            if result:
                try:
                    data = json.loads(result)
                    return json.dumps(data, indent=2)[:5000]
                except json.JSONDecodeError:
                    return result[:5000]

        if "palette_json" in api_endpoints and query:
            seed_url = api_endpoints["palette_json"].replace("{seed}", query.replace(" ", "-"))
            if not seed_url.startswith("http"):
                seed_url = url.rstrip("/") + seed_url
            result = _fetch_url_text(seed_url)
            if result:
                try:
                    data = json.loads(result)
                    return _format_gradient(data)
                except json.JSONDecodeError:
                    pass

        # Try default list
        if "list" in api_endpoints:
            list_url = api_endpoints["list"]
            if not list_url.startswith("http"):
                list_url = url.rstrip("/") + list_url
            result = _fetch_url_text(list_url)
            if result:
                try:
                    data = json.loads(result)
                    if isinstance(data, list):
                        outputs = []
                        for item in data[:3]:
                            if isinstance(item, dict) and "colors" in item:
                                outputs.append(_format_gradient(item))
                        if outputs:
                            return "\n\n---\n\n".join(outputs)
                    return json.dumps(data, indent=2)[:5000]
                except json.JSONDecodeError:
                    pass

    # ── GitHub extraction (reliable) ──
    if method == "github":
        github_url = source.get("github", "")
        if github_url:
            # Convert GitHub URL to raw content URL
            raw_url = github_url.replace("github.com", "raw.githubusercontent.com")
            # Try to fetch README for usage examples
            readme_url = raw_url + "/main/README.md"
            result = _fetch_url_text(readme_url)
            if result:
                return result[:5000]

    # ── NPM extraction ──
    if method == "npm":
        # Try to fetch package info from npm registry
        npm_name = source.get("npm", "")
        if npm_name:
            npm_url = f"https://registry.npmjs.org/{npm_name}/latest"
            result = _fetch_url_text(npm_url)
            if result:
                try:
                    data = json.loads(result)
                    readme_url = data.get("readme", "")
                    if readme_url:
                        readme = _fetch_url_text(readme_url)
                        if readme:
                            return readme[:5000]
                except json.JSONDecodeError:
                    pass

    # ── Static/Playwright extraction (DOM scraping) ──
    if method in ("static", "playwright"):
        html = _fetch_url_text(url)
        if not html:
            return f"Error: Could not fetch content from {url}"

        code_selector = source.get("code_selector", "pre code, code")

        # Try code blocks first
        code_blocks = _extract_code_blocks(html)
        if code_blocks:
            if format_filter:
                filtered = [b for b in code_blocks if b["language"].lower() == format_filter.lower()]
                if filtered:
                    return filtered[0]["code"][:5000]
            return code_blocks[0]["code"][:5000]

        # Try CSS extraction
        css = _extract_css_from_html(html, code_selector)
        if css and len(css) > 20:
            return css[:5000]

        # Try SVG patterns
        svgs = _extract_svg_patterns(html)
        if svgs:
            return svgs[0][:5000]

        # Fall back to stripped text (truncated)
        from .fetch import _strip_html
        text = _strip_html(html)
        if text:
            return text[:3000]

    return f"Error: Could not extract code from {name}"


# ── Tool class ──────────────────────────────────────────

class DesignFetchTool(Tool):
    """Browse and extract CSS/HTML/JS code from curated design source websites.

    Categories: cursors, animations, components, gradients, waves, shadows, patterns, borders.
    Use design_sources to see all available sources, then design_fetch to extract code.
    """

    def __init__(self):
        super().__init__(
            name="design_fetch",
            description=(
                "Fetch CSS/HTML/JS code from curated design source websites. "
                "Categories: cursors, animations, components, gradients, waves, shadows, patterns, borders. "
                "Use design_sources first to see available sources, then use this tool to extract code. "
                "Always fetch from a design source before writing components from scratch."
            ),
            permission="safe",
            parameters={
                "category": {
                    "type": "string",
                    "description": "Design category: cursors, animations, components, gradients, waves, shadows, patterns, borders",
                    "required": True,
                },
                "query": {
                    "type": "string",
                    "description": "What you're looking for (e.g., 'hover effect', 'dark gradient', 'loading spinner')",
                },
                "source_name": {
                    "type": "string",
                    "description": "Specific source name to fetch from (e.g., 'Grabient', 'UIverse'). If empty, picks the best source.",
                },
                "format": {
                    "type": "string",
                    "description": "Preferred code format: css, html, react, tailwind, svg, javascript",
                    "enum": ["css", "html", "react", "tailwind", "svg", "javascript"],
                },
            },
        )

    def execute(self, category: str, query: str = "", source_name: str = "", format: str = "") -> str:
        category = category.lower().strip()

        # List sources for category
        if not query and not source_name:
            sources = get_sources_by_category(category)
            if not sources:
                available = ", ".join(get_all_categories())
                return f"Unknown category '{category}'. Available: {available}"

            lines = [f"=== {category.upper()} SOURCES ==="]
            for s in sources:
                method = s["extract_method"]
                formats = ", ".join(s["code_formats"])
                lines.append(f"- {s['name']}: {s['description']} ({method}, {formats})")
            lines.append("")
            lines.append("Use design_fetch with a query to extract code from one of these sources.")
            return "\n".join(lines)

        # Find the source
        source = None
        if source_name:
            source = get_source_by_name(source_name)
            if not source:
                return f"Source '{source_name}' not found. Use design_sources to see available sources."
        else:
            # Pick best source for category
            sources = get_sources_by_category(category)
            if not sources:
                available = ", ".join(get_all_categories())
                return f"Unknown category '{category}'. Available: {available}"
            # Prefer high-reliability sources
            reliability_order = {"very high": 0, "high": 1, "medium": 2, "low": 3}
            sorted_sources = sorted(
                sources,
                key=lambda s: reliability_order.get(s.get("reliability", "medium"), 2)
            )
            source = sorted_sources[0]

        # Fetch and extract
        try:
            result = fetch_from_source(source, query=query, format_filter=format)
            if not result or result.startswith("Error:"):
                return result or f"Error: Could not extract code from {source['name']}"

            # Add source attribution
            header = f"Source: {source['name']} ({source['url']})\n"
            if source.get("highlights"):
                header += f"Note: {source['highlights']}\n"
            header += "---\n\n"

            return header + result

        except Exception as e:
            logger.error(f"Design fetch failed: {e}")
            return f"Error fetching from {source['name']}: {type(e).__name__}: {e}"


class DesignSourcesTool(Tool):
    """List all available design sources by category."""

    def __init__(self):
        super().__init__(
            name="design_sources",
            description=(
                "List all available design source websites by category. "
                "Use this first to find the right source, then use design_fetch to extract code."
            ),
            permission="safe",
            parameters={
                "category": {
                    "type": "string",
                    "description": "Filter by category (optional). Empty = show all.",
                    "enum": ["cursors", "animations", "components", "gradients", "waves", "shadows", "patterns", "borders"],
                },
                "method": {
                    "type": "string",
                    "description": "Filter by extraction method (optional). Empty = show all.",
                    "enum": ["api", "mcp", "github", "npm", "playwright", "static"],
                },
            },
        )

    def execute(self, category: str = "", method: str = "") -> str:
        if category:
            sources = get_sources_by_category(category.lower())
            if not sources:
                available = ", ".join(get_all_categories())
                return f"Unknown category '{category}'. Available: {available}"
        elif method:
            sources = get_sources_by_method(method.lower())
        else:
            sources = []
            for cat_sources in DESIGN_SOURCES.values():
                sources.extend(cat_sources)

        if not sources:
            return "No sources found matching your criteria."

        lines = [f"=== DESIGN SOURCE LIBRARY ({len(sources)} sources) ==="]

        if not category and not method:
            # Group by category
            for cat, cat_sources in DESIGN_SOURCES.items():
                lines.append(f"\n[{cat.upper()}]")
                for s in cat_sources:
                    method_str = s["extract_method"]
                    formats = ", ".join(s["code_formats"])
                    reliability = s.get("reliability", "?")
                    lines.append(f"  {s['name']}: {s['description']}")
                    lines.append(f"    URL: {s['url']}")
                    lines.append(f"    Method: {method_str} | Formats: {formats} | Reliability: {reliability}")
        else:
            for s in sources:
                method_str = s["extract_method"]
                formats = ", ".join(s["code_formats"])
                reliability = s.get("reliability", "?")
                lines.append(f"\n{s['name']}: {s['description']}")
                lines.append(f"  URL: {s['url']}")
                lines.append(f"  Method: {method_str} | Formats: {formats} | Reliability: {reliability}")
                if s.get("highlights"):
                    lines.append(f"  Highlights: {s['highlights']}")

        lines.append(f"\nUse design_fetch to extract code from any source.")
        return "\n".join(lines)
