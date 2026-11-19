"""Tests for LLM provider configuration and transport (Gemini, OpenAI, and Grok/xAI)."""

import difflib
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings, settings as default_settings
from app.core.errors import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.services.llm_provider import (
    GeminiLLMProvider,
    OpenAICompatibleLLMProvider,
    build_llm_provider,
    get_llm_provider,
    strip_json_fences,
)
from conftest import upload
from main import app


def _clear_llm_env(monkeypatch):
    for name in (
        "ROOTPATCH_LLM_PROVIDER",
        "ROOTPATCH_LLM_MODEL",
        "ROOTPATCH_LLM_API_KEY",
        "ROOTPATCH_LLM_BASE_URL",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "XAI_API_KEY",
        "GROQ_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


class _DummyHttpClient:
    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._handler(url, **kwargs)


# --- Configuration defaults & API key resolution ---


def test_gemini_config_defaults_unchanged(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gem-fallback-key")

    cfg = Settings()
    assert cfg.llm_provider == "gemini"
    assert cfg.llm_model == "gemini-4-hydrogen"
    assert cfg.llm_api_key == "gem-fallback-key"
    assert cfg.llm_base_url is None


def test_openai_config_fallback_and_explicit_priority(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ROOTPATCH_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")

    cfg = Settings()
    assert cfg.llm_provider == "openai"
    assert cfg.llm_model == "gemini-4-hydrogen"
    assert cfg.llm_api_key == "openai-fallback-key"

    monkeypatch.setenv("ROOTPATCH_LLM_API_KEY", "explicit-priority-key")
    cfg_explicit = Settings()
    assert cfg_explicit.llm_api_key == "explicit-priority-key"


@pytest.mark.parametrize("provider_name", ["xai", "grok", "XAI", "Grok"])
def test_xai_grok_config_defaults_and_key_priority(monkeypatch, provider_name):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ROOTPATCH_LLM_PROVIDER", provider_name)
    monkeypatch.setenv("XAI_API_KEY", "xai-fallback-key")

    cfg = Settings()
    assert cfg.llm_provider == provider_name.lower()
    assert cfg.llm_model == "grok-4.7"
    assert cfg.llm_api_key == "xai-fallback-key"
    assert cfg.llm_base_url is None

    # ROOTPATCH_LLM_API_KEY takes priority over XAI_API_KEY.
    monkeypatch.setenv("ROOTPATCH_LLM_API_KEY", "explicit-rootpatch-key")
    monkeypatch.setenv("ROOTPATCH_LLM_MODEL", "grok-custom-model")
    monkeypatch.setenv("ROOTPATCH_LLM_BASE_URL", "https://custom.x.ai/v1")

    cfg_override = Settings()
    assert cfg_override.llm_api_key == "explicit-rootpatch-key"
    assert cfg_override.llm_model == "grok-custom-model"
    assert cfg_override.llm_base_url == "https://custom.x.ai/v1"


def test_xai_api_key_not_used_for_other_providers(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ROOTPATCH_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("XAI_API_KEY", "xai-only-key")

    cfg = Settings()
    assert cfg.llm_api_key is None
    assert cfg.llm_model == "gemini-4-hydrogen"


# --- Provider factory selection ---


@pytest.mark.parametrize("provider_name", ["xai", "grok", " xai ", "GROK"])
def test_build_llm_provider_selects_openai_compatible_for_xai_and_grok(provider_name):
    s = replace(default_settings, llm_provider=provider_name, llm_api_key="test-key")
    provider = build_llm_provider(s)
    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.default_base_url == "https://api.x.ai/v1"


def test_build_llm_provider_preserves_gemini_and_openai():
    assert isinstance(
        build_llm_provider(replace(default_settings, llm_provider="gemini")),
        GeminiLLMProvider,
    )
    openai_provider = build_llm_provider(replace(default_settings, llm_provider="openai"))
    assert isinstance(openai_provider, OpenAICompatibleLLMProvider)
    assert openai_provider.default_base_url == "https://api.openai.com/v1"

    with pytest.raises(LLMConfigurationError):
        build_llm_provider(replace(default_settings, llm_provider="unknown-provider"))


# --- HTTP transport, URLs, parsing, and error handling ---


@pytest.mark.parametrize("provider_name", ["xai", "grok"])
def test_grok_default_url_payload_and_response_parsing(provider_name):
    expected_json = json.dumps({"analyses": [], "limitations": []})
    http_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": expected_json}}]},
        )
    )
    cfg = replace(
        default_settings,
        llm_provider=provider_name,
        llm_model="grok-4.7",
        llm_api_key="placeholder-xai-key",
        llm_base_url=None,
    )
    provider = build_llm_provider(cfg)

    with patch("app.services.llm_provider.httpx.Client", return_value=http_client):
        result = provider.analyze("system instructions", "user payload", cfg)

    assert result == expected_json
    assert strip_json_fences(result) == expected_json
    assert len(http_client.calls) == 1
    called_url, called_kwargs = http_client.calls[0]
    assert called_url == "https://api.x.ai/v1/chat/completions"
    assert called_kwargs["headers"]["Authorization"] == "Bearer placeholder-xai-key"
    assert called_kwargs["json"]["model"] == "grok-4.7"
    assert called_kwargs["json"]["response_format"] == {"type": "json_object"}
    assert called_kwargs["json"]["messages"] == [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "user payload"},
    ]


def test_grok_base_url_override_and_openai_default_unchanged():
    http_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )
    )

    grok_override_cfg = replace(
        default_settings,
        llm_provider="xai",
        llm_model="grok-4.7",
        llm_api_key="placeholder-xai-key",
        llm_base_url="https://proxy.example.internal/v1/",
    )
    openai_cfg = replace(
        default_settings,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        llm_api_key="placeholder-openai-key",
        llm_base_url=None,
    )

    with patch("app.services.llm_provider.httpx.Client", return_value=http_client):
        build_llm_provider(grok_override_cfg).analyze("s", "u", grok_override_cfg)
        build_llm_provider(openai_cfg).analyze("s", "u", openai_cfg)

    assert http_client.calls[0][0] == "https://proxy.example.internal/v1/chat/completions"
    assert http_client.calls[1][0] == "https://api.openai.com/v1/chat/completions"


