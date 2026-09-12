"""Verification package — single façade for all Nally verification.

Re-exports the layer's public API so callers can:

    from nally.agent.verification import verify_turn, VerificationLayer

Backward-compat shims for older imports that touched verifier/guardrails
directly continue to work; new code should go through this façade.
"""

from .layer import VerificationLayer, VerificationTurnResult, verify_turn  # noqa: F401

__all__ = ["VerificationLayer", "VerificationTurnResult", "verify_turn"]
