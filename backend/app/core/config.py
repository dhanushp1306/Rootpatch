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


settings = Settings()


def get_settings() -> Settings:
    """FastAPI dependency; tests override this to use temporary workspaces."""
    return settings
