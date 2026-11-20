# Run test: uv run pytest tests/test_llm.py -v
"""Unit tests for the provider-agnostic LLM adapter and Gemini Interactions API client."""

from __future__ import annotations

from typing import Any, Dict, List
import pytest
from pydantic import BaseModel

from app.core.llm import (
    AnthropicProvider,
    GeminiInteractionsProvider,
    MockLLMProvider,
    OpenAIProvider,
    ToolDefinition,
    create_llm_provider,
)


class SampleSchema(BaseModel):
    """Test Pydantic output model."""

    answer: str
    confidence: float


def test_mock_llm_provider_returns_structured_output_and_runs_tools() -> None:
    """Verifies that `MockLLMProvider` handles structured outputs and tool loops offline."""
    called_args: List[Dict[str, Any]] = []

    def lookup_tool(query: str) -> str:
        called_args.append({"query": query})
        return "Wilmington, DE"

    tool = ToolDefinition(
        name="lookup_hq",
        description="Look up corporate HQ.",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=lookup_tool,
    )

    mock = MockLLMProvider(
        structured_responses={
            "SampleSchema": {"answer": "Wilmington, DE", "confidence": 0.99}
        },
        tool_invocations=[{"name": "lookup_hq", "arguments": {"query": "HQ"}}],
    )
    result = mock.run_tool_loop(
        prompt="Where is HQ?",
        system_instruction="Extract HQ.",
        tools=[tool],
        response_model=SampleSchema,
    )
    assert isinstance(result, SampleSchema)
    assert result.answer == "Wilmington, DE"
    assert result.confidence == 0.99
    assert called_args == [{"query": "HQ"}]


def test_gemini_interactions_provider_formats_structured_output_call() -> None:
    """Verifies `GeminiInteractionsProvider` uses `client.interactions.create` with 2026 schema."""
    recorded_calls: List[Dict[str, Any]] = []

    class FakeUsage:
        total_tokens = 142

    class FakeInteraction:
        id = "int_test_123"
        status = "completed"
        output_text = '{"answer": "Wilmington", "confidence": 0.95}'
        steps: List[Any] = []
        usage = FakeUsage()

    class FakeInteractionsResource:
        def create(self, **kwargs: Any) -> FakeInteraction:
            recorded_calls.append(kwargs)
            return FakeInteraction()

    class FakeGenAIClient:
        interactions = FakeInteractionsResource()

    provider = GeminiInteractionsProvider(
        model="gemini-4-argon",
        client=FakeGenAIClient(),
    )
    parsed = provider.generate_structured(
        prompt="Identify headquarters.",
        system_instruction="You are a legal analyst.",
        response_model=SampleSchema,
    )

    assert parsed.answer == "Wilmington"
    assert parsed.confidence == 0.95
    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["model"] == "gemini-4-argon"
    assert call["system_instruction"] == "You are a legal analyst."
    assert call["response_format"]["type"] == "text"
    assert call["response_format"]["mime_type"] == "application/json"
    assert "properties" in call["response_format"]["schema"]


