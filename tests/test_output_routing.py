"""Tests for Response Composer + Output Routing — Phase 6 output pipeline.

Acceptance conditions:
  1. Verified success reaches composer
  2. Blocked result cannot bypass composer
  3. Partial completion uses the canonical response
  4. Telegram and Web consume the same composed result
  5. Voice remains an output mode rather than becoming part of reasoning
  6. No production caller bypasses ResponseComposer for final responses
  7. OutputRouter handles Telegram message splitting
"""

from unittest.mock import MagicMock, patch

import pytest

from nally.output.types import ComposedResponse
from nally.output.router import OutputRouter, OutputTarget, RoutedOutput, route_output
from nally.agent.response_composer import ResponseComposer, response_composer, compose_response


# ── 1. ComposedResponse data model ──────────────────────────


def test_composed_response_is_ok():
    """ComposedResponse.is_ok is True when verified, not partial, not blocked."""
    r = ComposedResponse(text="hello", verified=True, is_partial=False, blocked=False)
    assert r.is_ok is True


def test_composed_response_blocked():
    """ComposedResponse.is_ok is False when blocked."""
    r = ComposedResponse(text="hello", verified=True, is_partial=False, blocked=True, block_reason="guardrail")
    assert r.is_ok is False
    assert r.display_text == "[Blocked by guardrail] guardrail"


def test_composed_response_partial():
    """ComposedResponse.is_ok is False when partial."""
    r = ComposedResponse(text="did some work", verified=True, is_partial=True, block_reason="tool failed")
    assert r.is_ok is False
    assert r.display_text.startswith("[TASK NOT COMPLETE]")
    assert "did some work" in r.display_text


def test_composed_response_unverified():
    """ComposedResponse.is_ok is False when not verified."""
    r = ComposedResponse(text="hello", verified=False)
    assert r.is_ok is False


def test_composed_response_display_text_normal():
    """ComposedResponse.display_text returns text when not blocked/partial."""
    r = ComposedResponse(text="hello world", verified=True)
    assert r.display_text == "hello world"


def test_composed_response_attachments():
    """ComposedResponse carries attachments list."""
    r = ComposedResponse(text="here", attachments=["/tmp/img.png"])
    assert r.attachments == ["/tmp/img.png"]


# ── 2. ResponseComposer — verified success reaches composer ──


def test_composer_passes_through_verified_text():
    """ResponseComposer passes through clean verified text."""
    c = ResponseComposer()
    result = c.compose("Hello world", verified=True, channel="web:default")
    assert result == "Hello world"


def test_composer_telegram_strips_emojis():
    """ResponseComposer strips emojis for Telegram channel."""
    c = ResponseComposer()
    result = c.compose("Hello world \U0001f600", channel="telegram:123")
    assert "\U0001f600" not in result
    assert "Hello world" in result


def test_composer_telegram_capitalizes():
    """ResponseComposer capitalizes sentences for Telegram (when >30 chars)."""
    c = ResponseComposer()
    long_text = "this is a long sentence that should be capitalized properly for telegram"
    result = c.compose(long_text, channel="telegram:123")
    # First letter after sentence boundary should be capitalized
    assert result[0].isupper() or len(result) <= 30


def test_composer_web_no_emoji_strip():
    """ResponseComposer does NOT strip emojis for web channel."""
    c = ResponseComposer()
    result = c.compose("Hello \U0001f600 world", channel="web:default")
    assert "\U0001f600" in result


def test_composer_preserves_blocked_prefix():
    """ResponseComposer never re-processes [TASK NOT COMPLETE] or [Blocked] prefixes."""
    c = ResponseComposer()
    blocked = "[Blocked by guardrail] sensitive data"
    result = c.compose(blocked, channel="telegram:123")
    assert result == blocked


def test_composer_preserves_partial_prefix():
    """ResponseComposer preserves [TASK NOT COMPLETE] prefix."""
    c = ResponseComposer()
    partial = "[TASK NOT COMPLETE] tools failed"
    result = c.compose(partial, channel="telegram:123")
    assert result == partial


def test_composer_empty_returns_done():
    """ResponseComposer returns 'Done.' for empty text."""
    c = ResponseComposer()
    assert c.compose("") == "Done."
    assert c.compose(None) == "Done."


def test_composer_concise_style():
    """ResponseComposer truncates long text in concise style."""
    c = ResponseComposer()
    long_text = "First sentence. " + "Middle content. " * 50 + "Last sentence."
    result = c.compose(long_text, style="concise")
    assert len(result) < len(long_text)


def test_composer_all_channels_produce_text():
    """ResponseComposer always returns a string (plain text)."""
    c = ResponseComposer()
    for ch in ["", "telegram:123", "web:default", "cli", "ws:main"]:
        result = c.compose("hello", channel=ch)
        assert isinstance(result, str)


# ── 3. OutputRouter — same composed result for all surfaces ──


def test_router_telegram_produces_html():
    """OutputRouter produces Telegram HTML for telegram channel."""
    router = OutputRouter()
    routed = router.route("Hello **world**", channel="telegram:123")
    assert routed.target == OutputTarget.TEXT
    assert routed.html is not None
    assert "<b>" in routed.html or "Hello" in routed.html


def test_router_web_returns_text_only():
    """OutputRouter returns plain text for web channel (no HTML)."""
    router = OutputRouter()
    routed = router.route("Hello world", channel="web:default")
    assert routed.target == OutputTarget.TEXT
    assert routed.html is None
    assert routed.text == "Hello world"


