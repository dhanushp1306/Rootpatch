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
_REPO_ROOT = _BACKEND_DIR.parent


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


def resolve_workspace_dir(raw: str | None = None) -> Path:
    """Resolve the RootPatch workspace directory deterministically.

    Relative paths are anchored to `backend/` (or the repository root when
    prefixed with `backend/`) rather than `os.getcwd()`, so startup from either
    `<repo>` or `<repo>/backend` resolves to the same canonical workspace.
    """
    value = os.getenv("ROOTPATCH_WORKSPACE_DIR") if raw is None else raw
    cleaned = value.strip().strip('"').strip("'") if value else ""
    if not cleaned:
        return (_BACKEND_DIR / "workspace").resolve()

    expanded = Path(cleaned).expanduser()
    if expanded.is_absolute():
        return expanded.resolve()

    normalized_parts = tuple(
        part for part in cleaned.replace("\\", "/").split("/") if part and part != "."
    )
    if normalized_parts and normalized_parts[0] == _BACKEND_DIR.name:
        return (_REPO_ROOT.joinpath(*normalized_parts)).resolve()
    if normalized_parts:
        return (_BACKEND_DIR.joinpath(*normalized_parts)).resolve()
    return (_BACKEND_DIR / "workspace").resolve()


def _load_workspace_dir() -> Path:
    return resolve_workspace_dir()


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
    explicit = _env_optional_str("ROOTPATCH_LLM_MODEL")
    if explicit:
        return explicit
    if _llm_provider() in ("xai", "grok"):
        return "grok-4.7"
    return "gemini-4-hydrogen"


def _llm_api_key() -> str | None:
    explicit = _env_optional_str("ROOTPATCH_LLM_API_KEY")
    if explicit:
        return explicit
    provider = _llm_provider()
    if provider == "gemini":
        return _env_optional_str("GEMINI_API_KEY")
    if provider == "openai":
        return _env_optional_str("OPENAI_API_KEY")
    if provider in ("xai", "grok"):
        return _env_optional_str("XAI_API_KEY")
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


def _max_patch_diff_bytes() -> int:
    return _env_int("ROOTPATCH_MAX_PATCH_DIFF_BYTES", 262144)


def _max_patch_hunks() -> int:
    return _env_int("ROOTPATCH_MAX_PATCH_HUNKS", 25)


def _max_patches_per_run() -> int:
    return _env_int("ROOTPATCH_MAX_PATCHES_PER_RUN", 25)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    return default


def _validation_timeout_seconds() -> int:
    return _env_int("ROOTPATCH_VALIDATION_TIMEOUT_SECONDS", 60)


def _validation_memory_limit() -> str:
    return _env_str("ROOTPATCH_VALIDATION_MEMORY_LIMIT", "512m")


def _validation_cpus() -> str:
    return _env_str("ROOTPATCH_VALIDATION_CPUS", "1.0")


def _validation_pids_limit() -> int:
    return _env_int("ROOTPATCH_VALIDATION_PIDS_LIMIT", 64)


def _max_validation_output_bytes() -> int:
    return _env_int("ROOTPATCH_MAX_VALIDATION_OUTPUT_BYTES", 65536)


def _validation_python_image() -> str:
    return _env_str("ROOTPATCH_VALIDATION_PYTHON_IMAGE", "python:3.11-slim")


def _validation_node_image() -> str:
    return _env_str("ROOTPATCH_VALIDATION_NODE_IMAGE", "node:20-slim")


def _validation_network_disabled() -> bool:
    return _env_bool("ROOTPATCH_VALIDATION_NETWORK_DISABLED", True)


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

    # --- Step 5: automated patch generation ---
    max_patch_diff_bytes: int = field(default_factory=_max_patch_diff_bytes)
    max_patch_hunks: int = field(default_factory=_max_patch_hunks)
    max_patches_per_run: int = field(default_factory=_max_patches_per_run)

    # --- Step 7: isolated testing and patch validation ---
    validation_timeout_seconds: int = field(default_factory=_validation_timeout_seconds)
    validation_memory_limit: str = field(default_factory=_validation_memory_limit)
    validation_cpus: str = field(default_factory=_validation_cpus)
    validation_pids_limit: int = field(default_factory=_validation_pids_limit)
    max_validation_output_bytes: int = field(default_factory=_max_validation_output_bytes)
    validation_python_image: str = field(default_factory=_validation_python_image)
    validation_node_image: str = field(default_factory=_validation_node_image)
    validation_network_disabled: bool = field(default_factory=_validation_network_disabled)

    def __post_init__(self) -> None:
        if not self.workspace_dir.is_absolute():
            object.__setattr__(
                self,
                "workspace_dir",
                resolve_workspace_dir(str(self.workspace_dir)),
            )


settings = Settings()


def get_settings() -> Settings:
    """FastAPI dependency; tests override this to use temporary workspaces."""
    return settings
