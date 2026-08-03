"""Regression test: CONTENT_ROUTER model values (commit 30f0235)."""

from nally.tools.imagegen import CONTENT_ROUTER


def test_content_router_models_match_30f0235():
    """Stale-branch commits must not silently revert CONTENT_ROUTER models.

    Commit 30f0235 set these 5 entries to real free Pollinations models.
    Commit 9a8a16c accidentally reverted them all to 'flux'. This test
    catches any future recurrence.
    """
    assert CONTENT_ROUTER["photo"]["model"] == "gpt-image-2"
    assert CONTENT_ROUTER["3d"]["model"] == "gptimage-large"
    assert CONTENT_ROUTER["product"]["model"] == "gptimage"
    assert CONTENT_ROUTER["text"]["model"] == "gptimage-large"
    assert CONTENT_ROUTER["default"]["model"] == "zimage"


def test_content_router_flux_entries_unchanged():
    """Logo, art, anime, painting should stay 'flux' per 30f0235."""
    assert CONTENT_ROUTER["logo"]["model"] == "flux"
    assert CONTENT_ROUTER["art"]["model"] == "flux"
    assert CONTENT_ROUTER["anime"]["model"] == "flux"
    assert CONTENT_ROUTER["painting"]["model"] == "flux"
