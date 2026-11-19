"""Application configuration.

Values can be overridden with environment variables. No secrets are
stored here.
"""

import os
from dataclasses import dataclass, field

_DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",  # Vite dev server
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def _load_cors_origins() -> tuple[str, ...]:
    raw = os.getenv("ROOTPATCH_CORS_ORIGINS")
    if not raw:
        return _DEFAULT_CORS_ORIGINS
    origins = tuple(o.strip() for o in raw.split(",") if o.strip())
    return origins or _DEFAULT_CORS_ORIGINS


@dataclass(frozen=True)
class Settings:
    app_name: str = "RootPatch"
    app_version: str = "0.1.0"
    app_description: str = (
        "Explainable software bug detection and repair system."
    )
    cors_origins: tuple[str, ...] = field(default_factory=_load_cors_origins)


settings = Settings()
