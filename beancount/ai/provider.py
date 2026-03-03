"""LLM provider abstraction layer.

Supports OpenAI, Anthropic, and Ollama backends through a unified interface.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import json
import os
from abc import ABC
from abc import abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """Send a prompt to the LLM and return the response text.

        Args:
          prompt: The user prompt to send.
          system: An optional system prompt.
        Returns:
          The response text from the LLM.
        """

    @abstractmethod
    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        """Send a prompt and parse the response as JSON.

        Args:
          prompt: The user prompt to send.
          system: An optional system prompt.
        Returns:
          A parsed JSON dict from the LLM response.
        """


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (GPT-4, etc.)."""

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise ImportError(
                    "openai package required for OpenAI provider. "
                    "Install with: pip install openai"
                )
            self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> str:
        client = self._get_client()
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return response.choices[0].message.content

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        text = self.complete(prompt, system)
        return _extract_json(text)


class AnthropicProvider(LLMProvider):
    """Anthropic API provider (Claude)."""

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise ImportError(
                    "anthropic package required for Anthropic provider. "
                    "Install with: pip install anthropic"
                )
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> str:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        message = client.messages.create(**kwargs)
        return message.content[0].text

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        text = self.complete(prompt, system)
        return _extract_json(text)


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, model: str = "llama3.1", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete(self, prompt: str, system: str | None = None) -> str:
        import urllib.request

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["response"]

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        text = self.complete(prompt, system)
        return _extract_json(text)


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response text, handling markdown code blocks."""
    text = text.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


# Provider registry.
_PROVIDERS: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}


def get_provider(name: str | None = None, **kwargs) -> LLMProvider:
    """Get an LLM provider by name.

    If no name is given, auto-detects based on available environment variables.

    Args:
      name: Provider name ('openai', 'anthropic', 'ollama') or None for auto.
      **kwargs: Additional keyword arguments passed to the provider constructor.
    Returns:
      An LLMProvider instance.
    """
    if name is not None:
        name = name.lower()
        if name not in _PROVIDERS:
            raise ValueError(
                f"Unknown provider '{name}'. "
                f"Available: {', '.join(sorted(_PROVIDERS))}"
            )
        return _PROVIDERS[name](**kwargs)

    # Auto-detect from environment.
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicProvider(**kwargs)
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIProvider(**kwargs)
    # Fall back to Ollama (local, no key needed).
    return OllamaProvider(**kwargs)
