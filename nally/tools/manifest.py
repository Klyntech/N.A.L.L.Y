"""Capability manifest — generated projection of the tool registry.

The manifest answers "what capabilities exist?" as compact metadata
(names + first-line descriptions, never schemas). It is generated from
ToolRegistry at call time — never hand-maintained — so it cannot drift
from the authoritative inventory the way the old static TOOLS prompt
block did.

Turn-level callable schemas remain the job of ToolFilter.select();
the manifest and the turn set are distinct concepts sharing one source.
"""

import logging

logger = logging.getLogger("nally.manifest")

_MANIFEST_HEADER = "CAPABILITIES AVAILABLE TO NALLY"


def _first_line(description: str, limit: int = 150) -> str:
    text = (description or "").splitlines()
    line = text[0].strip() if text else ""
    if len(line) > limit:
        line = line[:limit].rsplit(" ", 1)[0] + "..."
    return line or "(no description)"


def get_capability_manifest(registry=None) -> str:
    """Build the capability manifest from the current registry state.

    Args:
        registry: ToolRegistry to project. Defaults to the global singleton.
            Pass an explicit registry in tests to avoid global state.

    Returns:
        Manifest block: header line + one "- name: description" line per
        registered tool, sorted by name. No counts (counts go stale; the
        projection is the inventory).
    """
    if registry is None:
        from .registry import registry as global_registry

        registry = global_registry
    try:
        tools = registry.tools
    except Exception as e:
        logger.debug(f"Manifest unavailable, registry unreadable: {e}")
        return ""
    if not tools:
        # Lazy safety net (same precedent as registry.execute_result):
        # the prompt may be built before startup finished loading tools.
        try:
            from .registry_builder import load_all_tools

            load_all_tools()
            tools = registry.tools
        except Exception as e:
            logger.debug(f"Manifest lazy load failed: {e}")
            return ""
    if not tools:
        return ""
    try:
        lines = [_MANIFEST_HEADER]
        for name in sorted(tools.keys()):
            tool = tools[name]
            try:
                desc = _first_line(tool.description)
            except Exception:
                desc = "(no description)"
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Manifest build failed: {e}")
        return ""
