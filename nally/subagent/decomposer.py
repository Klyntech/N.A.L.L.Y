"""Task Decomposer - Breaks complex requests into subtasks using LLM reasoning"""
import json
from typing import List, Dict, Optional
from ..agent.llm import llm
from ..utils.logger import logger


DECOMPOSE_PROMPT = """You are a task decomposition specialist. Break the following goal into 2-5 independent subtasks that can be executed in parallel by separate AI agents.

Rules:
- Each subtask must be INDEPENDENT (no dependency on other subtasks)
- Each subtask must have a clear, specific goal
- Each subtask should include necessary context from the original goal
- Output as a JSON array of objects, each with "goal" and "context" fields

Example:
Input: "Research competitors and build a landing page"
Output:
[
  {
    "goal": "Research top 3 competitors in the AI coding space",
    "context": "We need to know what features competitors offer, their pricing, and their target audience."
  },
  {
    "goal": "Build a responsive landing page HTML with Tailwind CSS",
    "context": "The landing page should highlight our key features: voice interaction, multi-provider AI, system control, and memory."
  }
]

Now decompose this goal:"""


class TaskDecomposer:
    """Uses LLM to break complex requests into subtasks"""

    def decompose(self, goal: str, context: str = "") -> List[Dict]:
        """Break a complex goal into independent subtasks"""
        try:
            messages = [
                {"role": "system", "content": DECOMPOSE_PROMPT},
                {"role": "user", "content": f"{goal}\n\nAdditional context:\n{context}" if context else goal}
            ]

            response = llm.simple_chat(
                user_message=messages[1]["content"],
                system_prompt=DECOMPOSE_PROMPT
            )

            return self._parse_response(response, goal)

        except Exception as e:
            logger.error(f"Task decomposition failed: {e}")
            return [{"goal": goal, "context": context}]

    def _parse_response(self, response: str, fallback_goal: str) -> List[Dict]:
        """Parse LLM response as JSON array of tasks"""
        try:
            # Try to find JSON array in the response
            start = response.find("[")
            end = response.rfind("]")
            if start != -1 and end != -1:
                json_str = response[start:end+1]
                tasks = json.loads(json_str)
                if isinstance(tasks, list) and len(tasks) > 0:
                    return tasks

            # Try parsing entire response
            tasks = json.loads(response)
            if isinstance(tasks, list) and len(tasks) > 0:
                return tasks

        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: return original goal as single task
        return [{"goal": fallback_goal, "context": ""}]

    def summarize_results(self, goal: str, results: List[Dict]) -> str:
        """Synthesize multiple sub-agent results into a final response"""
        lines = [f"Goal: {goal}", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"[Subtask {i}] {r.get('goal', '')[:100]}")
            result = r.get("result", r.get("error", "No result"))
            lines.append(f"  Result: {result[:300]}")
            lines.append("")

        return "\n".join(lines)


decomposer = TaskDecomposer()