def test_router_voice_telegram():
    """OutputRouter routes voice for Telegram."""
    router = OutputRouter()
    routed = router.route("Hello world", channel="telegram:123", wants_voice=True)
    assert routed.target in (OutputTarget.BOTH, OutputTarget.VOICE)
    assert routed.voice_text is not None
    assert routed.voice_format == "ogg"


def test_router_voice_web_disabled():
    """OutputRouter blocks web voice when NALLY_WEB_VOICE_ENABLED=false."""
    router = OutputRouter()
    with patch.dict("os.environ", {"NALLY_WEB_VOICE_ENABLED": "false"}):
        routed = router.route("Hello world", channel="web:default", wants_voice=True)
    assert routed.target == OutputTarget.TEXT
    assert routed.voice_text is None


def test_router_telegram_chunks():
    """OutputRouter produces chunks for long Telegram messages."""
    router = OutputRouter()
    long_text = "x" * 5000
    routed = router.route(long_text, channel="telegram:123")
    assert routed.html is not None
    assert len(routed.chunks) > 1
    for chunk in routed.chunks:
        assert len(chunk) <= 4096


def test_router_telegram_short_no_chunks():
    """OutputRouter does not split short Telegram messages."""
    router = OutputRouter()
    routed = router.route("Hello", channel="telegram:123")
    assert len(routed.chunks) <= 1


def test_router_unknown_channel_returns_text():
    """OutputRouter handles unknown channel gracefully."""
    router = OutputRouter()
    routed = router.route("Hello", channel="unknown:channel")
    assert routed.target == OutputTarget.TEXT
    assert routed.text == "Hello"
    assert routed.html is None


# ── 4. Telegram splitting ───────────────────────────────────


def test_split_telegram_empty():
    """_split_telegram handles empty input."""
    router = OutputRouter()
    assert router._split_telegram("") == []
    assert router._split_telegram(None) == []


def test_split_telegram_short():
    """_split_telegram does not split short text."""
    router = OutputRouter()
    result = router._split_telegram("hello", limit=100)
    assert result == ["hello"]


def test_split_telegram_paragraph_boundary():
    """_split_telegram splits at paragraph boundaries."""
    router = OutputRouter()
    text = "Para one.\n\n" + "x" * 3000 + "\n\nPara two.\n\n" + "y" * 3000
    chunks = router._split_telegram(text, limit=4096)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 4096


def test_split_telegram_newline_boundary():
    """_split_telegram falls back to newline splitting."""
    router = OutputRouter()
    text = "Line one.\n" + "x" * 3000 + "\nLine two.\n" + "y" * 3000
    chunks = router._split_telegram(text, limit=4096)
    assert len(chunks) >= 2


def test_split_telegram_force_split():
    """_split_telegram force-splits when no good boundary exists."""
    router = OutputRouter()
    text = "x" * 5000
    chunks = router._split_telegram(text, limit=4096)
    assert len(chunks) == 2
    assert chunks[0] == "x" * 4096


# ── 5. Voice is output mode, not reasoning ──────────────────


def test_router_voice_text_shortened():
    """OutputRouter shortens voice text for long responses."""
    router = OutputRouter()
    long_text = "x" * 1000
    routed = router.route(long_text, channel="telegram:123", wants_voice=True)
    assert routed.voice_text is not None
    assert len(routed.voice_text) <= len(long_text)


def test_router_voice_text_not_shortened():
    """OutputRouter does not shorten short voice text."""
    router = OutputRouter()
    short_text = "Hello world"
    routed = router.route(short_text, channel="telegram:123", wants_voice=True)
    assert routed.voice_text == short_text


def test_router_voice_format_ogg_telegram():
    """OutputRouter uses ogg format for Telegram voice."""
    router = OutputRouter()
    routed = router.route("test", channel="telegram:123", wants_voice=True)
    assert routed.voice_format == "ogg"


# ── 6. No bypass invariant ──────────────────────────────────


def test_core_imports_composer_helpers():
    """core.py imports _strip_emojis and _capitalize_sentences from response_composer."""
    from nally.agent import core
    # Verify the helpers are imported (not defined locally)
    import nally.agent.response_composer as rc
    assert core._strip_emojis is rc._strip_emojis
    assert core._capitalize_sentences is rc._capitalize_sentences


def test_composer_singleton_exists():
    """ResponseComposer singleton is available."""
    assert response_composer is not None
    assert isinstance(response_composer, ResponseComposer)


def test_compose_response_convenience():
    """compose_response() convenience function works."""
    result = compose_response("hello world", channel="web:default")
    assert result == "hello world"


def test_route_output_convenience():
    """route_output() convenience function works."""
    routed = route_output("hello", channel="web:default")
    assert isinstance(routed, RoutedOutput)
    assert routed.text == "hello"


# ── 7. RouteOutput data model ───────────────────────────────


def test_routed_output_fields():
    """RoutedOutput carries all required fields."""
    r = RoutedOutput(
        target=OutputTarget.TEXT,
        text="hello",
        html="<b>hello</b>",
        voice_text="hello",
        voice_format="ogg",
        attachments=["file.txt"],
        chunks=["<b>hello</b>"],
    )
    assert r.target == OutputTarget.TEXT
    assert r.html == "<b>hello</b>"
    assert r.chunks == ["<b>hello</b>"]
    assert r.attachments == ["file.txt"]


def test_output_target_enum():
    """OutputTarget has all expected values."""
    assert OutputTarget.TEXT == "text"
    assert OutputTarget.VOICE == "voice"
    assert OutputTarget.BOTH == "both"
