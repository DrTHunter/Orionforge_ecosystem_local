"""LLM client interface and canonical response schema."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def accepts_temperature(model: str) -> bool:
    """Claude and the GPT-5 / o-series models reject a temperature (deprecated there); the rest take one.
    Works on a bare id or a provider-prefixed one (anthropic/claude-opus-5.5)."""
    bare = (model or "").lower().rsplit("/", 1)[-1]
    return not bare.startswith(("claude", "gpt-5", "o1", "o3", "o4"))


def temperature_param(model: str, value: Optional[float]) -> Dict[str, float]:
    """``{"temperature": value}`` for a request body, or ``{}`` when the model won't take one."""
    return {"temperature": value} if value is not None and accepts_temperature(model) else {}


@dataclass
class LLMResponse:
    """Provider-agnostic response from any chat completion call."""
    content: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    # Each tool_call dict: {"call_id": str, "tool": str, "arguments": dict}
    model: str = ""
    usage: Optional[Dict[str, int]] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""  # the provider's own reason, e.g. "refusal" when a safety system declined


class LLMClient(ABC):
    """Abstract base for all LLM provider clients."""

    model: str  # concrete classes must set this

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Send a chat completion request and return a normalised response."""
        ...
