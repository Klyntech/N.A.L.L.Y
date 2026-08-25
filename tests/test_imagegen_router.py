"""Regression test: CONTENT_ROUTER model values (commit 30f0235)."""

from nally.tools.imagegen import CONTENT_ROUTER


def test_content_router_models_match_30f0235():
    """Stale-branch commits must not silently revert CONTENT_ROUTER models.

    Originally commit 30f0235 set these to gpt-image variants; hardened for
    free-tier reliability per 2026-08: all content types now default to 'flux'
    (reliable, fast, free). generate_pollinations() also has fallback for
    legacy gpt-* names. This test guards the hardened defaults.
    """
    assert CONTENT_ROUTER["photo"]["model"] == "flux"
    assert CONTENT_ROUTER["3d"]["model"] == "flux"
    assert CONTENT_ROUTER["product"]["model"] == "flux"
    assert CONTENT_ROUTER["text"]["model"] == "flux"
    assert CONTENT_ROUTER["default"]["model"] == "flux"


def test_content_router_flux_entries_unchanged():
    """Logo, art, anime, painting should stay 'flux' per 30f0235."""
    assert CONTENT_ROUTER["logo"]["model"] == "flux"
    assert CONTENT_ROUTER["art"]["model"] == "flux"
    assert CONTENT_ROUTER["anime"]["model"] == "flux"
    assert CONTENT_ROUTER["painting"]["model"] == "flux"
