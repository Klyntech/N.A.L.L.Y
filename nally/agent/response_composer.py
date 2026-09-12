"""Response Composer — turns verified execution state into the final user-facing response.

V2 diagram:
  VERIFICATION (PASS/FAIL) → RESPONSE COMPOSER → OUTPUT ROUTER → TEXT | VOICE

Responsibilities (previously scattered):
  - Honesty: "report what actually happened" + ground every claim in receipts
  - Post-processing: emoji strip + sentence capitalization (core._llm_process tail)
  - Plan synthesis: aggregate step results into coherent answer (planner.synthesize_node)
  - Voice summarization: shorten for voice without losing meaning (VoiceFormatter.SMART)

The composer does NOT decide whether the answer is blocked — that is the
Verification Layer's job. It only shapes a verified (or corrected) response
into its final textual form, before the Output Router chooses representation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.response_composer")

# ── Post-processing helpers (mirrored from core to keep composer self-contained) ──

def _strip_emojis(text: str) -> str:
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"
        "\U0001f300-\U0001f5ff"
        "\U0001f680-\U0001f6ff"
        "\U0001f1e0-\U0001f1ff"
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u200d"
        "\ufe0f"
        "\u2640-\u2642"
        "\u2600-\u2b55"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\u3030"
        "\u2934"
        "\u2935"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()

def _capitalize_sentences(text: str) -> str:
    return re.sub(
        r"(^|[.!?]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )

# ── Composer ─────────────────────────────────────────────

class ResponseComposer:
    """Compose a final textual response from verified state.

    All paths return plain text (Telegram HTML / voice pacing are applied by
    OutputRouter downstream).
    """

    def compose(
        self,
        text: str,
        *,
        intent_class: str = "",
        verified: bool = True,
        is_partial: bool = False,
        style: str = "default",
        channel: str = "",
    ) -> str:
        """Post-process a verified response into its final textual form.

        Args:
            text: Verified (or self-corrected) model text.
            intent_class: Harness class for style hints.
            verified: Whether verification passed (affects hedging).
            is_partial: When completion gate fired (already prepended [TASK NOT COMPLETE]).
            style: "default" | "concise" | "verbose".
            channel: Origin channel label. Presentation normalization
                (emoji strip + sentence caps) is Telegram-only by locked
                default — Web/API/voice paths keep neutral semantics so the
                OutputRouter/SpeechPlanner downstream stays uncorrupted.

        Returns:
            Final plain-text response ready for OutputRouter.
        """
        if not text:
            return text or "Done."
        out = text.strip()
        # Never re-apply post-processing to an already-gated prefix
        if out.startswith("[TASK NOT COMPLETE]") or out.startswith("[Blocked by guardrail]"):
            return out
        ch = (channel or "").lower()
        is_telegram = "telegram" in ch or "tg_voice" in ch
        if is_telegram:
            out = _strip_emojis(out)
            # Preserve explicitly lowercased casual tone for very short replies
            # (Nally personality: "Hey, what we doing today" — not "Hey, What We Doing Today")
            if len(out) > 30:
                out = _capitalize_sentences(out)
        else:
            # Channel-neutral: light trim only; no emoji/case mutation.
            out = out.strip()
        if style == "concise" and len(out) > 800:
            # Voice-style shortening: keep first 2 sentences + summary hint
            parts = re.split(r"(?<=[.!?])\s+", out)
            if len(parts) > 3:
                out = " ".join(parts[:2]) + " ... " + " ".join(parts[-1:])
        return out

    def compose_from_plan(
        self,
        goal: str,
        steps: List[Any],
        step_results: Dict[str, str],
        terminal: str,
        *,
        raw_llm_text: Optional[str] = None,
        channel: str = "",
    ) -> str:
        """Synthesize step results when planner's LLM synthesize fails or as fallback.

        Mirrors planner._fallback_synthesis but as a first-class composer path so
        planner.py can delegate here. When raw_llm_text is provided and terminal
        is complete, it is post-processed and returned directly.
        """
        if raw_llm_text and terminal == "complete":
            return self.compose(raw_llm_text, channel=channel)
        lines = [f"Here's what I did for: {goal}\n"]
        for s in steps:
            # steps may be dicts or PlanStep objects
            gid = getattr(s, "id", None) or (s.get("id") if isinstance(s, dict) else "?")
            g = getattr(s, "goal", None) or (s.get("goal") if isinstance(s, dict) else str(s))
            status = getattr(s, "status", None)
            status_val = status.value if hasattr(status, "value") else (status or "?")
            icon = {"completed": "+", "failed": "-"}.get(str(status_val).lower(), "?")
            result = step_results.get(gid, getattr(s, "result", None) or "")
            lines.append(f"[{icon}] {g}")
            if result:
                lines.append(f"  {str(result)[:200]}")
        # Honest prefix per terminal (mirrors planner.synthesize_node outcome_frame)
        prefix = {
            "complete": "",
            "partial": "[Partial] Some steps completed and some did not. What completed and what remains are listed below.\n\n",
            "failed": "[Failed] The objective could not be completed. Attempted work is listed below.\n\n",
            "blocked": "[Blocked] Progress stopped due to an external condition (approval/permission). What completed is listed below.\n\n",
        }.get(terminal, "")
        return self.compose(prefix + "\n".join(lines), channel=channel)

# Singleton
response_composer = ResponseComposer()

def compose_response(text: str, **kwargs) -> str:
    return response_composer.compose(text, **kwargs)
