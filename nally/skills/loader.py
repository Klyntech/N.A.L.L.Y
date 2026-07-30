"""Skill loader — scans skills/ directory, parses SKILL.md frontmatter, validates security."""
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nally.skills")

# Where skills live
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# ── Frontmatter parser (no external deps) ─────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from SKILL.md content.

    Returns (metadata_dict, body_text).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    raw = m.group(1)
    body = text[m.end():]

    # Minimal YAML parser for flat key-value pairs + lists
    meta = {}
    current_key = None
    current_list = None

    for line in raw.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue

        # List item (continuation)
        if line.startswith("  - ") or line.startswith("- "):
            val = line.lstrip(" -").strip()
            if current_key and current_list is not None:
                current_list.append(val)
            continue

        # Key: value
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()

            if not val:
                # Could be start of a list
                current_key = key
                current_list = []
                meta[key] = current_list
                continue

            # Quoted strings
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]

            # Booleans
            if val.lower() in ("true", "yes"):
                val = True
            elif val.lower() in ("false", "no"):
                val = False

            meta[key] = val
            current_key = key
            current_list = None
        else:
            current_key = None
            current_list = None

    return meta, body


# ── Security validation ──────────────────────────────────

_SUSPICIOUS_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now",
    r"system\s*:\s*",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
    r"<<SYS>>",
    r"<</SYS>>",
    r"DISREGARD",
    r"FORGET\s+EVERYTHING",
    r"NEW\s+INSTRUCTIONS",
    r"ACTUALLY,\s+IGNORE",
]


def validate_skill(name: str, body: str) -> list[str]:
    """Check skill content for prompt injection and security issues.

    Returns list of warning strings. Empty = clean.
    """
    warnings = []
    lower = body.lower()

    for pattern in _SUSPICIOUS_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            warnings.append(f"Potential prompt injection: {pattern[:40]}")

    # Check for suspicious URLs (data exfiltration)
    urls = re.findall(r"https?://[^\s\"'>]+", body)
    for url in urls:
        if any(sus in url.lower() for sus in ["ngrok", "webhook", "requestbin", "pipedream", "hookbin"]):
            warnings.append(f"Suspicious URL: {url[:60]}")

    # Check for env var reads
    env_reads = re.findall(r"(?:os\.environ|process\.env|getenv|ENV)\[?[\"'](\w+)", body)
    for var in env_reads:
        if any(s in var.upper() for s in ["SECRET", "KEY", "TOKEN", "PASSWORD", "CRED"]):
            warnings.append(f"Reads sensitive env var: {var}")

    return warnings


# ── Skill loading ────────────────────────────────────────

class Skill:
    """Represents a loaded skill with metadata and body."""

    def __init__(self, name: str, description: str, body: str,
                 allowed_tools: list[str], source_path: Path):
        self.name = name
        self.description = description
        self.body = body
        self.allowed_tools = allowed_tools
        self.source_path = source_path
        self.warnings: list[str] = []

    def __repr__(self):
        return f"Skill({self.name!r})"


def load_skill(skill_dir: Path) -> Optional[Skill]:
    """Load a single skill from a directory containing SKILL.md."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        logger.warning(f"No SKILL.md in {skill_dir.name}")
        return None

    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read {skill_md}: {e}")
        return None

    meta, body = _parse_frontmatter(content)

    name = meta.get("name", skill_dir.name)
    description = meta.get("description", "")
    allowed_tools_raw = meta.get("allowed-tools", "")
    allowed_tools = allowed_tools_raw.split() if isinstance(allowed_tools_raw, str) else []

    # Validate name matches directory
    if name != skill_dir.name:
        logger.warning(f"Skill name '{name}' doesn't match directory '{skill_dir.name}'")

    # Security check
    warnings = validate_skill(name, body)
    if warnings:
        for w in warnings:
            logger.warning(f"Skill '{name}': {w}")

    skill = Skill(
        name=name,
        description=description,
        body=body,
        allowed_tools=allowed_tools,
        source_path=skill_md,
    )
    skill.warnings = warnings

    return skill


def load_skills(skills_dir: Optional[Path] = None) -> dict[str, Skill]:
    """Scan skills directory and return dict of name -> Skill.

    This is Level 1 (discovery) + Level 2 (full load) combined.
    For progressive disclosure, use get_skill_manifest() for Level 1.
    """
    skills_dir = skills_dir or SKILLS_DIR
    result = {}

    if not skills_dir.exists():
        logger.info(f"Skills directory not found: {skills_dir}")
        return result

    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and not child.name.startswith("_"):
            skill = load_skill(child)
            if skill:
                result[skill.name] = skill

    logger.info(f"Loaded {len(result)} skills from {skills_dir}")
    return result


def get_skill_manifest(skills_dir: Optional[Path] = None) -> str:
    """Build Level 1 manifest: name + description for all skills.

    This is injected into the system prompt at startup.
    ~100 tokens per skill — cheap enough for all skills.
    """
    skills = load_skills(skills_dir)
    if not skills:
        return ""

    lines = ["AVAILABLE SKILLS:"]
    for name, skill in sorted(skills.items()):
        desc = skill.description or "No description"
        # Truncate description to keep manifest compact
        if len(desc) > 100:
            desc = desc[:97] + "..."
        lines.append(f"- {name}: {desc}")

    return "\n".join(lines)


def activate_skill(skill_name: str, skills_dir: Optional[Path] = None) -> Optional[str]:
    """Level 2 activation: return full SKILL.md body for a triggered skill.

    Returns the skill body text, or None if skill not found.
    """
    skills_dir = skills_dir or SKILLS_DIR
    skill_dir = skills_dir / skill_name

    if not skill_dir.exists():
        return None

    skill = load_skill(skill_dir)
    if not skill:
        return None

    return skill.body
