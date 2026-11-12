# Run test: uv run pytest tests/test_llm.py -v
"""Unit tests for the provider-agnostic LLM adapter and Gemini Interactions API client."""

from __future__ import annotations

from typing import Any, Dict, List
import pytest
from pydantic import BaseModel

from app.llm import (
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
