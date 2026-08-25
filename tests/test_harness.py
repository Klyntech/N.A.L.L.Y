"""Tests for Nally Harness v2 — Intent Classifier, Critique, and Scratchpad."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nally.agent.harness import (
    Classification,
    PipelineConfig,
    TaskClass,
    _classify_regex,
    classify_by_llm,
    classify_intent,
    get_pipeline_config,
)


# ── Regex Classifier ──────────────────────────────────────


class TestRegexClassifier:
    """Test the fast regex-based classification."""

    def test_greeting_is_simple(self):
        result = _classify_regex("hello")
        assert result.task_class == TaskClass.SIMPLE
        assert result.method == "regex"

    def test_thanks_is_simple(self):
        result = _classify_regex("thanks!")
        assert result.task_class == TaskClass.SIMPLE

    def test_short_question_is_knowledge(self):
        result = _classify_regex("what time is it")
        assert result.task_class == TaskClass.KNOWLEDGE

    def test_how_question_is_knowledge(self):
        result = _classify_regex("how are you")
        assert result.task_class == TaskClass.KNOWLEDGE

    def test_deploy_is_high_stakes(self):
        result = _classify_regex("deploy to production")
        assert result.task_class == TaskClass.HIGH_STAKES
        assert result.confidence >= 0.7

    def test_delete_database_is_high_stakes(self):
        result = _classify_regex("delete the production database")
        assert result.task_class == TaskClass.HIGH_STAKES

    def test_security_is_high_stakes(self):
        result = _classify_regex("fix the security vulnerability in auth")
        assert result.task_class == TaskClass.HIGH_STAKES

    def test_write_story_is_creative(self):
        result = _classify_regex("write a story about a robot")
        assert result.task_class == TaskClass.CREATIVE

    def test_draft_email_is_creative(self):
        result = _classify_regex("draft a blog post about AI")
        assert result.task_class == TaskClass.CREATIVE

    def test_explain_is_knowledge(self):
        result = _classify_regex("explain how neural networks work")
        assert result.task_class == TaskClass.KNOWLEDGE

    def test_compare_is_knowledge(self):
        result = _classify_regex("difference between TCP and UDP")
        assert result.task_class == TaskClass.KNOWLEDGE

    def test_build_project_is_complex(self):
        result = _classify_regex("build a full-stack web app with React and Node.js")
        assert result.task_class == TaskClass.COMPLEX

    def test_integrate_systems_is_complex(self):
        result = _classify_regex(
            "integrate Slack notifications with our CI/CD pipeline "
            "and set up webhook handlers for all build events"
        )
        assert result.task_class == TaskClass.COMPLEX

    def test_truly_ambiguous_is_ambiguous(self):
        result = _classify_regex(
            "maybe something with the data pipeline but I'm not entirely sure "
            "what exactly needs to change or if we should even touch it right now "
            "because there are several possible approaches and I haven't decided yet"
        )
        assert result.task_class == TaskClass.AMBIGUOUS

    def test_method_is_always_regex(self):
        result = _classify_regex("hello")
        assert result.method == "regex"


# ── LLM Classifier ────────────────────────────────────────


class TestLLMClassifier:
    """Test LLM-based classification with mocked LLM."""

    def test_parses_valid_json(self):
        mock_llm = MagicMock(return_value=json.dumps({
            "class": "COMPLEX",
            "confidence": 0.9,
            "reasoning": "Multi-step deployment task",
        }))
        result = classify_by_llm("deploy the app to AWS", mock_llm)
        assert result.task_class == TaskClass.COMPLEX
        assert result.confidence == 0.9
        assert result.method == "llm"

    def test_falls_back_on_invalid_json(self):
        mock_llm = MagicMock(return_value="not json at all")
        result = classify_by_llm("deploy the app", mock_llm)
        assert result.method == "regex"  # fell back

    def test_falls_back_on_unknown_class(self):
        mock_llm = MagicMock(return_value=json.dumps({
            "class": "UNKNOWN",
            "confidence": 0.5,
            "reasoning": "test",
        }))
        result = classify_by_llm("deploy the app", mock_llm)
        assert result.method == "regex"  # fell back

    def test_falls_back_on_exception(self):
        mock_llm = MagicMock(side_effect=Exception("API error"))
        result = classify_by_llm("deploy the app", mock_llm)
        assert result.method == "regex"

    def test_passes_correct_messages(self):
        mock_llm = MagicMock(return_value=json.dumps({
            "class": "SIMPLE",
            "confidence": 0.95,
            "reasoning": "greeting",
        }))
        classify_by_llm("hello", mock_llm)
        call_args = mock_llm.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "hello" in messages[1]["content"]

    def test_truncates_long_input(self):
        mock_llm = MagicMock(return_value=json.dumps({
            "class": "SIMPLE",
            "confidence": 0.9,
            "reasoning": "test",
        }))
        long_text = "x " * 5000
        classify_by_llm(long_text, mock_llm)
        call_args = mock_llm.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        # Input should be truncated to 2000 chars
        assert len(messages[1]["content"]) < 3000


# ── classify_intent Public API ────────────────────────────


class TestClassifyIntent:
    """Test the public classify_intent function."""

    def test_regex_only_mode(self):
        result = classify_intent("hello")
        assert result.task_class == TaskClass.SIMPLE
        assert result.method == "regex"

    def test_override_bypasses_classification(self):
        result = classify_intent("hello", override="COMPLEX")
        assert result.task_class == TaskClass.COMPLEX
        assert result.method == "override"
        assert result.confidence == 1.0

    def test_invalid_override_classifies_normally(self):
        result = classify_intent("hello", override="INVALID")
        assert result.task_class == TaskClass.SIMPLE
        assert result.method == "regex"

    def test_llm_mode_when_provided(self):
        mock_llm = MagicMock(return_value=json.dumps({
            "class": "CREATIVE",
            "confidence": 0.85,
            "reasoning": "creative writing task",
        }))
        result = classify_intent("write a poem about rain", llm_call_fn=mock_llm)
        assert result.task_class == TaskClass.CREATIVE
        assert result.method == "llm"


# ── Pipeline Config ───────────────────────────────────────


class TestPipelineConfig:
    """Test pipeline configuration retrieval."""

    def test_simple_pipeline(self):
        config = get_pipeline_config(TaskClass.SIMPLE)
        assert config.direct_answer is True
        assert config.critique is False
        assert config.scratchpad is False
        assert config.tool_verify is False

    def test_complex_pipeline(self):
        config = get_pipeline_config(TaskClass.COMPLEX)
        assert config.direct_answer is False
        assert config.critique is True
        assert config.scratchpad is True
        assert config.tool_verify is True

    def test_creative_pipeline(self):
        config = get_pipeline_config(TaskClass.CREATIVE)
        assert config.direct_answer is False
        assert config.critique is True
        assert config.scratchpad is False
        assert config.tool_verify is False

    def test_high_stakes_pipeline(self):
        config = get_pipeline_config(TaskClass.HIGH_STAKES)
        assert config.direct_answer is False
        assert config.critique is True
        assert config.scratchpad is True
        assert config.tool_verify is True

    def test_knowledge_pipeline(self):
        config = get_pipeline_config(TaskClass.KNOWLEDGE)
        assert config.direct_answer is True
        assert config.critique is False

    def test_ambiguous_pipeline(self):
        config = get_pipeline_config(TaskClass.AMBIGUOUS)
        assert config.direct_answer is True
        assert config.critique is False


# ── TaskClass Enum ────────────────────────────────────────


class TestTaskClass:
    """Test TaskClass enum values."""

    def test_all_six_classes_exist(self):
        assert len(TaskClass) == 6
        assert TaskClass.SIMPLE.value == "SIMPLE"
        assert TaskClass.KNOWLEDGE.value == "KNOWLEDGE"
        assert TaskClass.CREATIVE.value == "CREATIVE"
        assert TaskClass.COMPLEX.value == "COMPLEX"
        assert TaskClass.AMBIGUOUS.value == "AMBIGUOUS"
        assert TaskClass.HIGH_STAKES.value == "HIGH_STAKES"

    def test_classification_to_dict(self):
        c = Classification(
            task_class=TaskClass.COMPLEX,
            confidence=0.8,
            reasoning="test",
            method="llm",
        )
        d = c.to_dict()
        assert d["task_class"] == "COMPLEX"
        assert d["confidence"] == 0.8
        assert d["method"] == "llm"


# ── Phase 2: Critique Pipeline ────────────────────────────


class TestCritiquePipeline:
    """Test the Generate→Critique→Revise pipeline."""

    def test_parse_critique_valid_json(self):
        from nally.agent.harness import _parse_critique_response
        response = json.dumps({
            "issues": ["Missing error handling", "Unclear variable name"],
            "severity": "medium",
            "should_revise": True,
        })
        result = _parse_critique_response(response)
        assert len(result.issues) == 2
        assert result.severity == "medium"
        assert result.should_revise is True

    def test_parse_critique_no_issues(self):
        from nally.agent.harness import _parse_critique_response
        response = json.dumps({
            "issues": [],
            "severity": "none",
            "should_revise": False,
        })
        result = _parse_critique_response(response)
        assert result.should_revise is False
        assert result.severity == "none"

    def test_parse_critique_invalid_json(self):
        from nally.agent.harness import _parse_critique_response
        result = _parse_critique_response("not json at all")
        assert result.should_revise is False
        assert result.issues == []

    def test_parse_critique_string_issues(self):
        from nally.agent.harness import _parse_critique_response
        response = json.dumps({
            "issues": "Single issue as string",
            "severity": "low",
            "should_revise": "yes",
        })
        result = _parse_critique_response(response)
        assert result.issues == ["Single issue as string"]
        assert result.should_revise is True

    def test_critique_result_to_dict(self):
        from nally.agent.harness import CritiqueResult
        cr = CritiqueResult(
            issues=["issue1"],
            severity="high",
            should_revise=True,
        )
        d = cr.to_dict()
        assert d["severity"] == "high"
        assert d["should_revise"] is True

    def test_critique_pipeline_skips_revision_when_not_needed(self):
        from nally.agent.harness import run_critique_pipeline, TaskClass

        def mock_llm(messages, temperature=0.7):
            # Critique says no revision needed
            if "EVALUATE" in messages[-1]["content"] or "reviewer" in messages[0]["content"]:
                return json.dumps({"issues": [], "severity": "none", "should_revise": False})
            return "Generated response content"

        result = run_critique_pipeline(
            user_request="explain TCP",
            task_class=TaskClass.COMPLEX,
            llm_call_fn=mock_llm,
            existing_response="Generated response content",
        )
        assert result.was_revised is False
        assert result.response == "Generated response content"
        assert "critique" in result.stages_fired
        assert "revise" not in result.stages_fired  # not fired

    def test_critique_pipeline_revises_when_needed(self):
        from nally.agent.harness import run_critique_pipeline, TaskClass

        call_count = [0]

        def mock_llm(messages, temperature=0.7):
            call_count[0] += 1
            content = messages[-1]["content"]
            if "REVISE" in content:
                return "Revised and improved response"
            if "EVALUATE" in content or "reviewer" in messages[0]["content"]:
                return json.dumps({
                    "issues": ["Missing details"],
                    "severity": "medium",
                    "should_revise": True,
                })
            return "Original generated response"

        result = run_critique_pipeline(
            user_request="build a REST API",
            task_class=TaskClass.COMPLEX,
            llm_call_fn=mock_llm,
            existing_response="Original generated response",
        )
        assert result.was_revised is True
        assert result.response == "Revised and improved response"
        assert "revise" in result.stages_fired

    def test_critique_pipeline_handles_generate_failure(self):
        from nally.agent.harness import run_critique_pipeline, TaskClass

        def mock_llm(messages, temperature=0.7):
            raise Exception("API error")

        result = run_critique_pipeline(
            user_request="test",
            task_class=TaskClass.COMPLEX,
            llm_call_fn=mock_llm,
            existing_response="Original generated response",
        )
        # Without generate step, returns existing_response when critique fails
        assert result.response == "Original generated response"
        assert result.was_revised is False

    def test_critique_pipeline_handles_critique_failure(self):
        from nally.agent.harness import run_critique_pipeline, TaskClass

        def mock_llm(messages, temperature=0.7):
            content = messages[-1]["content"]
            if "EVALUATE" in content or "reviewer" in messages[0]["content"]:
                raise Exception("Critique API error")
            return "Generated response"

        result = run_critique_pipeline(
            user_request="test",
            task_class=TaskClass.COMPLEX,
            llm_call_fn=mock_llm,
            existing_response="Generated response",
        )
        assert result.response == "Generated response"
        assert result.was_revised is False

    def test_critique_pipeline_result_to_dict(self):
        from nally.agent.harness import CritiquePipelineResult, CritiqueResult

        result = CritiquePipelineResult(
            response="test response",
            was_revised=True,
            critique=CritiqueResult(issues=["x"], severity="low", should_revise=True),
            cost_tokens=100,
            cost_latency_ms=500.0,
            stages_fired=["generate", "critique", "revise"],
        )
        d = result.to_dict()
        assert d["was_revised"] is True
        assert d["cost_latency_ms"] == 500.0
        assert len(d["stages_fired"]) == 3


# ── Phase 3: Scratchpad ──────────────────────────────────


class TestScratchpad:
    """Test the per-request working memory."""

    def test_create_scratchpad(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="build a REST API")
        assert sp.objective == "build a REST API"
        assert sp.status == "active"
        assert sp.id  # auto-generated
        assert sp.created_at

    def test_add_fact(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="test")
        sp.add_fact("PostgreSQL is the target DB")
        assert "PostgreSQL is the target DB" in sp.facts

    def test_add_assumption(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="test")
        sp.add_assumption("User has Python 3.12 installed")
        assert len(sp.assumptions) == 1

    def test_add_decision(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="test")
        sp.add_decision("Use FastAPI for the backend")
        assert len(sp.decisions) == 1

    def test_add_action_and_result(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="test")
        sp.add_action("ran: pip install fastapi")
        sp.add_result("Successfully installed fastapi-0.115.0")
        assert len(sp.actions_taken) == 1
        assert len(sp.results) == 1

    def test_to_dict(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="test")
        d = sp.to_dict()
        assert d["objective"] == "test"
        assert d["status"] == "active"
        assert "constraints" in d

    def test_to_context_string(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="build API")
        sp.add_fact("Using FastAPI")
        sp.add_decision("PostgreSQL for DB")
        ctx = sp.to_context_string()
        assert "OBJECTIVE: build API" in ctx
        assert "FACTS:" in ctx
        assert "DECISIONS:" in ctx

    def test_suggest_long_term_writes(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="test")
        sp.add_fact("User prefers dark mode for all UIs")
        sp.add_decision("Use React with TypeScript")
        sp.add_result("Deployment failed due to missing env var")
        suggestions = sp.suggest_long_term_writes()
        assert len(suggestions) >= 2
        assert any("auto_fact" in s["category"] for s in suggestions)
        assert any("task" in s["category"] for s in suggestions)

    def test_suggest_skips_trivial(self):
        from nally.agent.scratchpad import Scratchpad
        sp = Scratchpad(objective="test")
        sp.add_fact("ok")
        sp.add_decision("yes")
        suggestions = sp.suggest_long_term_writes()
        assert len(suggestions) == 0


class TestScratchpadStore:
    """Test scratchpad persistence."""

    def test_save_and_load(self, tmp_dir):
        from nally.agent.scratchpad import Scratchpad, ScratchpadStore
        db = Path(tmp_dir) / "test_scratchpad.db"
        store = ScratchpadStore(db_path=db)
        sp = Scratchpad(objective="test task")
        sp.add_fact("test fact")
        store.save(sp)
        loaded = store.load(sp.id)
        assert loaded is not None
        assert loaded.objective == "test task"
        assert "test fact" in loaded.facts

    def test_complete(self, tmp_dir):
        from nally.agent.scratchpad import Scratchpad, ScratchpadStore
        db = Path(tmp_dir) / "test_scratchpad.db"
        store = ScratchpadStore(db_path=db)
        sp = Scratchpad(objective="test task")
        store.save(sp)
        store.complete(sp.id)
        loaded = store.load(sp.id)
        assert loaded.status == "completed"

    def test_fail(self, tmp_dir):
        from nally.agent.scratchpad import Scratchpad, ScratchpadStore
        db = Path(tmp_dir) / "test_scratchpad.db"
        store = ScratchpadStore(db_path=db)
        sp = Scratchpad(objective="test task")
        store.save(sp)
        store.fail(sp.id)
        loaded = store.load(sp.id)
        assert loaded.status == "failed"

    def test_load_nonexistent(self, tmp_dir):
        from nally.agent.scratchpad import ScratchpadStore
        db = Path(tmp_dir) / "test_scratchpad.db"
        store = ScratchpadStore(db_path=db)
        assert store.load("nonexistent") is None

    def test_get_active_count(self, tmp_dir):
        from nally.agent.scratchpad import Scratchpad, ScratchpadStore
        db = Path(tmp_dir) / "test_scratchpad.db"
        store = ScratchpadStore(db_path=db)
        assert store.get_active_count() == 0
        sp = Scratchpad(objective="test")
        store.save(sp)
        assert store.get_active_count() == 1
        store.complete(sp.id)
        assert store.get_active_count() == 0


# ── Phase 4: Tool-Result Verification ────────────────────


class TestToolVerification:
    """Test tool-result verification."""

    def test_successful_tool_with_objective_match(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="run_command",
            tool_args={"command": "mkdir -p src"},
            tool_result="Directory created successfully",
            tool_success=True,
            objective="create the project directory structure",
        )
        assert result.satisfies_objective is True
        assert result.confidence > 0.5

    def test_successful_tool_no_objective(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="run_command",
            tool_args={"command": "ls"},
            tool_result="file1.py\nfile2.py",
            tool_success=True,
            objective="",
        )
        assert result.satisfies_objective is True

    def test_tool_with_error(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="run_command",
            tool_args={"command": "bad_cmd"},
            tool_result="Traceback (most recent call last):\n  File ...",
            tool_success=True,
            objective="run a command",
        )
        assert result.satisfies_objective is False
        assert result.confidence >= 0.8

    def test_tool_reported_failure(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="run_command",
            tool_args={"command": "test"},
            tool_result="some output",
            tool_success=False,
            objective="test something",
        )
        assert result.satisfies_objective is False

    def test_empty_result(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="run_code",
            tool_args={"code": "pass"},
            tool_result="",
            tool_success=True,
            objective="run code",
        )
        assert result.satisfies_objective is False

    def test_trivial_result(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="run_code",
            tool_args={"code": "print(1)"},
            tool_result="ok",
            tool_success=True,
            objective="run code",
        )
        assert result.satisfies_objective is False

    def test_completion_signal_boosts_confidence(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="run_command",
            tool_args={"command": "npm install"},
            tool_result="Successfully installed 42 packages",
            tool_success=True,
            objective="install npm packages",
        )
        assert result.satisfies_objective is True
        assert result.confidence > 0.7

    def test_verification_to_dict(self):
        from nally.agent.harness import ToolVerification
        v = ToolVerification(
            action="test()",
            result="output",
            evidence="signal detected",
            satisfies_objective=True,
            confidence=0.8,
            reasoning="test",
        )
        d = v.to_dict()
        assert d["satisfies_objective"] is True
        assert d["confidence"] == 0.8

    def test_low_objective_match(self):
        from nally.agent.harness import verify_tool_result
        result = verify_tool_result(
            tool_name="web_search",
            tool_args={"query": "recipes"},
            tool_result="Found 10 results about pasta recipes",
            tool_success=True,
            objective="deploy the application to production",
        )
        assert result.satisfies_objective is False