def test_gemini_regression_url_headers_and_parsing():
    http_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=200,
            json={"candidates": [{"content": {"parts": [{"text": '{"analyses": []}'}]}}]},
        )
    )
    gemini_cfg = replace(
        default_settings,
        llm_provider="gemini",
        llm_model="gemini-4-hydrogen",
        llm_api_key="placeholder-gemini-key",
        llm_base_url=None,
    )

    with patch("app.services.llm_provider.httpx.Client", return_value=http_client):
        result = build_llm_provider(gemini_cfg).analyze("sys", "usr", gemini_cfg)

    assert result == '{"analyses": []}'
    called_url, called_kwargs = http_client.calls[0]
    assert called_url == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-hydrogen:generateContent"
    )
    assert called_kwargs["headers"]["x-goog-api-key"] == "placeholder-gemini-key"
    assert called_kwargs["json"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("provider_name", ["xai", "grok"])
def test_grok_missing_api_key_raises_configuration_error(provider_name):
    cfg = replace(default_settings, llm_provider=provider_name, llm_api_key=None)
    provider = build_llm_provider(cfg)
    with pytest.raises(LLMConfigurationError) as exc_info:
        provider.analyze("sys", "usr", cfg)
    detail = str(exc_info.value)
    assert "not configured" in detail.lower()
    assert "XAI_API_KEY" in detail


@pytest.mark.parametrize("status_code", [401, 403])
def test_grok_authentication_failure_raises_502_without_exposing_key(status_code):
    secret = "xai-very-secret-placeholder-value"
    http_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=status_code,
            json={"error": f"invalid api key {secret}"},
        )
    )
    cfg = replace(
        default_settings,
        llm_provider="xai",
        llm_model="grok-4.7",
        llm_api_key=secret,
    )
    with patch("app.services.llm_provider.httpx.Client", return_value=http_client):
        with pytest.raises(LLMProviderError) as exc_info:
            build_llm_provider(cfg).analyze("sys", "usr", cfg)

    assert exc_info.value.status_code == 502
    assert secret not in str(exc_info.value)


