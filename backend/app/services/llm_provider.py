"""Modular LLM provider abstraction for Step 4 root cause analysis.

Provider configuration and HTTP transport are kept completely separate from
root cause analysis business logic. API keys are never hardcoded, logged,
placed in URL query parameters, or echoed in error responses.
"""

import json
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class LLMProvider(Protocol):
    """Pluggable interface for generating structured JSON analysis from prompts."""

    def analyze(self, system_prompt: str, user_prompt: str, settings: Settings) -> str:
        ...


class GeminiLLMProvider:
    """Google Gemini REST API client via httpx."""

    def analyze(self, system_prompt: str, user_prompt: str, settings: Settings) -> str:
        api_key = settings.llm_api_key
        if not api_key:
            raise LLMConfigurationError(
                "LLM provider is not configured. Set ROOTPATCH_LLM_API_KEY or GEMINI_API_KEY."
            )

        base = (settings.llm_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url = f"{base}/models/{settings.llm_model}:generateContent"

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "User-Agent": "rootpatch-backend",
        }

        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Gemini request timed out after {settings.llm_timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"Network error contacting Gemini provider: {type(exc).__name__}."
            ) from exc

        if response.status_code == 429:
            raise LLMRateLimitError("Gemini API rate limit exceeded. Please retry later.")
        if response.status_code in (401, 403):
            raise LLMProviderError(
                "Gemini API authentication failed; verify the configured API key.",
                status_code=502,
            )
        if response.status_code >= 400:
            raise LLMProviderError(
                f"Gemini API returned HTTP {response.status_code}.",
                status_code=502,
            )

        try:
            data = response.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise LLMProviderError("Gemini response contained no candidates.")
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text_chunks = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
            text = "".join(text_chunks).strip()
            if not text:
                raise LLMProviderError("Gemini response contained empty content.")
            return text
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Gemini returned an unreadable response payload.") from exc


class OpenAICompatibleLLMProvider:
    """OpenAI / OpenAI-compatible chat completions REST client via httpx."""

    def __init__(
        self,
        default_base_url: str | None = None,
        api_key_env_hint: str | None = None,
    ) -> None:
        self.default_base_url = default_base_url
        self.api_key_env_hint = api_key_env_hint

    def analyze(self, system_prompt: str, user_prompt: str, settings: Settings) -> str:
        provider_name = (settings.llm_provider or "").strip().lower()
        is_xai = provider_name in ("xai", "grok")

        api_key = settings.llm_api_key
        if not api_key:
            env_hint = self.api_key_env_hint or ("XAI_API_KEY" if is_xai else "OPENAI_API_KEY")
            raise LLMConfigurationError(
                f"LLM provider is not configured. Set ROOTPATCH_LLM_API_KEY or {env_hint}."
            )

        fallback_base = self.default_base_url or (
            "https://api.x.ai/v1" if is_xai else "https://api.openai.com/v1"
        )
        base = (settings.llm_base_url or fallback_base).rstrip("/")
        url = f"{base}/chat/completions"

        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"LLM provider request timed out after {settings.llm_timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"Network error contacting LLM provider: {type(exc).__name__}."
            ) from exc

        if response.status_code == 429:
            raise LLMRateLimitError("LLM provider rate limit exceeded. Please retry later.")
        if response.status_code in (401, 403):
            raise LLMProviderError(
                "LLM provider authentication failed; verify the configured API key.",
                status_code=502,
            )
        if response.status_code >= 400:
            raise LLMProviderError(
                f"LLM provider returned HTTP {response.status_code}.",
                status_code=502,
            )

        try:
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise LLMProviderError("LLM provider returned no completion choices.")
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "").strip()
            if not content:
                raise LLMProviderError("LLM provider returned empty message content.")
            return content
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("LLM provider returned an unreadable response payload.") from exc


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Instantiate the configured LLM provider without running any API call yet."""
    provider_name = (settings.llm_provider or "gemini").strip().lower()
    if provider_name == "gemini":
        return GeminiLLMProvider()
    if provider_name in ("openai", "openai-compatible"):
        return OpenAICompatibleLLMProvider(
            default_base_url="https://api.openai.com/v1",
            api_key_env_hint="OPENAI_API_KEY",
        )
    if provider_name in ("xai", "grok"):
        return OpenAICompatibleLLMProvider(
            default_base_url="https://api.x.ai/v1",
            api_key_env_hint="XAI_API_KEY",
        )
    raise LLMConfigurationError(
        f"Unsupported LLM provider '{settings.llm_provider}'. Supported providers: gemini, openai, xai, grok."
    )


def get_llm_provider() -> LLMProvider | None:
    """FastAPI dependency returning an optional pre-injected LLM provider (used by tests)."""
    return None


def strip_json_fences(raw_text: str) -> str:
    """Extract JSON payload if a model wrapped it in markdown code fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Validate early that string is plausibly JSON
    json.loads(text)
    return text
