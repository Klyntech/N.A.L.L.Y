import concurrent.futures
from typing import Dict, List, Optional

from ..agent.llm import llm
from ..utils.logger import logger
from .config import THINKING_MAX_STRATEGIES, THINKING_TIMEOUT
from .prompts import STRATEGY_PROMPTS, SYNTHESIS_SYSTEM_PROMPT, THINKING_SYSTEM_PROMPT
from .strategies import STRATEGY_REGISTRY, StrategyResult, get_strategy_names


class ThinkingEngine:
    """Orchestrates multi-strategy thinking for complex questions."""

    def __init__(self):
        self._enabled = True

    def think(
        self,
        question: str,
        domain: str = "all",
        strategies: Optional[List[str]] = None,
        max_strategies: int = THINKING_MAX_STRATEGIES,
    ) -> Dict:
        """Run thinking strategies and return synthesized results."""
        if not self._enabled:
            return {"thinking_enabled": False, "answer": None}

        # Select strategies
        if strategies is None or len(strategies) == 0:
            selected_names = self._select_strategies(question, domain, max_strategies)
        else:
            selected_names = [
                s for s in strategies if s in STRATEGY_REGISTRY
            ][:max_strategies]

        if not selected_names:
            return {"thinking_enabled": True, "answer": None, "strategies_run": []}

        # Run strategies in parallel
        results = self._run_strategies_parallel(selected_names, question, domain)

        # Synthesize
        synthesis = self._synthesize(question, domain, results)

        return {
            "thinking_enabled": True,
            "strategies_run": [r.strategy_name for r in results],
            "results": [self._result_to_dict(r) for r in results],
            "synthesis": synthesis,
        }

    def _select_strategies(
        self, question: str, domain: str, max_strategies: int
    ) -> List[str]:
        """Select the best strategies for a question."""
        available = [
            name for name in get_strategy_names()
            if STRATEGY_REGISTRY[name]["domain"] == domain
            or STRATEGY_REGISTRY[name]["domain"] == "all"
        ]

        # Prioritize by question type
        question_lower = question.lower()

        priority_map = {
            "decision_matrix": any(
                kw in question_lower for kw in [
                    "should i", "should we", "choice", "option", "pros and cons",
                    "tradeoff", "between", "or ", "either", "neither",
                ]
            ),
            "pre_mortem": any(
                kw in question_lower for kw in [
                    "risk", "fail", "danger", "what if", "worst case",
                    "pivot", "quit", "drop", "leave", "stop",
                ]
            ),
            "second_order": any(
                kw in question_lower for kw in [
                    "long term", "future", "consequence", "then what",
                    "after that", "down the line", "cascade", "ripple",
                ]
            ),
            "six_hats": any(
                kw in question_lower for kw in [
                    "analyze", "evaluate", "assess", "review", "think about",
                    "perspective", "viewpoint", "angle",
                ]
            ),
            "scampER": any(
                kw in question_lower for kw in [
                    "idea", "creative", "innovate", "new approach", "brainstorm",
                    "alternative", "different", "improve", "enhance",
                ]
            ),
            "devils_advocate": any(
                kw in question_lower for kw in [
                    "challenge", "flaw", "weakness", "problem with",
                    "is this right", "am i wrong", "blind spot",
                ]
            ),
            "first_principles": any(
                kw in question_lower for kw in [
                    "fundamental", "why", "root cause", "break down",
                    "first principle", "essence", "core",
                ]
            ),
            "inversion": any(
                kw in question_lower for kw in [
                    "avoid", "prevent", "mistake", "don't", "wrong",
                    "failure", "bad", "dangerous",
                ]
            ),
            "swot": any(
                kw in question_lower for kw in [
                    "business", "startup", "company", "market", "compete",
                    "strength", "weakness", "opportunity", "threat",
                ]
            ),
            "tradeoff_matrix": any(
                kw in question_lower for kw in [
                    "tradeoff", "trade off", "sacrifice", "give up",
                    "cost", "benefit", "worth it",
                ]
            ),
            "edge_case_analysis": any(
                kw in question_lower for kw in [
                    "code", "function", "class", "bug", "error", "edge case",
                    "boundary", "null", "empty", "overflow",
                ]
            ),
            "lateral_thinking": any(
                kw in question_lower for kw in [
                    "creative", "unusual", "out of the box", "lateral",
                    "random", "unexpected", "wild card",
                ]
            ),
        }

        scored = []
        for name in available:
            score = 1.0
            for kw, matches in priority_map.items():
                if name == kw and matches:
                    score += 3.0
            scored.append((name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored[:max_strategies]]

    def _run_strategies_parallel(
        self, strategy_names: List[str], question: str, domain: str
    ) -> List[StrategyResult]:
        """Run multiple strategies in parallel using ThreadPoolExecutor."""
        results = []

        def _run_strategy(name: str) -> StrategyResult:
            strategy_info = STRATEGY_REGISTRY[name]
            prompt_template = STRATEGY_PROMPTS.get(
                strategy_info["prompt_key"],
                STRATEGY_PROMPTS["six_hats"],
            )
            prompt = prompt_template.format(question=question, domain=domain)

            try:
                response = llm.simple_chat(
                    user_message=prompt,
                    system_prompt=THINKING_SYSTEM_PROMPT,
                )
                return StrategyResult(
                    strategy_name=name,
                    domain=domain,
                    category=strategy_info["category"],
                    analysis=response.strip(),
                    confidence=0.7,
                    key_insight=self._extract_key_insight(response),
                    recommendation=self._extract_recommendation(response),
                )
            except Exception as e:
                logger.warning(f"Thinking strategy '{name}' failed: {e}")
                return StrategyResult(
                    strategy_name=name,
                    domain=domain,
                    category=strategy_info["category"],
                    analysis=f"Strategy failed: {e}",
                    confidence=0.0,
                    key_insight="",
                    recommendation="",
                )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(strategy_names), 4)
        ) as executor:
            futures = {
                executor.submit(_run_strategy, name): name
                for name in strategy_names
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result(timeout=THINKING_TIMEOUT)
                    results.append(result)
                except concurrent.futures.TimeoutError:
                    name = futures[future]
                    logger.warning(f"Thinking strategy '{name}' timed out")
                    results.append(
                        StrategyResult(
                            strategy_name=name,
                            domain=domain,
                            category=STRATEGY_REGISTRY[name]["category"],
                            analysis="Strategy timed out.",
                            confidence=0.0,
                            key_insight="",
                            recommendation="",
                        )
                    )
                except Exception as e:
                    name = futures[future]
                    logger.warning(f"Thinking strategy '{name}' error: {e}")
                    results.append(
                        StrategyResult(
                            strategy_name=name,
                            domain=domain,
                            category=STRATEGY_REGISTRY[name]["category"],
                            analysis=f"Strategy error: {e}",
                            confidence=0.0,
                            key_insight="",
                            recommendation="",
                        )
                    )

        return results

    def _synthesize(
        self, question: str, domain: str, results: List[StrategyResult]
    ) -> str:
        """Synthesize multiple strategy results into one answer."""
        if not results:
            return ""

        # Build synthesis prompt
        strategy_summaries = []
        for r in results:
            if r.confidence > 0:
                strategy_summaries.append(
                    f"[{r.strategy_name}] (confidence: {r.confidence:.0%})\n"
                    f"Key insight: {r.key_insight}\n"
                    f"Recommendation: {r.recommendation}\n"
                    f"Full analysis:\n{r.analysis[:800]}"
                )

        if not strategy_summaries:
            return "I couldn't get reliable analysis from any strategy."

        synthesis_prompt = (
            f"Question: {question}\n\n"
            f"Here are analyses from multiple thinking strategies:\n\n"
            + "\n\n---\n\n".join(strategy_summaries)
            + "\n\nSynthesize these into a clear, direct answer. Lead with the conclusion, then the key reasons. Be strict yet warm. Point at what matters most."
        )

        try:
            response = llm.simple_chat(
                user_message=synthesis_prompt,
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            )
            return response.strip()
        except Exception as e:
            logger.warning(f"Synthesis failed: {e}")
            # Fallback: concatenate key insights
            insights = [r.key_insight for r in results if r.key_insight]
            if insights:
                return "Based on the analysis:\n\n" + "\n".join(f"- {i}" for i in insights[:5])
            return "I ran multiple analyses but couldn't synthesize a clear answer."

    def _extract_key_insight(self, analysis: str) -> str:
        """Extract the key insight from a strategy analysis."""
        lines = analysis.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and len(line) > 20 and len(line) < 300:
                if any(kw in line.lower() for kw in [
                    "recommend", "suggest", "should", "key", "important",
                    "critical", "main", "primary", "best", "worst",
                ]):
                    return line[:300]
        return lines[0].strip()[:300] if lines else ""

    def _extract_recommendation(self, analysis: str) -> str:
        """Extract the recommendation from a strategy analysis."""
        lines = analysis.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and any(kw in line.lower() for kw in [
                "recommend", "suggest", "should do", "best option",
                "go with", "choose", "pick", "do this",
            ]):
                return line[:300]
        return ""

    def _result_to_dict(self, result: StrategyResult) -> Dict:
        return {
            "strategy": result.strategy_name,
            "domain": result.domain,
            "category": result.category,
            "analysis": result.analysis,
            "confidence": result.confidence,
            "key_insight": result.key_insight,
            "recommendation": result.recommendation,
        }


thinking_engine = ThinkingEngine()