def test_grok_rate_limit_timeout_http_error_and_malformed_responses():
    cfg = replace(
        default_settings,
        llm_provider="grok",
        llm_model="grok-4.7",
        llm_api_key="placeholder-key",
    )
    provider = build_llm_provider(cfg)

    # 429 rate limit
    rate_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(status_code=429, text="rate limited")
    )
    with patch("app.services.llm_provider.httpx.Client", return_value=rate_client):
        with pytest.raises(LLMRateLimitError):
            provider.analyze("sys", "usr", cfg)

    # 500 upstream error -> 502 LLMProviderError
    err_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(status_code=500, text="server error")
    )
    with patch("app.services.llm_provider.httpx.Client", return_value=err_client):
        with pytest.raises(LLMProviderError) as exc_500:
            provider.analyze("sys", "usr", cfg)
    assert exc_500.value.status_code == 502

    # Timeout
    def _raise_timeout(_url, **_kw):
        raise httpx.ReadTimeout("timed out")

    with patch("app.services.llm_provider.httpx.Client", return_value=_DummyHttpClient(_raise_timeout)):
        with pytest.raises(LLMTimeoutError):
            provider.analyze("sys", "usr", cfg)

    # Malformed non-JSON HTTP 200 payload
    bad_json_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(status_code=200, content=b"not-json")
    )
    with patch("app.services.llm_provider.httpx.Client", return_value=bad_json_client):
        with pytest.raises(LLMProviderError):
            provider.analyze("sys", "usr", cfg)

    # Empty choices
    empty_choices_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(status_code=200, json={"choices": []})
    )
    with patch("app.services.llm_provider.httpx.Client", return_value=empty_choices_client):
        with pytest.raises(LLMProviderError):
            provider.analyze("sys", "usr", cfg)

    # Empty content
    empty_content_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=200, json={"choices": [{"message": {"content": "   "}}]}
        )
    )
    with patch("app.services.llm_provider.httpx.Client", return_value=empty_content_client):
        with pytest.raises(LLMProviderError):
            provider.analyze("sys", "usr", cfg)


# --- End-to-end analysis and patch workflow compatibility with xai/grok ---


