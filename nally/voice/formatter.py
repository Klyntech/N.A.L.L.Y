"""Voice Formatter — converts agent text responses to speakable audio.

Separates "what is displayed" from "what is spoken" — critical for voice UX.
Code, tables, long lists, and thinking are stripped or summarized for TTS.
"""

import re
from dataclasses import dataclass
from enum import Enum


class VoiceMode(str, Enum):
    """Voice output mode."""
    FULL = "full"           # Speak entire response (short responses)
    SUMMARY = "summary"     # Speak only voice_summary field
    SMART = "smart"         # Auto: <200 chars = full, >200 = summary
    NONE = "none"           # Silent — visual only


@dataclass
class VoiceConfig:
    """Voice output configuration from agent."""
    speak: bool = True
    mode: VoiceMode = VoiceMode.SMART
    summary: str = ""
    skip_patterns: list[str] | None = None

    def __post_init__(self):
        if self.skip_patterns is None:
            self.skip_patterns = ["code", "table", "long_list", "thinking"]


class VoiceFormatter:
    """Formats text for TTS — strips markdown, converts structures for speech."""

    # Patterns to strip/convert for speech
    CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    INLINE_CODE_RE = re.compile(r"`([^`]+)`")
    TABLE_RE = re.compile(r"^\|.*\|$", re.MULTILINE)
    TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$", re.MULTILINE)
    HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
    ITALIC_RE = re.compile(r"\*(.+?)\*")
    STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")
    LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
    IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
    BLOCKQUOTE_RE = re.compile(r"^>\s*(.+)$", re.MULTILINE)
    HR_RE = re.compile(r"^---+$", re.MULTILINE)
    LIST_ITEM_RE = re.compile(r"^[\s]*[-*+]\s+(.+)$", re.MULTILINE)
    ORDERED_LIST_RE = re.compile(r"^[\s]*\d+\.\s+(.+)$", re.MULTILINE)
    CHECKBOX_RE = re.compile(r"^[\s]*[-*+]\s+\[[ xX]\]\s+(.+)$", re.MULTILINE)

    def __init__(self, config: VoiceConfig | None = None):
        self.config = config or VoiceConfig()

    def format(self, text: str, mode: VoiceMode | None = None, summary: str = "") -> str:
        """Format text for TTS based on mode."""
        mode = mode or self.config.mode

        if mode == VoiceMode.NONE or not self.config.speak:
            return ""

        if mode == VoiceMode.SUMMARY:
            return self._clean_for_speech(summary or self.config.summary or text)

        if mode == VoiceMode.FULL:
            return self._clean_for_speech(text)

        # SMART mode: auto-detect
        if len(text) <= 200:
            return self._clean_for_speech(text)
        else:
            return self._clean_for_speech(summary or self.config.summary or self._extract_summary(text))

    def _clean_for_speech(self, text: str) -> str:
        """Clean text for natural speech output."""
        if not text:
            return ""

        # Replace code blocks
        text = self.CODE_BLOCK_RE.sub("[code shown on screen]", text)

        # Replace inline code
        text = self.INLINE_CODE_RE.sub(r"\1", text)

        # Replace tables
        text = self.TABLE_RE.sub("[table shown on screen]", text)
        text = self.TABLE_SEP_RE.sub("", text)

        # Headers → spoken with pause
        text = self.HEADER_RE.sub("\\1. ", text)

        # Bold/italic/strikethrough → plain
        text = self.BOLD_RE.sub(r"\1", text)
        text = self.ITALIC_RE.sub(r"\1", text)
        text = self.STRIKETHROUGH_RE.sub(r"\1", text)

        # Links → speak link text only
        text = self.LINK_RE.sub(r"\1", text)

        # Images → announce
        text = self.IMAGE_RE.sub(r"[image: \1]", text)

        # Blockquotes
        text = self.BLOCKQUOTE_RE.sub("Quote: \\1. ", text)

        # Horizontal rules
        text = self.HR_RE.sub(". ", text)

        # Checkboxes
        text = self.CHECKBOX_RE.sub(r"\1", text)

        # Lists → convert to spoken form
        text = self._convert_lists(text)

        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = text.strip()

        return text

    def _convert_lists(self, text: str) -> str:
        """Convert markdown lists to spoken form."""
        lines = text.split("\n")
        result = []
        list_items = []
        in_list = False

        for line in lines:
            # Check for list items
            m = self.LIST_ITEM_RE.match(line)
            om = self.ORDERED_LIST_RE.match(line)

            if m or om:
                in_list = True
                item = m.group(1) if m else om.group(1)
                list_items.append(item)
            else:
                if in_list and list_items:
                    # Flush accumulated list
                    result.append(self._format_list(list_items))
                    list_items = []
                    in_list = False
                result.append(line)

        # Flush any remaining list
        if list_items:
            result.append(self._format_list(list_items))

        return "\n".join(result)

    def _format_list(self, items: list[str]) -> str:
        """Format list items for speech."""
        if not items:
            return ""

        if len(items) == 1:
            return f"First, {items[0]}."

        # Multiple items: "First, X. Second, Y. Third, Z."
        ordinals = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth"]
        parts = []
        for i, item in enumerate(items):
            if i < len(ordinals):
                parts.append(f"{ordinals[i]}, {item}")
            else:
                parts.append(f"Item {i+1}, {item}")

        return ". ".join(parts) + "."

    def _extract_summary(self, text: str) -> str:
        """Extract a reasonable summary from long text (fallback)."""
        # Take first 2 sentences
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) >= 2:
            return " ".join(sentences[:2]) + " Details on screen."
        elif sentences:
            return sentences[0] + " Details on screen."
        return "Response shown on screen."


def create_voice_config_from_agent(response: dict) -> VoiceConfig:
    """Create VoiceConfig from agent response dict."""
    voice_data = response.get("voice", {}) if isinstance(response, dict) else {}

    mode_str = voice_data.get("mode", "smart")
    try:
        mode = VoiceMode(mode_str)
    except ValueError:
        mode = VoiceMode.SMART

    return VoiceConfig(
        speak=voice_data.get("speak", True),
        mode=mode,
        summary=voice_data.get("summary", ""),
        skip_patterns=voice_data.get("skip_patterns"),
    )


def format_for_voice(response: dict | str, config: VoiceConfig | None = None) -> str:
    """Convenience function to format agent response for TTS."""
    if isinstance(response, str):
        return VoiceFormatter(config).format(response)

    if isinstance(response, dict):
        if config is None:
            config = create_voice_config_from_agent(response)
        text = response.get("text", "")
        return VoiceFormatter(config).format(text)

    return ""


# Backward compatibility
__all__ = [
    "VoiceConfig",
    "VoiceFormatter",
    "VoiceMode",
    "create_voice_config_from_agent",
    "format_for_voice",
]
