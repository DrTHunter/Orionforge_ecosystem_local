"""Anthropic Messages API client, built on the official ``anthropic`` SDK.

Talks directly to the Anthropic Messages API (https://api.anthropic.com/v1/messages).
Supports tool calling, prompt caching, effort, and server-side fallback for when a
model's safety classifiers decline a request.

Set ANTHROPIC_API_KEY in your environment, or the client will fall back to the
profile dict (not recommended for production).
"""

import os
from typing import Any, Dict, List, Optional

import anthropic

from src.llm_client.base import LLMClient, LLMResponse, temperature_param

ANTHROPIC_API_URL = "https://api.anthropic.com"

# Thinking counts toward max_tokens, so this has to leave room for it as well as the reply.
# Requests stream, so a limit this high can't hit an HTTP timeout.
DEFAULT_MAX_TOKENS = 64_000

# Models that take output_config.effort.
_EFFORT_MODELS = (
    "claude-fable-", "claude-mythos-", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
    "claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-5",
)

# Models whose declined requests can continue on another model, chosen by Anthropic by refusal category.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicClient(LLMClient):
    """Native Anthropic provider for the agent runtime."""

    # Anthropic models → context windows (for reference only)
    KNOWN_MODELS = {
        "claude-fable-5-1": 1_000_000,
        "claude-opus-5-5": 1_000_000,
        "claude-sonnet-5-5": 1_000_000,
        "claude-haiku-5-5": 1_000_000,
    }

    def __init__(self, profile: dict):
        self.model: str = profile["model"]
        self.base_url: str = profile.get("base_url", ANTHROPIC_API_URL).rstrip("/")
        # Prefer an explicit profile/connection key (bring-your-own), then fall
        # back to the platform-hosted ANTHROPIC_API_KEY environment variable.
        self.api_key: str = profile.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.temperature: float = profile.get("temperature", 0.7)
        self.max_tokens: int = profile.get("max_tokens", DEFAULT_MAX_TOKENS)
        self.effort: Optional[str] = profile.get("effort")  # low, medium, high, xhigh or max

        if not self.api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Export it before running with the anthropic provider."
            )
        self._client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)

    # ------------------------------------------------------------------
    # Main chat entry-point
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Separate system message from conversation messages
        system_text, conv_messages = self._extract_system(messages)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(conv_messages),
            "max_tokens": self.max_tokens,
            **temperature_param(self.model, self.temperature),
        }

        if system_text:
            kwargs["system"] = system_text

        # Build tool definitions
        api_tools = self._build_tools(tools)
        if api_tools:
            kwargs["tools"] = api_tools

        if self.effort and self.model.startswith(_EFFORT_MODELS):
            kwargs["output_config"] = {"effort": self.effort}

        # Features a proxy in front of the API may not understand.
        if self.base_url == ANTHROPIC_API_URL:
            kwargs["cache_control"] = {"type": "ephemeral"}
            if self.model in _FALLBACK_MODELS:
                kwargs["betas"] = [_FALLBACK_BETA]
                kwargs["fallbacks"] = "default"

        with self._client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()

        return self._parse_response(message.to_dict())

    # ------------------------------------------------------------------
    # Tool schema conversion
    # ------------------------------------------------------------------
    def _build_tools(
        self, tools: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Convert internal tool definitions to Anthropic format."""
        api_tools: List[Dict[str, Any]] = []

        # Standard function tools
        if tools:
            for t in tools:
                api_tools.append({
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
                })

        return api_tools

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        """Parse Anthropic response into canonical LLMResponse."""
        content_blocks = data.get("content", [])

        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []

        for block in content_blocks:
            btype = block.get("type")

            if btype == "text":
                text_parts.append(block["text"])

            elif btype == "tool_use":
                tool_calls.append({
                    "call_id": block["id"],
                    "tool": block["name"],
                    "arguments": block.get("input", {}),
                })

        # A declined request is a normal response with this stop reason. Anything written before
        # the decline is discarded, and an unfinished tool call must not run.
        stop_reason = data.get("stop_reason") or ""
        if stop_reason == "refusal":
            text_parts, tool_calls = [], []

        # Usage. The API counts cached tokens separately from input_tokens.
        usage_raw = data.get("usage") or {}
        cache_read = usage_raw.get("cache_read_input_tokens") or 0
        cache_write = usage_raw.get("cache_creation_input_tokens") or 0
        prompt_tokens = (usage_raw.get("input_tokens") or 0) + cache_read + cache_write
        completion_tokens = usage_raw.get("output_tokens") or 0
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        }

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            model=data.get("model", self.model),
            usage=usage,
            raw=data,
            stop_reason=stop_reason,
        )

    # ------------------------------------------------------------------
    # Message format conversion
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_system(
        messages: List[Dict[str, Any]],
    ) -> tuple:
        """Pull out the system message (if any) and return (system_text, rest)."""
        if messages and messages[0].get("role") == "system":
            return messages[0].get("content", ""), messages[1:]
        return "", messages

    @staticmethod
    def _convert_messages(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert internal message format → Anthropic Messages API format.

        Key differences from OpenAI:
        - Tool results use role="user" with tool_result content blocks
        - Assistant tool calls use tool_use content blocks
        - No separate tool_call_id field at message level
        """
        out: List[Dict[str, Any]] = []

        for m in messages:
            role = m["role"]

            if role == "system":
                # System messages are handled separately; skip here
                continue

            elif role == "tool":
                # Anthropic: tool results are sent as user messages
                out.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", ""),
                            "content": m.get("content", ""),
                        }
                    ],
                })

            elif role == "assistant" and m.get("raw_content"):
                # The model's own blocks (LLMResponse.raw["content"]). Thinking blocks have to
                # come back unmodified during a tool loop.
                out.append({"role": "assistant", "content": m["raw_content"]})

            elif role == "assistant" and m.get("tool_calls"):
                # Assistant messages with tool calls → content blocks
                blocks: List[Dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["call_id"],
                        "name": tc["tool"],
                        "input": tc["arguments"],
                    })
                out.append({"role": "assistant", "content": blocks})

            elif role == "assistant":
                out.append({"role": "assistant", "content": m.get("content", "")})

            elif role == "user":
                out.append({"role": "user", "content": m.get("content", "")})

            else:
                # Fallback for any other role
                out.append({"role": "user", "content": m.get("content", "")})

        return out