def test_xai_provider_end_to_end_analysis_and_patch_workflows(workspace, make_zip):
    old_code = "def greet():\n    return missing_symbol\n"
    new_code = "def greet():\n    return 'hello'\n"
    diff_text = "\n".join(
        difflib.unified_diff(
            old_code.splitlines(),
            new_code.splitlines(),
            fromfile="a/app.py",
            tofile="b/app.py",
            n=3,
            lineterm="",
        )
    ) + "\n"

    test_settings = replace(
        default_settings,
        workspace_dir=workspace,
        llm_provider="xai",
        llm_model="grok-4.7",
        llm_api_key="placeholder-xai-key",
        llm_base_url=None,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides.pop(get_llm_provider, None)

    try:
        client = TestClient(app)
        up = upload(client, make_zip({"proj/app.py": old_code}))
        assert up.status_code == 201
        pid = up.json()["project_id"]

        scan_resp = client.post(f"/api/projects/{pid}/scan")
        assert scan_resp.status_code == 200
        finding = scan_resp.json()["findings"][0]

        def _mock_post(url, **kwargs):
            assert url == "https://api.x.ai/v1/chat/completions"
            assert kwargs["json"]["model"] == "grok-4.7"
            assert kwargs["json"]["response_format"] == {"type": "json_object"}
            user_prompt = kwargs["json"]["messages"][1]["content"]
            if "unified_diff" in kwargs["json"]["messages"][0]["content"]:
                payload = {
                    "patches": [
                        {
                            "finding_id": finding["id"],
                            "target_file": "app.py",
                            "unified_diff": diff_text,
                            "summary": "Return literal greeting.",
                            "explanation": "Replaces undefined missing_symbol with string literal.",
                            "confidence": "HIGH",
                        }
                    ],
                    "limitations": [],
                }
            else:
                assert finding["id"] in user_prompt
                payload = {
                    "analyses": [
                        {
                            "finding_id": finding["id"],
                            "root_cause": "missing_symbol is undefined.",
                            "technical_explanation": "Line 2 references missing_symbol without defining it.",
                            "affected_component": "app.py:L2",
                            "impact": "Raises NameError when called.",
                            "recommended_fix": "Return a valid string value.",
                            "evidence": ["return missing_symbol"],
                            "assumptions_or_uncertainties": ["Assumes static string is intended."],
                            "related_finding_ids": [],
                            "confidence": "HIGH",
                            "confidence_reason": "Observed directly in source snippet.",
                            "analysis_status": "completed",
                        }
                    ],
                    "shared_root_cause_groups": [],
                    "limitations": [],
                }
            return SimpleNamespace(
                status_code=200,
                json=lambda p=payload: {"choices": [{"message": {"content": json.dumps(p)}}]},
            )

        with patch(
            "app.services.llm_provider.httpx.Client",
            return_value=_DummyHttpClient(_mock_post),
        ):
            analyze_resp = client.post(f"/api/projects/{pid}/analyze")
            assert analyze_resp.status_code == 200
            analyze_body = analyze_resp.json()
            assert analyze_body["provider"] == "xai"
            assert analyze_body["model"] == "grok-4.7"

            patch_resp = client.post(f"/api/projects/{pid}/patches/generate")
            assert patch_resp.status_code == 200
            patch_body = patch_resp.json()
            assert patch_body["provider"] == "xai"
            assert patch_body["model"] == "grok-4.7"
            assert patch_body["generated_count"] == 1
    finally:
        app.dependency_overrides.clear()


# --- Regression tests: Groq, OpenAI-compatible, fallback resolution & HTTP 400 ---


def test_groq_and_openai_compatible_provider_selection_and_key_resolution(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ROOTPATCH_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("ROOTPATCH_LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("ROOTPATCH_LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fallback_groq_key")

    cfg = Settings()
    assert cfg.llm_provider == "openai-compatible"
    assert cfg.llm_model == "openai/gpt-oss-120b"
    assert cfg.llm_api_key == "gsk_fallback_groq_key"
    assert cfg.llm_base_url == "https://api.groq.com/openai/v1"

    provider = build_llm_provider(cfg)
    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.default_base_url == "https://api.groq.com/openai/v1"
    assert provider.api_key_env_hint == "GROQ_API_KEY"

    # Test "groq" alias and default model
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ROOTPATCH_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_groq_alias_key")

    cfg_groq = Settings()
    assert cfg_groq.llm_provider == "groq"
    assert cfg_groq.llm_model == "llama-3.3-70b-versatile"
    assert cfg_groq.llm_api_key == "gsk_groq_alias_key"
    assert cfg_groq.llm_base_url == "https://api.groq.com/openai/v1"

    provider_groq = build_llm_provider(cfg_groq)
    assert isinstance(provider_groq, OpenAICompatibleLLMProvider)
    assert provider_groq.default_base_url == "https://api.groq.com/openai/v1"


def test_auto_detect_openai_compatible_from_groq_env(monkeypatch):
    # Auto-detect from ROOTPATCH_LLM_BASE_URL containing groq.com
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ROOTPATCH_LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")
    cfg1 = Settings()
    assert cfg1.llm_provider == "openai-compatible"

    # Auto-detect from GROQ_API_KEY
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test123")
    cfg2 = Settings()
    assert cfg2.llm_provider == "openai-compatible"
    assert cfg2.llm_api_key == "gsk_test123"

    # Auto-detect from ROOTPATCH_LLM_API_KEY starting with gsk_
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ROOTPATCH_LLM_API_KEY", "gsk_test456")
    cfg3 = Settings()
    assert cfg3.llm_provider == "openai-compatible"
    assert cfg3.llm_api_key == "gsk_test456"


def test_gemini_http_400_invalid_key_error_sanitization():
    secret_key = "AIzaSySecretGeminiKey12345"
    http_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=400,
            json={
                "error": {
                    "code": 400,
                    "message": f"API key not valid for {secret_key}. Please pass a valid API key.",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )
    )
    cfg = replace(
        default_settings,
        llm_provider="gemini",
        llm_model="gemini-4-hydrogen",
        llm_api_key=secret_key,
    )

    with patch("app.services.llm_provider.httpx.Client", return_value=http_client):
        with pytest.raises(LLMProviderError) as exc_info:
            build_llm_provider(cfg).analyze("sys", "usr", cfg)

    err = exc_info.value
    assert err.status_code == 502
    assert err.code == "llm_bad_request"
    assert "API key not valid" in err.message
    assert secret_key not in err.message


def test_gemini_http_400_invalid_model_error_sanitization():
    http_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=400,
            json={
                "error": {
                    "code": 400,
                    "message": "models/gemini-4-hydrogen is not found for API version v1beta, or is not supported for generateContent.",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )
    )
    cfg = replace(
        default_settings,
        llm_provider="gemini",
        llm_model="gemini-4-hydrogen",
        llm_api_key="placeholder-key",
    )

    with patch("app.services.llm_provider.httpx.Client", return_value=http_client):
        with pytest.raises(LLMProviderError) as exc_info:
            build_llm_provider(cfg).analyze("sys", "usr", cfg)

    err = exc_info.value
    assert err.status_code == 502
    assert err.code == "llm_bad_request"
    assert "models/gemini-4-hydrogen is not found" in err.message


def test_groq_http_400_model_not_found_error_sanitization():
    http_client = _DummyHttpClient(
        lambda _url, **_kw: httpx.Response(
            status_code=400,
            json={
                "error": {
                    "message": "The model 'openai/gpt-oss-120b' does not exist or you do not have access to it.",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            },
        )
    )
    cfg = replace(
        default_settings,
        llm_provider="openai-compatible",
        llm_model="openai/gpt-oss-120b",
        llm_base_url="https://api.groq.com/openai/v1",
        llm_api_key="gsk_placeholder_test",
    )

    with patch("app.services.llm_provider.httpx.Client", return_value=http_client):
        with pytest.raises(LLMProviderError) as exc_info:
            build_llm_provider(cfg).analyze("sys", "usr", cfg)

    err = exc_info.value
    assert err.status_code == 502
    assert err.code == "llm_bad_request"
    assert "Groq returned HTTP 400" in err.message
    assert "The model 'openai/gpt-oss-120b' does not exist" in err.message
    assert "gsk_placeholder_test" not in err.message


def test_groq_openai_compatible_end_to_end_analysis_and_patch(workspace, make_zip):
    old_code = "def calc():\n    return undefined_var\n"
    new_code = "def calc():\n    return 42\n"
    diff_text = "\n".join(
        difflib.unified_diff(
            old_code.splitlines(),
            new_code.splitlines(),
            fromfile="a/calc.py",
            tofile="b/calc.py",
            n=3,
            lineterm="",
        )
    ) + "\n"

    test_settings = replace(
        default_settings,
        workspace_dir=workspace,
        llm_provider="openai-compatible",
        llm_model="openai/gpt-oss-120b",
        llm_base_url="https://api.groq.com/openai/v1",
        llm_api_key="gsk_test_api_key",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides.pop(get_llm_provider, None)

    try:
        client = TestClient(app)
        up = upload(client, make_zip({"proj/calc.py": old_code}))
        assert up.status_code == 201
        pid = up.json()["project_id"]

        scan_resp = client.post(f"/api/projects/{pid}/scan")
        assert scan_resp.status_code == 200
        finding = scan_resp.json()["findings"][0]

        def _mock_post(url, **kwargs):
            assert url == "https://api.groq.com/openai/v1/chat/completions"
            assert kwargs["headers"]["Authorization"] == "Bearer gsk_test_api_key"
            assert kwargs["json"]["model"] == "openai/gpt-oss-120b"
            if "unified_diff" in kwargs["json"]["messages"][0]["content"]:
                payload = {
                    "patches": [
                        {
                            "finding_id": finding["id"],
                            "target_file": "calc.py",
                            "unified_diff": diff_text,
                            "summary": "Fix undefined_var.",
                            "explanation": "Return constant 42.",
                            "confidence": "HIGH",
                        }
                    ],
                    "limitations": [],
                }
            else:
                payload = {
                    "analyses": [
                        {
                            "finding_id": finding["id"],
                            "root_cause": "undefined_var is not defined.",
                            "technical_explanation": "calc.py references undefined_var.",
                            "affected_component": "calc.py:L2",
                            "impact": "Raises NameError.",
                            "recommended_fix": "Return integer 42.",
                            "evidence": ["return undefined_var"],
                            "assumptions_or_uncertainties": [],
                            "related_finding_ids": [],
                            "confidence": "HIGH",
                            "confidence_reason": "Direct code evidence.",
                            "analysis_status": "completed",
                        }
                    ],
                    "shared_root_cause_groups": [],
                    "limitations": [],
                }
            return SimpleNamespace(
                status_code=200,
                json=lambda p=payload: {"choices": [{"message": {"content": json.dumps(p)}}]},
            )

        with patch("app.services.llm_provider.httpx.Client", return_value=_DummyHttpClient(_mock_post)):
            analyze_resp = client.post(f"/api/projects/{pid}/analyze")
            assert analyze_resp.status_code == 200
            analyze_data = analyze_resp.json()
            assert analyze_data["provider"] == "openai-compatible"
            assert analyze_data["model"] == "openai/gpt-oss-120b"

            patch_resp = client.post(f"/api/projects/{pid}/patches/generate")
            assert patch_resp.status_code == 200
            patch_data = patch_resp.json()
            assert patch_data["provider"] == "openai-compatible"
            assert patch_data["model"] == "openai/gpt-oss-120b"
            assert patch_data["generated_count"] == 1
    finally:
        app.dependency_overrides.clear()
