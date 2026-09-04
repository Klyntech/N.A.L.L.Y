"""Nally Core Agent - The Brain"""

import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional

from ..config import CONTEXT_MAX_TOKENS as MAX_CONTEXT_TOKENS
from ..config import MAX_ITERATIONS_PER_TURN, SESSION_ID, get_system_prompt
from ..core.errors import LLMError, NallyError
from ..memory import memory_store
from ..utils.logger import logger
from .router import matcher


def _strip_emojis(text: str) -> str:
    """Remove emojis and special unicode symbols from text"""
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
    """Capitalize the first letter of every sentence."""
    return re.sub(
        r"(^|[.!?]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )


_TIME_SENSITIVE_PATTERNS = [
    r"this\s+(season|year|month|week|weekend)",
    r"(20\d{2})\s*[-–]\s*(20\d{2})",
    r"(match|matches|result|score|fixture|standing|league|table|rank)",
    r"(news|latest|recent|current|update)",
    r"(price|stock|rate|weather|temperature|forecast)",
    r"(who\s+won|final\s+score)",
    r"(upcoming|next|schedule)",
    r"(release\s+date|when\s+does)",
]


def _needs_web_search(query: str) -> bool:
    """Check if query looks time-sensitive and needs web search context."""
    q = query.lower()
    return any(re.search(p, q) for p in _TIME_SENSITIVE_PATTERNS)


def _extract_topics(user_msgs: List[str]) -> List[str]:
    """Extract conversation topics from user messages."""
    topic_keywords = {
        "deployment": ["deploy", "render", "server", "hosting"],
        "coding": ["code", "function", "class", "import", "api"],
        "memory": ["memory", "remember", "recall", "forget"],
        "frontend": ["widget", "ui", "frontend", "css", "html"],
        "debugging": ["fix", "bug", "error", "issue"],
        "devops": ["docker", "ci", "pipeline", "git"],
        "ai": ["agent", "llm", "model", "ai"],
    }
    topics = []
    for msg in user_msgs[-10:]:
        msg_lower = msg.lower()
        for topic, keywords in topic_keywords.items():
            if any(w in msg_lower for w in keywords) and topic not in topics:
                topics.append(topic)
    return topics[:3] or ["general"]


class NallyAgent:
    def __init__(self, session_id: Optional[str] = None, channel: Optional[str] = None, route_key: Optional[str] = None):
        self.messages: List[dict] = []
        self._session_id = session_id or SESSION_ID
        # Human-facing channel label (e.g. "Telegram voice call"). Explicit
        # instead of sniffed from the session-id prefix, since one shared
        # session ("user:{owner}") is reached from many channels.
        self._channel = channel
        # Per-channel route key for history isolation (Telegram vs Web).
        # Same brain (session_id) but different chat logs.
        self._route_key = route_key or self._session_id
        # Stable abort key. Must equal the session id used by set_abort()
        # (web/ws handlers) so abort flags match the graph's checks. The
        # graph appends a uuid suffix and registers it as an alias back to
        # this value in core/abort.py.
        self._thread_id = self._session_id
        self._lock = threading.Lock()
        self._init_conversation()
        self._load_history()

        # Background memory decay
        threading.Thread(target=self._bg_memory_decay, daemon=True).start()

    def _bg_memory_decay(self):
        """Run memory decay and reset stale facts on startup."""
        try:
            memory_store.reset_stale_facts()
            memory_store.decay_old_memories()
        except Exception as e:
            logger.debug(f"Memory decay failed: {e}")

    def _init_conversation(self):
        """Initialize conversation with system prompt + memory context."""
        user_context = None

        try:
            user_facts = memory_store.get_user_facts()
            if user_facts and user_facts != "No user facts stored yet.":
                user_context = user_facts
        except Exception as e:
            logger.debug(f"Failed to load user facts: {e}")

        try:
            convo_summaries = memory_store.get_conversation_summaries_text(3)
            if convo_summaries:
                if user_context:
                    user_context += f"\n\n{convo_summaries}"
                else:
                    user_context = convo_summaries
        except Exception as e:
            logger.debug(f"Failed to load conversation summaries: {e}")

        try:
            episodes_text = memory_store.get_recent_episodes_text(3)
            if episodes_text:
                if user_context:
                    user_context += f"\n\n{episodes_text}"
                else:
                    user_context = episodes_text
        except Exception as e:
            logger.debug(f"Failed to load recent episodes: {e}")

        system_content = get_system_prompt(
            user_context=user_context, interface=self._channel or self._session_id
        )

        self.messages = [{"role": "system", "content": system_content, "cache_control": {"type": "ephemeral"}}]

    def _load_history(self):
        """Load conversation history from database on startup (per-channel)."""
        try:
            saved = memory_store.load_messages(self._session_id, route_key=self._route_key)
            if saved:
                system_msg = self.messages[0] if self.messages else None
                if system_msg:
                    self.messages = [system_msg] + saved
                else:
                    self.messages = saved

                # Prune loaded history immediately to avoid context overflow
                from .context import context_manager

                self.messages = context_manager.prune(self.messages, max_tokens=MAX_CONTEXT_TOKENS)

                logger.debug(f"Loaded {len(saved)} messages from session {self._session_id} route {self._route_key}")
        except Exception as e:
            logger.debug(f"No saved history to load: {e}")

    def _save_history(self):
        """Save conversation history to database on shutdown (per-channel)."""
        try:
            saveable = [m for m in self.messages if m.get("role") != "system"]
            if len(saveable) > 1:
                memory_store.save_messages(saveable, self._session_id, route_key=self._route_key)
                logger.debug(f"Saved {len(saveable)} messages to session {self._session_id} route {self._route_key}")
        except Exception as e:
            logger.debug(f"Failed to save history: {e}")

    def _emit(self, callback: Optional[Callable], event: str, data: dict):
        """Emit a streaming event if callback is provided."""
        if callback:
            try:
                callback(event, data)
            except Exception:
                pass

    def process(self, user_input: str, emit: Optional[Callable] = None) -> str:
        """Process user input and return response."""
        logger.user_input(user_input)
        start = time.time()

        # Skip local patterns for compound requests and research commands
        compound_indicators = [" and ", " then ", " also ", " plus ", " with "]
        research_commands = ["deep research", "quick search", "read article", "list reports"]
        is_compound = any(ind in user_input.lower() for ind in compound_indicators)
        is_research = any(cmd in user_input.lower() for cmd in research_commands)

        if not is_compound and not is_research:
            handler = matcher.match(user_input)
            if handler:
                try:
                    result = handler()
                except NallyError as e:
                    logger.error_with_context("Local handler error", e)
                    result = e.to_llm_format()
                except Exception as e:
                    logger.error_with_context("Local handler error", e)
                    result = f"Error: {e!s}"

                if result == "__EXIT__":
                    self._save_history()
                    return "__EXIT__"

                elapsed = (time.time() - start) * 1000
                result = _capitalize_sentences(_strip_emojis(result))
                logger.nally_response(result)
                logger.debug(f"Response time: {elapsed:.0f}ms (local)")
                self._save_history()
                return result

        return self._llm_process(user_input, emit)

    def _llm_process(self, user_input: str, emit: Optional[Callable] = None) -> str:
        """Process using LLM with LangGraph agent loop."""
        from ..tools.registry import registry
        from .context import context_manager
        from .graph import run_agent

        start = time.time()

        # Prefix user message with temporal context (no extra messages accumulated)
        now = datetime.now(timezone.utc)
        ts_prefix = f"[Current time: {now.strftime('%Y-%m-%d %H:%M UTC')} | Day: {now.strftime('%A')}]\n\n"

        # ── Input Guardrails ──
        try:
            from .guardrails import guardrail_engine
            input_results = guardrail_engine.check_input(user_input)
            if guardrail_engine.should_block(input_results):
                blocked_msg = "I can't process that request. It appears to be outside my scope."
                for r in input_results:
                    if r.verdict.value == "block":
                        blocked_msg = f"I can't process that request: {r.message}"
                        break
                self.messages.append({"role": "user", "content": ts_prefix + user_input})
                self.messages.append({"role": "assistant", "content": blocked_msg})
                self._save_history()
                return blocked_msg
        except Exception as e:
            logger.debug(f"Input guardrails skipped: {e}")

        self.messages.append({"role": "user", "content": ts_prefix + user_input})

        # ── Harness v2: Intent Classification ──
        _classification = None
        _scratchpad = None
        try:
            from ..config import HARNESS_ENABLED, HARNESS_LOG_CLASSIFICATIONS, HARNESS_SCRATCHPAD_ENABLED
            if HARNESS_ENABLED:
                from .harness import classify_intent, get_pipeline_config
                from .llm import llm as _harness_llm
                def _harness_llm_call(messages, temperature=0.0, **kwargs):
                    # messages is OpenAI-style list; extract last user + first system
                    try:
                        user_msg = messages[-1].get("content", "") if messages else user_input
                        sys_prompt = None
                        if messages and messages[0].get("role") == "system":
                            sys_prompt = messages[0].get("content")
                        return _harness_llm.simple_chat(
                            user_message=user_msg,
                            system_prompt=sys_prompt,
                        )
                    except Exception as e:
                        logger.warning(f"Harness LLM call failed: {e}")
                        raise
                _classification = classify_intent(user_input, llm_call_fn=_harness_llm_call)
                if HARNESS_LOG_CLASSIFICATIONS:
                    logger.info(
                        f"Intent classified: {_classification.task_class.value} "
                        f"(conf={_classification.confidence:.2f}, method={_classification.method})"
                    )
                self._last_classification = _classification

                # TaskRouter: automatic strategy (no user plan toggle)
                try:
                    from .task_router import route_from_classification

                    _route = route_from_classification(_classification, user_text=user_input)
                    self._last_route = _route
                    logger.info(
                        "TaskRouter strategy=%s (class=%s conf=%.2f)",
                        _route.strategy.value,
                        _route.task_class or "-",
                        _route.confidence,
                    )
                except Exception as _tr_err:
                    logger.debug("TaskRouter skipped: %s", _tr_err)
                    self._last_route = None

                # Create scratchpad per pipeline config
                if HARNESS_ENABLED and _classification:
                    from .harness import get_pipeline_config
                    pipeline_cfg = get_pipeline_config(_classification.task_class)
                    if (
                        HARNESS_SCRATCHPAD_ENABLED
                        and pipeline_cfg.scratchpad
                        and _classification.task_class.value
                        in ("COMPLEX", "CREATIVE", "HIGH_STAKES")
                    ):
                        from .scratchpad import Scratchpad, scratchpad_store
                        _scratchpad = Scratchpad(objective=user_input)
                        scratchpad_store.save(_scratchpad)
                        logger.info(f"Scratchpad created: {_scratchpad.id}")
        except Exception as e:
            logger.warning(f"Harness classification failed: {e}")

        # Skill activation (Level 2): check if a skill matches this request
        try:
            from ..skills.registry import skill_registry
            from ..tools.permissions import gate as perm_gate

            if not skill_registry._loaded:
                skill_registry.load()
            matched = skill_registry.find_by_intent(user_input)
            if matched:
                skill_body = skill_registry.activate(matched[0])
                skill_obj = skill_registry.get(matched[0])
                if skill_body:
                    self.messages.append(
                        {
                            "role": "system",
                            "content": f"[SKILL ACTIVATED: {matched[0]}]\n\n{skill_body}\n\nFollow these instructions for this task.",
                        }
                    )
                    # Grant skill's allowed-tools temporarily
                    if skill_obj and skill_obj.allowed_tools:
                        perm_gate.set_skill_overrides(matched[0], skill_obj.allowed_tools)
        except Exception as e:
            logger.warning(f"Skill activation failed: {e}")

        # Gate skill injection: only for creation requests, not questions
        def _is_creation_request(text: str) -> bool:
            """Check if user is asking to create/build something vs asking a question."""
            question_patterns = [
                r"what('s| is| are) your",
                r"how (long|much|would)",
                r"timeline",
                r"cost",
                r"price",
                r"recommend",
                r"tech stack",
                r"hire you",
                r"estimated",
                r"budget",
                r"what (do|would) you (charge|suggest|advise)",
            ]
            text_lower = text.lower()
            for pattern in question_patterns:
                if re.search(pattern, text_lower):
                    return False
            return True

        # Auto-inject design skills for code/creative tasks (skip for questions)
        _CODE_KEYWORDS = [
            "create",
            "build",
            "make",
            "design",
            "frontend",
            "website",
            "page",
            "html",
            "css",
            "javascript",
            "component",
            "landing",
            "ui",
            "interface",
            "layout",
            "page",
            "form",
            "dashboard",
            "app",
            "template",
        ]
        if _is_creation_request(user_input) and any(kw in user_input.lower() for kw in _CODE_KEYWORDS):
            try:
                from ..skills.registry import skill_registry

                if not skill_registry._loaded:
                    skill_registry.load()
                for skill_name in ["ui-design", "design-system"]:
                    skill_obj = skill_registry.get(skill_name)
                    if skill_obj and skill_obj.body:
                        self.messages.insert(
                            1, {"role": "system", "content": f"[SKILL REFERENCE: {skill_name}]\n\n{skill_obj.body}"}
                        )
            except Exception as e:
                logger.warning(f"Design skill injection failed: {e}")

        # Smart context management — single pass
        self.messages = context_manager.prune(self.messages, max_tokens=MAX_CONTEXT_TOKENS)
        self.messages = context_manager.compact(self.messages)

        # Memory and history injections
        self.messages = context_manager.inject_memories(user_input, self.messages)
        self.messages = context_manager.inject_conversation_history(self.messages)

        # Final safety check: prune once more if injections pushed us over
        estimated = context_manager.estimate_tokens(self.messages)
        if estimated > MAX_CONTEXT_TOKENS:
            logger.warning(f"Context over limit after injections ({estimated} tokens), final prune")
            self.messages = context_manager.prune(self.messages, max_tokens=MAX_CONTEXT_TOKENS)

        # Build tool set — pass task class for broader selection on complex tasks
        try:
            from ..tools.filter import tool_filter

            if not tool_filter._ready:
                tool_filter.build_index(registry.tools)
            _task_class = _classification.task_class.value if _classification else ""
            tools = tool_filter.select(user_input, task_class=_task_class)
        except ImportError:
            tools = [t.to_openai_schema() for t in registry.tools.values()]

        # Auto-search for time-sensitive queries — inject fresh web data
        # so the LLM sees real results regardless of whether it calls web_search
        # Skip for benchmark sessions so the test can measure explicit web_search tool use
        if _needs_web_search(user_input) and not self._session_id.startswith("bench_"):
            try:
                from ..tools.websearch import WebSearch

                ws = WebSearch()
                results = ws.execute(query=user_input, num_results=3)
                if results:
                    self.messages.insert(
                        1, {"role": "system", "content": f"[Auto-searched web for '{user_input}']:\n{results}"}
                    )
            except Exception:
                pass  # fallback to LLM's own knowledge

        try:
            _intent_class = ""
            _intent_confidence = 0.0
            if _classification:
                _intent_class = _classification.task_class.value
                _intent_confidence = _classification.confidence

            # Inject scratchpad context for COMPLEX/HIGH_STAKES tasks
            if _scratchpad and _classification.task_class.value in ("COMPLEX", "HIGH_STAKES"):
                self.messages.insert(
                    1,
                    {"role": "system", "content": f"[SCRATCHPAD] Objective: {_scratchpad.objective}\nConstraints: {_scratchpad.constraints or ''}"},
                )

            # Confirmation gate: force plan-before-execute for complex tasks
            if _classification and _classification.task_class.value in ("COMPLEX", "HIGH_STAKES"):
                self.messages.insert(
                    1,
                    {
                        "role": "system",
                        "content": (
                            "[EXECUTION MODE: PLAN FIRST]\n"
                            "This task is classified as COMPLEX or HIGH_STAKES.\n"
                            "BEFORE executing any tool calls, you MUST:\n"
                            "1. Present a brief plan (3-5 bullet points) of what you will do\n"
                            "2. Ask the user: 'Should I proceed?'\n"
                            "3. WAIT for user confirmation before executing\n"
                            "4. If the user says yes/proceed/go, execute the plan\n"
                            "5. If the user says no/cancel/stop, stop and ask what they want instead\n\n"
                            "Do NOT start executing tools until the user confirms. "
                            "The plan should be concise — one line per step."
                        ),
                    },
                )

            # ── Auto-inject task state on "continue" ──
            # When the user says continue/resume/pick up, check for saved task state
            # and inject it so Nally doesn't re-read everything from scratch.
            _continue_patterns = [
                r"^(continue|resume|pick up|keep going|go on|where (was|i was|we were) i|what (was|i was|were) (i|we) (doing|working on))",
                r"^( carry on| proceed| keep going)",
            ]
            _is_continue = any(re.search(p, user_input.lower().strip()) for p in _continue_patterns)
            if _is_continue:
                try:
                    from ..tools.task_state import task_state_manager
                    saved_state = task_state_manager.get(self._session_id)
                    if saved_state and saved_state.status == "in_progress":
                        state_context = task_state_manager.format_for_prompt(saved_state)
                        self.messages.insert(
                            1,
                            {"role": "system", "content": state_context},
                        )
                        logger.info(
                            f"Task state injected for resume: {saved_state.task_description[:60]} "
                            f"({len(saved_state.files_created)} files, {len(saved_state.pending_steps)} pending steps)"
                        )
                except Exception as e:
                    logger.debug(f"Task state auto-injection skipped: {e}")

            final_response = run_agent(
                messages=self.messages,
                tools=tools,
                emit=emit,
                max_iterations=MAX_ITERATIONS_PER_TURN,
                thread_id=self._thread_id,
                intent_class=_intent_class,
                intent_confidence=_intent_confidence,
            )

            # ── Harness v2: Critique Pipeline (Phase 2) ──
            try:
                from ..config import HARNESS_ENABLED, HARNESS_CRITIQUE_ENABLED
                if (
                    HARNESS_ENABLED
                    and HARNESS_CRITIQUE_ENABLED
                    and _classification
                    and _classification.task_class.value in ("COMPLEX", "CREATIVE")
                ):
                    from .harness import (
                        TaskClass,
                        run_critique_pipeline,
                    )
                    from .llm import llm as _harness_llm

                    def _harness_llm_call(messages, temperature=0.7, **kwargs):
                        try:
                            user_msg = messages[-1].get("content", "") if messages else ""
                            sys_prompt = None
                            if messages and messages[0].get("role") == "system":
                                sys_prompt = messages[0].get("content")
                            return _harness_llm.simple_chat(
                                user_message=user_msg,
                                system_prompt=sys_prompt,
                            )
                        except Exception as e:
                            logger.warning(f"Harness LLM critique call failed: {e}")
                            raise

                    critique_result = run_critique_pipeline(
                        user_request=user_input,
                        task_class=_classification.task_class,
                        llm_call_fn=_harness_llm_call,
                        existing_response=final_response,
                        context_messages=self.messages[:-1],
                    )
                    if critique_result.was_revised:
                        final_response = critique_result.response
                        logger.info(
                            f"Critique pipeline revised response "
                            f"(stages={critique_result.stages_fired}, "
                            f"latency={critique_result.cost_latency_ms:.0f}ms)"
                        )
                    if emit:
                        try:
                            emit("critique", critique_result.to_dict())
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Critique pipeline failed: {e}")

            final_response = _capitalize_sentences(_strip_emojis(final_response))
            self.messages.append({"role": "assistant", "content": final_response})

            # Clear skill overrides after task completion
            try:
                from ..tools.permissions import gate as perm_gate

                perm_gate.clear_all_skill_overrides()
            except Exception as e:
                logger.warning(f"Failed to clear skill overrides: {e}")

            elapsed = (time.time() - start) * 1000
            logger.nally_response(final_response)
            logger.debug(f"Total response time: {elapsed:.0f}ms")

            # ── Harness v2: Scratchpad Write-back (Phase 3) ──
            if _scratchpad:
                try:
                    from .scratchpad import scratchpad_store
                    _scratchpad.add_result(f"Task completed: {final_response[:200]}")
                    _scratchpad.status = "completed"
                    scratchpad_store.save(_scratchpad)

                    # Deliberate write-back to long-term memory
                    suggestions = _scratchpad.suggest_long_term_writes()
                    for s in suggestions:
                        try:
                            from ..memory import memory_store as _scratch_mem
                            _scratch_mem.remember(
                                key=s["key"],
                                value=s["value"],
                                category=s.get("category", "auto_fact"),
                                confidence=0.6,
                            )
                        except Exception:
                            pass
                    if suggestions:
                        logger.info(f"Scratchpad write-back: {len(suggestions)} items to long-term memory")
                except Exception as e:
                    logger.warning(f"Scratchpad write-back failed: {e}")

            self._save_history()
            self._maybe_create_episode(user_input, final_response)
            self._maybe_extract_facts(user_input)

            # Periodic auto-save summary every 20 messages
            if len(self.messages) % 20 == 0 and len(self.messages) > 10:
                self._auto_save_summary()

            return final_response

        except LLMError as e:
            logger.error_with_context("LLM processing failed", e)
            error_msg = e.to_llm_format()
            self.messages.append({"role": "assistant", "content": error_msg})
            self._save_history()
            return error_msg

        except NallyError as e:
            logger.error_with_context("Processing failed", e)
            error_msg = e.to_llm_format()
            self.messages.append({"role": "assistant", "content": error_msg})
            self._save_history()
            return error_msg

        except Exception as e:
            logger.error_with_context("Processing failed", e)
            error_msg = f"I encountered an error: {e!s}"
            self.messages.append({"role": "assistant", "content": error_msg})
            self._save_history()
            return error_msg

    def _maybe_create_episode(self, user_input: str, response: str):
        """Auto-create episode for conversations with substance."""
        if len(self.messages) <= 4:
            return
        try:
            user_msgs = [m["content"] for m in self.messages if m.get("role") == "user"]
            if not user_msgs:
                return
            last_user = user_msgs[-1]
            tools_used = []
            for m in self.messages:
                if isinstance(m, dict) and m.get("role") == "tool":
                    name = m.get("name", "unknown")
                    if name not in tools_used:
                        tools_used.append(name)
            recent_context = " | ".join([m[:60] for m in user_msgs[-3:]])
            topics = _extract_topics(user_msgs)
            memory_store.add_episode(
                topic=last_user[:50],
                what_happened=f"Context: {recent_context}",
                outcome=response[:300] if response else "completed",
                solution=f"Tools: {','.join(tools_used[:5])}" if tools_used else "direct response",
                tags=tools_used[:5] + topics,
            )
        except Exception as e:
            logger.debug(f"Episode creation failed: {e}")

    _ENTITY_PATTERNS = [
        (r"(?:built|created|made|developed|designed|built)\s+(?:a\s+|an\s+|the\s+)?(.+?)(?:\s+called|\s+named|\s+for|\s+that|\s+which|\s*[,.]|$)", "project"),
        (r"(?:my|the)\s+(project|app|bot|tool|site|platform|system)\s+(?:is\s+)?(.+?)(?:\s*[,.]|$)", "project"),
        (r"(?:working on|building|developing)\s+(?:a\s+|an\s+|the\s+)?(.+?)(?:\s+[,.]|$)", "project"),
    ]

    def _maybe_extract_facts(self, user_input: str):
        """Lightweight per-turn fact extraction — no LLM call, just regex."""
        if not user_input or len(user_input) < 10:
            return
        try:
            import re
            text = user_input.lower()
            # Only trigger on entity-mention keywords
            trigger_words = ("built", "created", "made", "project", "app", "bot", "tool", "site",
                             "working on", "building", "developing", "launched", "renamed", "called")
            if not any(w in text for w in trigger_words):
                return

            for pattern, category in self._ENTITY_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    groups = [g.strip() for g in match.groups() if g and len(g.strip()) > 2]
                    if groups:
                        key = groups[0][:80]
                        value = " ".join(groups)[:200]
                        # Don't duplicate if already stored
                        existing = memory_store.recall(key=key)
                        if not existing:
                            memory_store.remember(key=key, value=value, category=category, confidence=0.7)
                            logger.debug(f"Auto-stored fact: {key} = {value}")
                        break
        except Exception as e:
            logger.debug(f"Fact extraction failed: {e}")

    def _auto_save_summary(self):
        """Periodically save conversation summary without clearing."""
        try:
            user_msgs = [m["content"] for m in self.messages if m["role"] == "user"]
            if len(user_msgs) >= 3:
                summary = " | ".join(user_msgs[-5:])
                topics = _extract_topics(user_msgs)
                memory_store.save_conversation(summary=summary, topics=topics, message_count=len(user_msgs))
        except Exception:
            pass

    def clear_history(self):
        """Clear conversation history and save summary."""
        self._save_history()

        if len(self.messages) > 2:
            user_msgs = [m["content"] for m in self.messages if m["role"] == "user"]
            if user_msgs:
                summary = " | ".join(user_msgs[-5:])
                topics = _extract_topics(user_msgs)
                try:
                    memory_store.save_conversation(
                        summary=summary,
                        topics=topics,
                        message_count=len(user_msgs),
                    )
                    logger.debug(f"Saved conversation: {topics}")
                except Exception as e:
                    logger.warning(f"Failed to save conversation: {e}")

        logger.debug("Conversation history cleared")
        self._init_conversation()

    def get_history(self) -> List[dict]:
        """Get conversation history."""
        return self.messages


# Lazy singleton — use get_agent() instead of importing agent directly
_agent_instance: Optional[NallyAgent] = None
_agent_lock = threading.Lock()


def get_agent() -> NallyAgent:
    """Get or create the singleton NallyAgent instance (thread-safe).

    Defaults to the owner's shared brain session so CLI turns land in the
    same cross-platform history as web/Telegram/voice (identity, not channel).
    """
    global _agent_instance
    if _agent_instance is None:
        with _agent_lock:
            if _agent_instance is None:
                from .identity import owner_session_id

                _agent_instance = NallyAgent(
                    session_id=owner_session_id(), channel="CLI"
                )
    return _agent_instance