def test_gemini_interactions_provider_executes_multi_turn_tool_loop() -> None:
    """Verifies stateful `previous_interaction_id` function_call -> function_result loop."""
    recorded_calls: List[Dict[str, Any]] = []

    class FakeStep:
        def __init__(self, step_type: str, step_id: str, name: str, arguments: Dict[str, Any]) -> None:
            self.type = step_type
            self.id = step_id
            self.name = name
            self.arguments = arguments

    class FakeUsage:
        total_tokens = 250

    class Turn1Interaction:
        id = "int_turn_1"
        status = "requires_action"
        output_text = None
        steps = [FakeStep("function_call", "fc_1", "grep_inputs", {"pattern": "Wilmington"})]
        usage = FakeUsage()

    class Turn2Interaction:
        id = "int_turn_2"
        status = "completed"
        output_text = '{"answer": "1209 North Orange St, Wilmington, DE", "confidence": 1.0}'
        steps: List[Any] = []
        usage = FakeUsage()

    class FakeInteractionsResource:
        def create(self, **kwargs: Any) -> Any:
            recorded_calls.append(kwargs)
            if len(recorded_calls) == 1:
                return Turn1Interaction()
            return Turn2Interaction()

    class FakeGenAIClient:
        interactions = FakeInteractionsResource()

    tool = ToolDefinition(
        name="grep_inputs",
        description="Search indexed inputs.",
        parameters_schema={
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
        handler=lambda pattern: f"Found match for {pattern} on page 2",
    )

    provider = GeminiInteractionsProvider(
        model="gemini-4-argon",
        client=FakeGenAIClient(),
    )
    result = provider.run_tool_loop(
        prompt="Find the HQ address.",
        system_instruction="Be strictly factual.",
        tools=[tool],
        response_model=SampleSchema,
    )

    assert result.answer == "1209 North Orange St, Wilmington, DE"
    assert len(recorded_calls) == 2
    assert "tools" in recorded_calls[0]
    assert recorded_calls[1]["previous_interaction_id"] == "int_turn_1"
    assert recorded_calls[1]["input"][0]["type"] == "function_result"
    assert recorded_calls[1]["input"][0]["call_id"] == "fc_1"
    assert "Found match for Wilmington on page 2" in recorded_calls[1]["input"][0]["result"][0]["text"]


def test_create_llm_provider_factory_supports_multiple_backends() -> None:
    """Verifies provider factory routing for mock, gemini, anthropic, and openai."""
    mock_provider = create_llm_provider("mock")
    assert isinstance(mock_provider, MockLLMProvider)

    anthropic_provider = create_llm_provider("anthropic", api_key="test-key")
    assert isinstance(anthropic_provider, AnthropicProvider)

    openai_provider = create_llm_provider("openai", api_key="test-key")
    assert isinstance(openai_provider, OpenAIProvider)

    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        create_llm_provider("unknown_backend")


def test_gemini_decisions_api_calls_v1beta_and_normalizes_answers() -> None:
    """Verifies `GeminiInteractionsProvider.evaluate_decisions` calls `decisions.create(api_version='v1beta')`."""
    recorded: List[Dict[str, Any]] = []

    class FakeNoulAnswer:
        type = "noul"
        noul = 0.94
        confidence = 0.94

    class FakeChoiceAnswer:
        type = "choice"
        choice = "verified"
        probabilities = {"verified": 0.91, "extrapolation": 0.08, "assumption": 0.01}
        confidence = 0.91

    class FakeDecisionResp:
        answers = {
            "check_b_congruence": FakeNoulAnswer(),
            "claim_1_status": FakeChoiceAnswer(),
        }

    class FakeDecisionsResource:
        def create(self, **kwargs: Any) -> FakeDecisionResp:
            recorded.append(kwargs)
            return FakeDecisionResp()

    class FakeClient:
        decisions = FakeDecisionsResource()

    provider = GeminiInteractionsProvider(model="gemini-4-argon", client=FakeClient())
    batch = provider.evaluate_decisions(
        input_text="Docket says March 1, 2026.",
        questions={
            "check_b_congruence": {"type": "noul", "instructions": "Entailed?"},
            "claim_1_status": {
                "type": "choice",
                "instructions": "Classify claim 1.",
                "criteria": {"verified": "Direct", "extrapolation": "Inferred"},
            },
        },
        decision_model="gemini-decision-1",
    )

    assert len(recorded) == 1
    assert recorded[0]["model"] == "models/gemini-decision-1"
    assert recorded[0]["api_version"] == "v1beta"
    assert batch.answers["check_b_congruence"].noul == 0.94
    assert batch.answers["claim_1_status"].choice == "verified"
    assert batch.answers["claim_1_status"].probabilities["verified"] == 0.91

    # Also verify graceful fallback to generate_structured if decisions.create raises
    class FailingDecisionsResource:
        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("Decisions endpoint unavailable")

    class FallbackInteraction:
        id = "int_fb"
        status = "completed"
        output_text = '{"answers": {"q1": {"question_id": "q1", "question_type": "noul", "noul": 0.88, "confidence": 0.88}}}'
        steps: List[Any] = []
        usage = None

    class FallbackInteractions:
        def create(self, **kwargs: Any) -> FallbackInteraction:
            return FallbackInteraction()

    class FallbackClient:
        decisions = FailingDecisionsResource()
        interactions = FallbackInteractions()

    fb_provider = GeminiInteractionsProvider(model="gemini-4-argon", client=FallbackClient())
    fb_batch = fb_provider.evaluate_decisions(
        input_text="Context",
        questions={"q1": {"type": "noul", "instructions": "Ok?"}},
    )
    assert fb_batch.answers["q1"].noul == 0.88


def test_create_llm_provider_loads_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies `create_llm_provider()` invokes `load_dotenv` to pick up keys from `.env`."""
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=dotenv_fake_key_123\nJD_SCREEN_MODEL=gemini-4-hydrogen\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("JD_SCREEN_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)

    captured: Dict[str, Any] = {}

    class StubClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    import google.genai as genai_mod

    monkeypatch.setattr(genai_mod, "Client", StubClient)
    provider = create_llm_provider("gemini")
    assert isinstance(provider, GeminiInteractionsProvider)
    assert captured.get("api_key") == "dotenv_fake_key_123"
    assert provider.model == "gemini-4-hydrogen"
