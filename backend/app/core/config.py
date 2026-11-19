"""Application configuration.

Values can be overridden with environment variables. No secrets are
stored here.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",  # Vite dev server
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)

# backend/app/core/config.py -> parents[2] is the `backend/` directory.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _load_cors_origins() -> tuple[str, ...]:
    raw = os.getenv("ROOTPATCH_CORS_ORIGINS")
    if not raw:
        return _DEFAULT_CORS_ORIGINS
    origins = tuple(o.strip() for o in raw.split(",") if o.strip())
    return origins or _DEFAULT_CORS_ORIGINS


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _load_workspace_dir() -> Path:
    raw = os.getenv("ROOTPATCH_WORKSPACE_DIR")
    return Path(raw).expanduser() if raw else _BACKEND_DIR / "workspace"


def _upload_limit() -> int:
    return _env_int("ROOTPATCH_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)


def _files_limit() -> int:
    return _env_int("ROOTPATCH_MAX_EXTRACTED_FILES", 5000)


def _total_limit() -> int:
    return _env_int("ROOTPATCH_MAX_EXTRACTED_TOTAL_BYTES", 200 * 1024 * 1024)


def _file_limit() -> int:
    return _env_int("ROOTPATCH_MAX_EXTRACTED_FILE_BYTES", 25 * 1024 * 1024)


def _structure_limit() -> int:
    return _env_int("ROOTPATCH_MAX_STRUCTURE_NODES", 5000)


def _scan_files_limit() -> int:
    return _env_int("ROOTPATCH_MAX_SCAN_FILES", 1000)


def _scan_file_bytes_limit() -> int:
    return _env_int("ROOTPATCH_MAX_SCAN_FILE_BYTES", 2 * 1024 * 1024)


def _scanner_timeout_limit() -> int:
    return _env_int("ROOTPATCH_SCANNER_TIMEOUT_SECONDS", 30)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else default


def _env_optional_str(name: str) -> str | None:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else None


def _llm_provider() -> str:
    return _env_str("ROOTPATCH_LLM_PROVIDER", "gemini").lower()


def _llm_model() -> str:
    return _env_str("ROOTPATCH_LLM_MODEL", "gemini-4-hydrogen")


def _llm_api_key() -> str | None:
    explicit = _env_optional_str("ROOTPATCH_LLM_API_KEY")
    if explicit:
        return explicit
    provider = _llm_provider()
    if provider == "gemini":
        return _env_optional_str("GEMINI_API_KEY")
    if provider == "openai":
        return _env_optional_str("OPENAI_API_KEY")
    return None


def _llm_base_url() -> str | None:
    return _env_optional_str("ROOTPATCH_LLM_BASE_URL")


def _llm_timeout() -> int:
    return _env_int("ROOTPATCH_LLM_TIMEOUT_SECONDS", 30)


def _context_before() -> int:
    return _env_int("ROOTPATCH_CONTEXT_LINES_BEFORE", 20)


def _context_after() -> int:
    return _env_int("ROOTPATCH_CONTEXT_LINES_AFTER", 20)


def _context_file_bytes() -> int:
    return _env_int("ROOTPATCH_MAX_CONTEXT_FILE_BYTES", 512 * 1024)


def _context_chars_per_finding() -> int:
    return _env_int("ROOTPATCH_MAX_CONTEXT_CHARS_PER_FINDING", 8000)


def _total_context_chars() -> int:
    return _env_int("ROOTPATCH_MAX_TOTAL_CONTEXT_CHARS", 32000)


def _max_findings_per_analysis() -> int:
    return _env_int("ROOTPATCH_MAX_FINDINGS_PER_ANALYSIS", 50)


@dataclass(frozen=True)
class Settings:
    app_name: str = "RootPatch"
    app_version: str = "0.1.0"
    app_description: str = (
        "Explainable software bug detection and repair system."
    )
    cors_origins: tuple[str, ...] = field(default_factory=_load_cors_origins)

    # --- Step 2: project upload and inspection ---
    workspace_dir: Path = field(default_factory=_load_workspace_dir)
    max_upload_bytes: int = field(default_factory=_upload_limit)
    max_extracted_files: int = field(default_factory=_files_limit)
    max_extracted_total_bytes: int = field(default_factory=_total_limit)
    max_extracted_file_bytes: int = field(default_factory=_file_limit)
    max_structure_nodes: int = field(default_factory=_structure_limit)

    # --- Step 3: static bug detection ---
    max_scan_files: int = field(default_factory=_scan_files_limit)
    max_scan_file_bytes: int = field(default_factory=_scan_file_bytes_limit)
    scanner_timeout_seconds: int = field(default_factory=_scanner_timeout_limit)

    # --- Step 4: AI-powered root cause analysis ---
    llm_provider: str = field(default_factory=_llm_provider)
    llm_model: str = field(default_factory=_llm_model)
    llm_api_key: str | None = field(default_factory=_llm_api_key, repr=False)
    llm_base_url: str | None = field(default_factory=_llm_base_url)
    llm_timeout_seconds: int = field(default_factory=_llm_timeout)
    max_context_lines_before: int = field(default_factory=_context_before)
    max_context_lines_after: int = field(default_factory=_context_after)
    max_context_file_bytes: int = field(default_factory=_context_file_bytes)
    max_context_chars_per_finding: int = field(default_factory=_context_chars_per_finding)
    max_total_context_chars: int = field(default_factory=_total_context_chars)
    max_findings_per_analysis: int = field(default_factory=_max_findings_per_analysis)


settings = Settings()


def get_settings() -> Settings:
    """FastAPI dependency; tests override this to use temporary workspaces."""
    return settings
