"""Provider-agnostic LLM gateway with Google Gemini Interactions API support.

This module isolates all agentic pipeline stages from vendor-specific SDKs behind
the `LLMProvider` protocol. The primary implementation (`GeminiInteractionsProvider`)
uses the modern `google-genai` Interactions API (`client.interactions.create`),
while `AnthropicProvider` and `OpenAIProvider` provide drop-in extension hooks
for adding Claude or GPT models without altering pipeline logic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Type, TypeVar, Union, runtime_checkable

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

from app.models import DecisionAnswerItem, DecisionBatchResult

logger = logging.getLogger("jd_screen.llm")

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ToolDefinition:
    """Declarative tool descriptor executable inside an agentic tool loop.

    Attributes:
        name: Unique snake_case tool name exposed to the model.
        description: Clear description of when and how the model should call this tool.
        parameters_schema: JSON Schema object describing the tool's arguments.
        handler: Local Python callable invoked with keyword arguments from the model.
    """

    name: str
    description: str
    parameters_schema: Dict[str, Any]
    handler: Callable[..., Any]


@runtime_checkable
class LLMProvider(Protocol):
    """Unified interface for structured generation, text polishing, and tool loops."""

    def generate_structured(
        self,
        prompt: str,
        system_instruction: str,
        response_model: Type[T],
    ) -> T:
        """Generates a single response strictly conforming to a Pydantic model.

        Args:
            prompt: User or stage task prompt.
            system_instruction: System role and strict grounding rules.
            response_model: Pydantic `BaseModel` subclass defining the output schema.

        Returns:
            Validated instance of `response_model`.
        """
        ...

    def generate_text(
        self,
        prompt: str,
        system_instruction: str,
    ) -> str:
        """Generates plain or markdown text (used for Stage 4 editorial stitching).

        Args:
            prompt: Task prompt containing text to edit or synthesize.
            system_instruction: System role and tag-immutability invariants.

        Returns:
            Generated string output.
        """
        ...

    def run_tool_loop(
        self,
        prompt: str,
        system_instruction: str,
        tools: List[ToolDefinition],
        response_model: Type[T],
        max_turns: int = 8,
    ) -> T:
        """Executes a multi-turn function-calling loop ending in structured output.

        Args:
            prompt: Initial task instruction for the agent.
            system_instruction: System prompt governing tool usage and honesty.
            tools: Available local tools the agent may invoke.
            response_model: Pydantic model for the final structured synthesis.
            max_turns: Safety cap on tool-execution round trips.

        Returns:
            Validated instance of `response_model`.
        """
        ...

    def evaluate_decisions(
        self,
        input_text: str,
        questions: Dict[str, Dict[str, Any]],
        *,
        decision_model: str = "models/gemini-decision-1",
    ) -> DecisionBatchResult:
        """Evaluates structured Noul/Choice questions with calibrated probabilities."""
        ...


def _extract_json_text(raw_text: Optional[str]) -> str:
    """Strips optional Markdown code fences from an LLM JSON response.

    Args:
        raw_text: Raw text returned by an LLM endpoint.

    Returns:
        Clean JSON string ready for Pydantic `model_validate_json`.
    """
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _serialize_tool_output(result: Any) -> str:
    """Converts a local Python tool return value into a deterministic string."""
    if isinstance(result, str):
        return result
    if isinstance(result, BaseModel):
        return result.model_dump_json(indent=2)
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


class GeminiInteractionsProvider:
    """LLM backend powered by the Google Gemini Interactions API (`google-genai >= 2.30.1`).

    Uses `client.interactions.create(...)` with `response_format` JSON Schema
    enforcement and stateful `previous_interaction_id` chaining for tool calls.
    """

    DEFAULT_MODEL = "gemini-4-argon"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        """Initializes the Gemini Interactions API provider.

        Args:
            model: Gemini model identifier (default: `gemini-4-argon`; supports
                `gemini-4-carbon`, `gemini-3.8-flash`, `gemini-3.5-flash-lite`).
            api_key: Optional Gemini API key; falls back to `GEMINI_API_KEY` env var.
            client: Optional pre-constructed `google.genai.Client` (useful for tests).
        """
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if client is not None:
            self.client = client
        else:
            from google import genai

            self.client = genai.Client(api_key=self.api_key) if self.api_key else genai.Client()

    @staticmethod
    def _log_interaction(stage: str, interaction: Any, system_len: int, prompt_len: int) -> None:
        """Logs interaction IDs and token usage without dumping full sensitive payloads."""
        usage = getattr(interaction, "usage", None)
        total_tokens = getattr(usage, "total_tokens", None)
        logger.info(
            "Gemini interaction [%s] model=%s id=%s status=%s sys_chars=%d prompt_chars=%d total_tokens=%s",
            stage,
            getattr(interaction, "model", "unknown"),
            getattr(interaction, "id", None),
            getattr(interaction, "status", None),
            system_len,
            prompt_len,
            total_tokens,
        )

    def generate_structured(
        self,
        prompt: str,
        system_instruction: str,
        response_model: Type[T],
    ) -> T:
        """Generates schema-validated Pydantic output via `client.interactions.create`.

        Args:
            prompt: User or stage prompt.
            system_instruction: System instruction string.
            response_model: Pydantic model class for structured decoding.

        Returns:
            Validated instance of `response_model`.
        """
        response_format = {
            "type": "text",
            "mime_type": "application/json",
            "schema": response_model.model_json_schema(),
        }
        interaction = self.client.interactions.create(
            model=self.model,
            system_instruction=system_instruction,
            input=prompt,
            response_format=response_format,
        )
        self._log_interaction(
            f"structured:{response_model.__name__}",
            interaction,
            len(system_instruction),
            len(prompt),
        )
        payload = _extract_json_text(getattr(interaction, "output_text", None))
        return response_model.model_validate_json(payload)

    def generate_text(
        self,
        prompt: str,
        system_instruction: str,
    ) -> str:
        """Generates plain/markdown text via `client.interactions.create`.

        Args:
            prompt: User or editorial prompt.
            system_instruction: System instruction string.

        Returns:
            Generated text string.
        """
        interaction = self.client.interactions.create(
            model=self.model,
            system_instruction=system_instruction,
            input=prompt,
        )
        self._log_interaction(
            "text",
            interaction,
            len(system_instruction),
            len(prompt),
        )
        return (getattr(interaction, "output_text", None) or "").strip()

    def run_tool_loop(
        self,
        prompt: str,
        system_instruction: str,
        tools: List[ToolDefinition],
        response_model: Type[T],
        max_turns: int = 8,
    ) -> T:
        """Runs a stateful `previous_interaction_id` tool loop ending in `response_model`.

        Note: In the Gemini Interactions API, `tools`, `system_instruction`, and
        `response_format` are interaction-scoped and must be re-specified on each turn.

        Args:
            prompt: Initial task prompt.
            system_instruction: System instructions for tool invocation.
            tools: List of `ToolDefinition` objects.
            response_model: Target Pydantic schema for the final response.
            max_turns: Maximum number of interaction round trips.

        Returns:
            Validated instance of `response_model`.
        """
        tool_map = {t.name: t for t in tools}
        gemini_tools = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_schema,
            }
            for t in tools
        ]
        response_format = {
            "type": "text",
            "mime_type": "application/json",
            "schema": response_model.model_json_schema(),
        }

        interaction = self.client.interactions.create(
            model=self.model,
            system_instruction=system_instruction,
            input=prompt,
            tools=gemini_tools,
            response_format=response_format,
        )
        self._log_interaction(
            f"tool_turn_0:{response_model.__name__}",
            interaction,
            len(system_instruction),
            len(prompt),
        )

        for turn in range(1, max_turns + 1):
            steps = getattr(interaction, "steps", None) or []
            function_calls = [s for s in steps if getattr(s, "type", None) == "function_call"]
            if not function_calls:
                break

            tool_results: List[Dict[str, Any]] = []
            for fc in function_calls:
                tool_name = getattr(fc, "name", "")
                arguments = getattr(fc, "arguments", {}) or {}
                call_id = getattr(fc, "id", "")
                logger.info("Executing tool '%s' args=%s", tool_name, arguments)

                tool_def = tool_map.get(tool_name)
                if tool_def is None:
                    result_str = json.dumps({"error": f"Unknown tool '{tool_name}'"})
                else:
                    try:
                        output = tool_def.handler(**arguments)
                        result_str = _serialize_tool_output(output)
                    except Exception as exc:
                        logger.warning("Tool '%s' failed: %s", tool_name, exc)
                        result_str = json.dumps({"error": str(exc)})

                tool_results.append(
                    {
                        "type": "function_result",
                        "call_id": call_id,
                        "name": tool_name,
                        "result": [{"type": "text", "text": result_str}],
                    }
                )

            interaction = self.client.interactions.create(
                model=self.model,
                previous_interaction_id=interaction.id,
                system_instruction=system_instruction,
                input=tool_results,
                tools=gemini_tools,
                response_format=response_format,
            )
            self._log_interaction(
                f"tool_turn_{turn}:{response_model.__name__}",
                interaction,
                len(system_instruction),
                len(tool_results),
            )

        output_text = getattr(interaction, "output_text", None)
        if not output_text:
            # Final structured coercion turn if the loop hit max_turns on a tool call
            interaction = self.client.interactions.create(
                model=self.model,
                previous_interaction_id=interaction.id,
                system_instruction=system_instruction,
                input="Stop calling tools and emit the final JSON matching the required schema.",
                response_format=response_format,
            )
            output_text = getattr(interaction, "output_text", None)

        return response_model.model_validate_json(_extract_json_text(output_text))

    def evaluate_decisions(
        self,
        input_text: str,
        questions: Dict[str, Dict[str, Any]],
        *,
        decision_model: str = "models/gemini-decision-1",
    ) -> DecisionBatchResult:
        """Evaluates Noul/Choice questions via `client.decisions.create(api_version='v1beta')`."""
        model_name = (
            decision_model if decision_model.startswith("models/") else f"models/{decision_model}"
        )
        try:
            response = self.client.decisions.create(
                model=model_name,
                input=input_text,
                questions=questions,
                api_version="v1beta",
            )
            raw_answers = getattr(response, "answers", None) or {}
            normalized: Dict[str, DecisionAnswerItem] = {}
            for qid, ans in raw_answers.items():
                ans_type = (
                    ans.get("type") if isinstance(ans, dict) else getattr(ans, "type", None)
                ) or "noul"
                conf = (
                    ans.get("confidence", 0.5)
                    if isinstance(ans, dict)
                    else getattr(ans, "confidence", 0.5)
                )
                if ans_type == "choice":
                    ch = ans.get("choice", "") if isinstance(ans, dict) else getattr(ans, "choice", "")
                    probs = (
                        ans.get("probabilities", {})
                        if isinstance(ans, dict)
                        else getattr(ans, "probabilities", {})
                    )
                    normalized[qid] = DecisionAnswerItem(
                        question_id=qid,
                        question_type="choice",
                        choice=str(ch or ""),
                        probabilities=dict(probs or {}),
                        confidence=float(conf if conf is not None else 0.5),
                    )
                else:
                    noul_val = (
                        ans.get("noul", 0.5) if isinstance(ans, dict) else getattr(ans, "noul", 0.5)
                    )
                    normalized[qid] = DecisionAnswerItem(
                        question_id=qid,
                        question_type="noul",
                        noul=float(noul_val if noul_val is not None else 0.5),
                        confidence=float(conf if conf is not None else 0.5),
                    )
            return DecisionBatchResult(answers=normalized)
        except Exception as exc:
            logger.warning(
                "Gemini Decisions API call failed (%s); falling back to generate_structured.",
                exc,
            )
            fallback_prompt = (
                f"Input Context:\n{input_text}\n\n"
                f"Questions to evaluate (JSON):\n{json.dumps(questions, indent=2)}\n\n"
                "Emit a DecisionBatchResult JSON answering every question_id accurately."
            )
            return self.generate_structured(
                prompt=fallback_prompt,
                system_instruction="Evaluate each decision question strictly against Input Context.",
                response_model=DecisionBatchResult,
            )


class AnthropicProvider:
    """Extension adapter for Anthropic Claude models conforming to `LLMProvider`.

    Install `anthropic` (`uv add anthropic`) and set `ANTHROPIC_API_KEY` to enable.
    """

    DEFAULT_MODEL = "claude-sonnet-4-5"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None) -> None:
        """Initializes the Anthropic provider configuration.

        Args:
            model: Anthropic model identifier.
            api_key: Optional API key; falls back to `ANTHROPIC_API_KEY`.
        """
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def _get_client(self) -> Any:
        """Lazily imports and instantiates `anthropic.Anthropic`."""
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic provider requires the `anthropic` package. Run: uv add anthropic"
            ) from exc
        return anthropic.Anthropic(api_key=self.api_key)

    def generate_structured(
        self,
        prompt: str,
        system_instruction: str,
        response_model: Type[T],
    ) -> T:
        """Uses Anthropic tool-forcing to return a schema-validated Pydantic object."""
        client = self._get_client()
        tool_name = f"emit_{response_model.__name__}"
        msg = client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system_instruction,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": tool_name,
                    "description": f"Emit structured {response_model.__name__} JSON.",
                    "input_schema": response_model.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return response_model.model_validate(block.input)
        raise ValueError(f"Anthropic response did not invoke forced tool {tool_name}")

    def generate_text(self, prompt: str, system_instruction: str) -> str:
        """Generates plain text via `client.messages.create`."""
        client = self._get_client()
        msg = client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system_instruction,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        ).strip()

    def run_tool_loop(
        self,
        prompt: str,
        system_instruction: str,
        tools: List[ToolDefinition],
        response_model: Type[T],
        max_turns: int = 8,
    ) -> T:
        """Executes an Anthropic `tool_use` / `tool_result` loop ending in `response_model`."""
        client = self._get_client()
        tool_map = {t.name: t for t in tools}
        emit_name = f"emit_{response_model.__name__}"
        anthropic_tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters_schema,
            }
            for t in tools
        ] + [
            {
                "name": emit_name,
                "description": f"Final step: emit validated {response_model.__name__}.",
                "input_schema": response_model.model_json_schema(),
            }
        ]
        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

        for _ in range(max_turns):
            msg = client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system_instruction,
                messages=messages,
                tools=anthropic_tools,
            )
            messages.append({"role": "assistant", "content": msg.content})
            tool_results: List[Dict[str, Any]] = []
            for block in msg.content:
                if getattr(block, "type", None) == "tool_use":
                    if block.name == emit_name:
                        return response_model.model_validate(block.input)
                    tool_def = tool_map.get(block.name)
                    output = (
                        tool_def.handler(**(block.input or {}))
                        if tool_def
                        else {"error": f"Unknown tool {block.name}"}
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": _serialize_tool_output(output),
                        }
                    )
            if not tool_results:
                break
            messages.append({"role": "user", "content": tool_results})

        return self.generate_structured(
            prompt=f"{prompt}\n\nSynthesize final output from gathered evidence.",
            system_instruction=system_instruction,
            response_model=response_model,
        )

    def evaluate_decisions(
        self,
        input_text: str,
        questions: Dict[str, Dict[str, Any]],
        *,
        decision_model: str = "models/gemini-decision-1",
    ) -> DecisionBatchResult:
        """Signals pipeline callers to fall back to `generate_structured` on Anthropic."""
        return DecisionBatchResult(answers={})


class OpenAIProvider:
    """Extension adapter for OpenAI models conforming to `LLMProvider`.

    Install `openai` (`uv add openai`) and set `OPENAI_API_KEY` to enable.
    """

    DEFAULT_MODEL = "gpt-5"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None) -> None:
        """Initializes the OpenAI provider configuration.

        Args:
            model: OpenAI model identifier.
            api_key: Optional API key; falls back to `OPENAI_API_KEY`.
        """
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")

    def _get_client(self) -> Any:
        """Lazily imports and instantiates `openai.OpenAI`."""
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI provider requires the `openai` package. Run: uv add openai"
            ) from exc
        return openai.OpenAI(api_key=self.api_key)

    def generate_structured(
        self,
        prompt: str,
        system_instruction: str,
        response_model: Type[T],
    ) -> T:
        """Uses OpenAI structured parsing (`beta.chat.completions.parse`)."""
        client = self._get_client()
        completion = client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            response_format=response_model,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI structured completion returned empty parsed object.")
        return parsed

    def generate_text(self, prompt: str, system_instruction: str) -> str:
        """Generates plain text via OpenAI Chat Completions."""
        client = self._get_client()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
        )
        return (completion.choices[0].message.content or "").strip()

    def run_tool_loop(
        self,
        prompt: str,
        system_instruction: str,
        tools: List[ToolDefinition],
        response_model: Type[T],
        max_turns: int = 8,
    ) -> T:
        """Executes an OpenAI function-calling loop ending in `response_model`."""
        client = self._get_client()
        tool_map = {t.name: t for t in tools}
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            }
            for t in tools
        ]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ]

        for _ in range(max_turns):
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=oai_tools,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                break
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                tool_def = tool_map.get(tc.function.name)
                args = json.loads(tc.function.arguments or "{}")
                output = (
                    tool_def.handler(**args)
                    if tool_def
                    else {"error": f"Unknown tool {tc.function.name}"}
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _serialize_tool_output(output),
                    }
                )

        messages.append(
            {
                "role": "user",
                "content": "Emit the final structured JSON matching the target schema.",
            }
        )
        completion = client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=response_model,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI tool loop ended without parsed structured output.")
        return parsed

    def evaluate_decisions(
        self,
        input_text: str,
        questions: Dict[str, Dict[str, Any]],
        *,
        decision_model: str = "models/gemini-decision-1",
    ) -> DecisionBatchResult:
        """Signals pipeline callers to fall back to `generate_structured` on OpenAI."""
        return DecisionBatchResult(answers={})


class MockLLMProvider:
    """Deterministic offline LLM provider for unit/integration testing without paid tokens."""

    def __init__(
        self,
        structured_responses: Optional[Dict[str, Any]] = None,
        text_responses: Optional[List[str]] = None,
        tool_invocations: Optional[List[Dict[str, Any]]] = None,
        decision_responses: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> None:
        """Initializes deterministic mock queues keyed by Pydantic model class name.

        Args:
            structured_responses: Mapping of `ModelName -> dict | list[dict] | callable`
                returning payloads validated against `response_model`.
            text_responses: FIFO list of strings returned by `generate_text`.
            tool_invocations: Optional list of `{"name": ..., "arguments": ...}` dicts
                invoked during `run_tool_loop` before emitting the structured response.
            decision_responses: Optional dict, FIFO list of dicts, or callable returning
                a `DecisionBatchResult` payload (or `answers` dict).
        """
        self.structured_responses = structured_responses or {}
        self.text_responses = list(text_responses or [])
        self.tool_invocations = list(tool_invocations or [])
        self.decision_responses = decision_responses
        self.call_log: List[Dict[str, Any]] = []

    def generate_structured(
        self,
        prompt: str,
        system_instruction: str,
        response_model: Type[T],
    ) -> T:
        """Returns the next configured mock response validated as `response_model`."""
        key = response_model.__name__
        self.call_log.append(
            {"method": "generate_structured", "model": key, "prompt": prompt}
        )
        if key not in self.structured_responses:
            raise KeyError(f"MockLLMProvider has no fixture configured for '{key}'.")
        entry = self.structured_responses[key]
        if callable(entry):
            payload = entry(prompt, system_instruction)
        elif isinstance(entry, list):
            payload = entry.pop(0)
        else:
            payload = entry
        if isinstance(payload, response_model):
            return payload
        return response_model.model_validate(payload)

    def generate_text(self, prompt: str, system_instruction: str) -> str:
        """Returns the next configured text response or echoes the prompt."""
        self.call_log.append({"method": "generate_text", "prompt": prompt})
        if self.text_responses:
            return self.text_responses.pop(0)
        return prompt

    def run_tool_loop(
        self,
        prompt: str,
        system_instruction: str,
        tools: List[ToolDefinition],
        response_model: Type[T],
        max_turns: int = 8,
    ) -> T:
        """Executes configured mock tool calls and returns `generate_structured`."""
        tool_map = {t.name: t for t in tools}
        for inv in self.tool_invocations:
            t_name = inv["name"]
            t_args = inv.get("arguments", {})
            if t_name in tool_map:
                tool_map[t_name].handler(**t_args)
        return self.generate_structured(
            prompt=prompt,
            system_instruction=system_instruction,
            response_model=response_model,
        )

    def evaluate_decisions(
        self,
        input_text: str,
        questions: Dict[str, Dict[str, Any]],
        *,
        decision_model: str = "models/gemini-decision-1",
    ) -> DecisionBatchResult:
        """Returns configured mock decision verdicts or empty batch for structured fallback."""
        self.call_log.append(
            {
                "method": "evaluate_decisions",
                "model": decision_model,
                "input": input_text,
                "questions": questions,
            }
        )
        if self.decision_responses is None:
            return DecisionBatchResult(answers={})

        entry = self.decision_responses
        if callable(entry):
            payload = entry(input_text, questions)
        elif isinstance(entry, list):
            payload = entry.pop(0)
        else:
            payload = entry

        if isinstance(payload, DecisionBatchResult):
            return payload
        if isinstance(payload, dict) and "answers" not in payload:
            payload = {"answers": payload}
        return DecisionBatchResult.model_validate(payload)


def create_llm_provider(
    provider_name: str = "gemini",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> LLMProvider:
    """Factory instantiating an `LLMProvider` by backend name.

    Loads `.env` (with `override=False`) before inspecting API key and default
    provider/model environment variables.

    Args:
        provider_name: One of `'gemini'`, `'anthropic'`, `'openai'`, `'mock'`.
        model: Optional model override (uses provider default if omitted).
        api_key: Optional API key override.

    Returns:
        Configured `LLMProvider` instance.

    Raises:
        ValueError: If `provider_name` is not recognized.
    """
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)
    else:
        load_dotenv(override=False)
    normalized = (provider_name or os.environ.get("JD_SCREEN_PROVIDER", "gemini")).strip().lower()
    env_model = model or os.environ.get("JD_SCREEN_MODEL")
    if normalized == "gemini":
        return GeminiInteractionsProvider(
            model=env_model or GeminiInteractionsProvider.DEFAULT_MODEL,
            api_key=api_key,
        )
    if normalized == "anthropic":
        return AnthropicProvider(
            model=env_model or AnthropicProvider.DEFAULT_MODEL,
            api_key=api_key,
        )
    if normalized == "openai":
        return OpenAIProvider(
            model=env_model or OpenAIProvider.DEFAULT_MODEL,
            api_key=api_key,
        )
    if normalized == "mock":
        return MockLLMProvider()
    raise ValueError(
        f"Unsupported LLM provider '{provider_name}'. Expected one of: gemini, anthropic, openai, mock."
    )
