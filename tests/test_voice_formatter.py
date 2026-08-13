"""Tests for VoiceFormatter."""

import pytest

from nally.voice.formatter import VoiceFormatter, VoiceConfig, VoiceMode, format_for_voice


class TestVoiceFormatter:
    """Test VoiceFormatter behavior."""

    def setup_method(self):
        self.formatter = VoiceFormatter()

    # ── Basic formatting ─────────────────────────────────────

    def test_simple_text(self):
        """Simple text passes through clean."""
        result = self.formatter.format("Hello world. How are you?", mode=VoiceMode.FULL)
        assert "Hello world." in result
        assert "How are you?" in result

    def test_code_block_stripped(self):
        """Code blocks replaced with placeholder."""
        text = "Here is code:\n```python\nprint('hello')\n```\nEnd."
        result = self.formatter.format(text, mode=VoiceMode.FULL)
        assert "[code shown on screen]" in result
        assert "print('hello')" not in result

    def test_inline_code_stripped(self):
        """Inline code backticks removed."""
        result = self.formatter.format("Use `print()` function.", mode=VoiceMode.FULL)
        assert "print()" in result
        assert "`" not in result

    def test_table_replaced(self):
        """Tables replaced with placeholder."""
        text = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = self.formatter.format(text, mode=VoiceMode.FULL)
        assert "[table shown on screen]" in result

    def test_headers_converted(self):
        """Headers get a pause after them."""
        result = self.formatter.format("# Header\nContent", mode=VoiceMode.FULL)
        assert "Header" in result
        assert "Content" in result

    def test_bold_italic_stripped(self):
        """Markdown emphasis stripped."""
        result = self.formatter.format("**Bold** and *italic* text.", mode=VoiceMode.FULL)
        assert "Bold and italic text." in result
        assert "**" not in result
        assert "*" not in result

    def test_links_speak_text(self):
        """Links speak the link text, not URL."""
        result = self.formatter.format("See [Google](https://google.com) for more.", mode=VoiceMode.FULL)
        assert "Google" in result
        assert "https://google.com" not in result

    def test_blockquote(self):
        """Blockquotes announced."""
        result = self.formatter.format("> This is a quote", mode=VoiceMode.FULL)
        assert "Quote:" in result
        assert "This is a quote" in result

    # ── List conversion ──────────────────────────────────────

    def test_single_item_list(self):
        """Single list item -> 'First, item.'"""
        result = self.formatter.format("- Item one", mode=VoiceMode.FULL)
        assert "First" in result
        assert "Item one" in result

    def test_multi_item_list(self):
        """Multiple items -> 'First, X. Second, Y.'"""
        text = "- Item one\n- Item two\n- Item three"
        result = self.formatter.format(text, mode=VoiceMode.FULL)
        assert "First" in result
        assert "Item one" in result
        assert "Second" in result
        assert "Item two" in result
        assert "Third" in result
        assert "Item three" in result

    def test_ordered_list(self):
        """Ordered lists also converted."""
        text = "1. First item\n2. Second item"
        result = self.formatter.format(text, mode=VoiceMode.FULL)
        assert "First" in result
        assert "First item" in result
        assert "Second" in result
        assert "Second item" in result

    def test_checkbox_list(self):
        """Checkboxes treated as regular items."""
        result = self.formatter.format("- [x] Done\n- [ ] Todo", mode=VoiceMode.FULL)
        assert "Done" in result
        assert "Todo" in result

    # ── Mode behavior ────────────────────────────────────────

    def test_mode_none_returns_empty(self):
        """NONE mode returns empty string."""
        result = self.formatter.format("Anything", mode=VoiceMode.NONE)
        assert result == ""

    def test_mode_summary_uses_summary(self):
        """SUMMARY mode uses provided summary."""
        result = self.formatter.format("Long text...", mode=VoiceMode.SUMMARY, summary="Short summary.")
        assert result == "Short summary."

    def test_mode_full_uses_full_text(self):
        """FULL mode uses full text."""
        result = self.formatter.format("Full text.", mode=VoiceMode.FULL)
        assert "Full text." in result

    def test_smart_mode_short_text(self):
        """SMART mode: short text -> full."""
        result = self.formatter.format("Short.", mode=VoiceMode.SMART)
        assert "Short." in result

    def test_smart_mode_long_text(self):
        """SMART mode: long text -> summary fallback."""
        long_text = "This is a very long response that exceeds the 200 character threshold for smart mode. " * 3
        result = self.formatter.format(long_text, mode=VoiceMode.SMART)
        assert "Details on screen." in result

    # ── Natural punctuation ────────────────────────────────────

    def test_comma_preserved(self):
        """Commas preserved for natural TTS pauses."""
        result = self.formatter.format("One, two, three.", mode=VoiceMode.FULL)
        assert "One, two, three." in result

    def test_sentence_preserved(self):
        """Sentence punctuation preserved for natural pauses."""
        result = self.formatter.format("Hello. World.", mode=VoiceMode.FULL)
        assert "Hello." in result
        assert "World." in result

    def test_colon_preserved(self):
        """Colons preserved for natural pauses."""
        result = self.formatter.format("Items: one, two.", mode=VoiceMode.FULL)
        assert "Items: one, two." in result

    # ── VoiceConfig from agent ──────────────────────────────

    def test_create_voice_config_defaults(self):
        """Default voice config from agent response."""
        from nally.voice.formatter import create_voice_config_from_agent

        response = {"text": "Hello", "voice": {}}
        config = create_voice_config_from_agent(response)
        assert config.speak is True
        assert config.mode == VoiceMode.SMART

    def test_create_voice_config_custom(self):
        """Custom voice config from agent response."""
        from nally.voice.formatter import create_voice_config_from_agent

        response = {"text": "Hello", "voice": {"speak": False, "mode": "none"}}
        config = create_voice_config_from_agent(response)
        assert config.speak is False
        assert config.mode == VoiceMode.NONE

    # ── format_for_voice convenience ─────────────────────────

    def test_format_for_voice_string(self):
        """format_for_voice works with plain string."""
        result = format_for_voice("Hello world.")
        assert "Hello world." in result

    def test_format_for_voice_dict(self):
        """format_for_voice works with agent response dict."""
        result = format_for_voice({"text": "Test.", "voice": {"mode": "full"}})
        assert "Test." in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])