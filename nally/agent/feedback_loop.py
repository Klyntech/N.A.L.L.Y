"""Executable Feedback Loop — run code, capture errors, iterate for correction.

Pattern from MetaGPT: after generating code, run it in a sandbox, capture
execution output/errors, and feed them back to the LLM for correction.
Up to MAX_CORRECTION_CYCLES iterations.

This is NOT prompt-level reflection — it's grounded in actual runtime output.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nally.feedback_loop")

MAX_CORRECTION_CYCLES = 3
CORRECTION_TIMEOUT = 30  # seconds per execution attempt


@dataclass
class ExecutionResult:
    """Result of a code execution attempt."""
    success: bool
    output: str
    error: str = ""
    exit_code: int = 0
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output[:500],
            "error": self.error[:500],
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
        }


@dataclass
class FeedbackCycle:
    """One iteration of the feedback loop."""
    cycle: int
    code: str
    execution: ExecutionResult
    correction_prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle": self.cycle,
            "code": self.code[:300],
            "execution": self.execution.to_dict(),
            "correction_prompt": self.correction_prompt[:300],
        }


@dataclass
class FeedbackLoopResult:
    """Final result after all correction cycles."""
    final_code: str
    cycles: List[FeedbackCycle]
    success: bool
    total_duration_ms: int = 0

    @property
    def attempts(self) -> int:
        return len(self.cycles)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_code": self.final_code[:500],
            "attempts": self.attempts,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
            "cycles": [c.to_dict() for c in self.cycles],
        }


class ExecutableFeedbackLoop:
    """Run code, capture errors, feed back to LLM for correction.

    Usage:
        loop = ExecutableFeedbackLoop(llm_call_fn, execute_fn)
        result = loop.run(initial_code, "Create a function that sorts a list")
        if result.success:
            print(f"Fixed after {result.attempts} attempts")
    """

    def __init__(
        self,
        llm_call_fn: Callable,
        execute_fn: Callable,
        max_cycles: int = MAX_CORRECTION_CYCLES,
        timeout: int = CORRECTION_TIMEOUT,
    ):
        self._llm_call = llm_call_fn
        self._execute = execute_fn
        self._max_cycles = max_cycles
        self._timeout = timeout

    def run(self, initial_code: str, goal: str, language: str = "python") -> FeedbackLoopResult:
        """Run the feedback loop: execute → check → correct → repeat.

        Args:
            initial_code: The code to execute first
            goal: What the code should accomplish (for correction prompts)
            language: Programming language (python, javascript, etc.)

        Returns:
            FeedbackLoopResult with final code and cycle history
        """
        start_time = time.time()
        cycles: List[FeedbackCycle] = []
        current_code = initial_code

        for cycle_num in range(1, self._max_cycles + 1):
            # Execute the code
            execution = self._execute_code(current_code, language)

            # Record this cycle
            correction_prompt = ""
            if not execution.success and cycle_num < self._max_cycles:
                correction_prompt = self._build_correction_prompt(
                    goal, current_code, execution, cycle_num
                )

            cycles.append(FeedbackCycle(
                cycle=cycle_num,
                code=current_code,
                execution=execution,
                correction_prompt=correction_prompt,
            ))

            # If execution succeeded, we're done
            if execution.success:
                logger.info(f"Feedback loop: succeeded on attempt {cycle_num}")
                return FeedbackLoopResult(
                    final_code=current_code,
                    cycles=cycles,
                    success=True,
                    total_duration_ms=int((time.time() - start_time) * 1000),
                )

            # If this was the last cycle, stop
            if cycle_num >= self._max_cycles:
                logger.warning(f"Feedback loop: exhausted {self._max_cycles} cycles")
                break

            # Get corrected code from LLM
            try:
                corrected = self._llm_call(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"You are fixing {language} code that failed execution. "
                                "The code produced an error. Fix the error and output ONLY "
                                "the corrected code, no explanation."
                            ),
                        },
                        {
                            "role": "user",
                            "content": correction_prompt,
                        },
                    ],
                    temperature=0.1,
                )

                if corrected and not corrected.startswith("Error"):
                    # Extract code from response (handle markdown code blocks)
                    current_code = self._extract_code(corrected, language)
                else:
                    logger.warning(f"Feedback loop: LLM correction failed on cycle {cycle_num}")
                    break

            except Exception as e:
                logger.warning(f"Feedback loop: LLM call failed on cycle {cycle_num}: {e}")
                break

        # All cycles exhausted without success
        return FeedbackLoopResult(
            final_code=current_code,
            cycles=cycles,
            success=False,
            total_duration_ms=int((time.time() - start_time) * 1000),
        )

    def _execute_code(self, code: str, language: str) -> ExecutionResult:
        """Execute code and capture output/errors."""
        start = time.time()
        try:
            result = self._execute(code)
            duration = int((time.time() - start) * 1000)

            if isinstance(result, tuple):
                output, success = result
                return ExecutionResult(
                    success=success,
                    output=str(output)[:2000] if output else "",
                    duration_ms=duration,
                )
            elif isinstance(result, str):
                return ExecutionResult(
                    success=not result.startswith("Error"),
                    output=result[:2000],
                    duration_ms=duration,
                )
            else:
                return ExecutionResult(
                    success=True,
                    output=str(result)[:2000],
                    duration_ms=duration,
                )

        except Exception as e:
            duration = int((time.time() - start) * 1000)
            return ExecutionResult(
                success=False,
                output="",
                error=str(e)[:2000],
                duration_ms=duration,
            )

    def _build_correction_prompt(
        self, goal: str, code: str, execution: ExecutionResult, cycle: int
    ) -> str:
        """Build a prompt that gives the LLM the error context for correction."""
        parts = [
            f"Goal: {goal}",
            f"Attempt {cycle} failed with this error:",
            "",
        ]

        if execution.error:
            parts.append(f"Error:\n{execution.error}")
        elif execution.output:
            parts.append(f"Output (may contain errors):\n{execution.output[:1000]}")
        else:
            parts.append("No output produced (possible crash or hang)")

        parts.extend([
            "",
            "The code that was executed:",
            f"```python\n{code[:2000]}\n```",
            "",
            "Fix the error. Output ONLY the corrected code in a code block.",
        ])

        return "\n".join(parts)

    def _extract_code(self, response: str, language: str) -> str:
        """Extract code from LLM response (handles markdown code blocks)."""
        import re

        # Try to find code block
        pattern = rf"```(?:{language})?\s*\n(.*?)```"
        match = re.search(pattern, response, re.DOTALL)
        if match:
            return match.group(1).strip()

        # No code block — assume the entire response is code
        # Strip any leading/trailing explanation text
        lines = response.strip().split("\n")
        code_lines = []
        in_code = False
        for line in lines:
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code or not line.strip().startswith(("Here", "The", "This", "Sure", "Okay")):
                code_lines.append(line)

        return "\n".join(code_lines).strip() or response.strip()


# Convenience function
def run_with_correction(
    code: str,
    goal: str,
    llm_call_fn: Callable,
    execute_fn: Callable,
    language: str = "python",
    max_cycles: int = MAX_CORRECTION_CYCLES,
) -> FeedbackLoopResult:
    """Run code with automatic error correction.

    Args:
        code: Initial code to execute
        goal: What the code should accomplish
        llm_call_fn: Callable for LLM correction (messages, temperature) -> str
        execute_fn: Callable to execute code (code) -> str or (output, success)
        language: Programming language
        max_cycles: Maximum correction attempts

    Returns:
        FeedbackLoopResult with final code and cycle history
    """
    loop = ExecutableFeedbackLoop(
        llm_call_fn=llm_call_fn,
        execute_fn=execute_fn,
        max_cycles=max_cycles,
    )
    return loop.run(code, goal, language)
