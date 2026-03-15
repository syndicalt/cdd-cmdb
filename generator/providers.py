"""LLM provider abstraction for multi-model support.

Supports:
- Anthropic (Claude): claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5, etc.
- OpenAI: gpt-4o, o1-preview, o1-mini, etc.
- Google Gemini: gemini-2.0-flash, gemini-2.0-pro, etc.
- Ollama (local): any model via Ollama's OpenAI-compatible API
- LM Studio (local): any model via LM Studio's OpenAI-compatible API
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def generate(self, system: str, user: str, max_tokens: int = 32768) -> str:
        """Send a prompt and return the text response."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier."""


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-6"):
        import anthropic
        self._model = model
        self._client = anthropic.Anthropic()
        self._anthropic = anthropic  # for exception types

    def generate(self, system: str, user: str, max_tokens: int = 32768) -> str:
        import time

        retries = 3
        for attempt in range(retries):
            try:
                # Use streaming to avoid 10-minute timeout on large prompts
                text_parts: list[str] = []
                with self._client.messages.stream(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                ) as stream:
                    for text in stream.text_stream:
                        text_parts.append(text)
                return "".join(text_parts)
            except (
                self._anthropic.RateLimitError,
                self._anthropic.APIStatusError,
                self._anthropic.APIConnectionError,
            ) as e:
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1) * 5  # 10s, 20s
                    print(f"  API error: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

    @property
    def model_name(self) -> str:
        return self._model


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4o"):
        from openai import OpenAI
        self._model = model
        self._client = OpenAI()

    def generate(self, system: str, user: str, max_tokens: int = 32768) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    @property
    def model_name(self) -> str:
        return self._model


class GeminiProvider(LLMProvider):
    def __init__(self, model: str = "gemini-2.0-flash"):
        from google import genai
        self._model = model
        self._client = genai.Client()

    def generate(self, system: str, user: str, max_tokens: int = 32768) -> str:
        from google.genai import types
        response = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text or ""

    @property
    def model_name(self) -> str:
        return self._model


class OllamaProvider(LLMProvider):
    """Uses Ollama's OpenAI-compatible API at localhost:11434."""

    def __init__(self, model: str = "llama3"):
        from openai import OpenAI
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self._model = model
        self._client = OpenAI(base_url=base_url, api_key="ollama")

    def generate(self, system: str, user: str, max_tokens: int = 32768) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"


class LMStudioProvider(LLMProvider):
    """Uses LM Studio's OpenAI-compatible API at localhost:1234."""

    def __init__(self, model: str = "default"):
        from openai import OpenAI
        base_url = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        self._model = model
        self._client = OpenAI(base_url=base_url, api_key="lm-studio")

    def generate(self, system: str, user: str, max_tokens: int = 32768) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    @property
    def model_name(self) -> str:
        return f"lmstudio/{self._model}"


# --- Provider auto-detection ---

# Prefix -> provider class mapping
_PROVIDER_PREFIXES = {
    "claude-": "anthropic",
    "gpt-": "openai",
    "o1-": "openai",
    "o3-": "openai",
    "gemini-": "gemini",
    "ollama/": "ollama",
    "lmstudio/": "lmstudio",
}


def detect_provider(model: str) -> str:
    """Detect provider from model name. Returns provider key string."""
    model_lower = model.lower()
    for prefix, provider in _PROVIDER_PREFIXES.items():
        if model_lower.startswith(prefix):
            return provider
    # Fallback: check env vars
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "anthropic"  # default


def create_provider(model: str, provider: str | None = None) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        model: Model identifier (e.g. "claude-sonnet-4-6", "gpt-4o", "ollama/llama3")
        provider: Explicit provider override. Auto-detected from model name if None.
    """
    if provider is None:
        provider = detect_provider(model)

    provider = provider.lower()

    # Strip provider prefix from model name if present
    if provider == "ollama" and model.startswith("ollama/"):
        model = model[len("ollama/"):]
    elif provider == "lmstudio" and model.startswith("lmstudio/"):
        model = model[len("lmstudio/"):]

    if provider == "anthropic":
        return AnthropicProvider(model)
    elif provider == "openai":
        return OpenAIProvider(model)
    elif provider == "gemini":
        return GeminiProvider(model)
    elif provider == "ollama":
        return OllamaProvider(model)
    elif provider == "lmstudio":
        return LMStudioProvider(model)
    else:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Supported: anthropic, openai, gemini, ollama, lmstudio"
        )
