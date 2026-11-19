"""Small, dependency-free filesystem helpers."""

import re
import shutil
from pathlib import Path
from typing import Optional

_PROJECT_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def is_valid_project_id(value: str) -> bool:
    """Project IDs are server-generated uuid4 hex strings; nothing else is accepted."""
    return bool(_PROJECT_ID_PATTERN.fullmatch(value))


def sanitize_display_name(
    raw: Optional[str], fallback: str = "unnamed-project", max_length: int = 100
) -> str:
    """Make a user-supplied name safe to display. Never use the result as a path."""
    if not raw:
        return fallback
    cleaned = _CONTROL_CHARS.sub("", raw).replace("/", "_").replace("\\", "_")
    cleaned = cleaned.strip()[:max_length].strip()
    return cleaned or fallback


def is_within_directory(base: Path, target: Path) -> bool:
    """True if `target` resolves to a location inside `base`."""
    return target.resolve().is_relative_to(base.resolve())


def remove_tree(path: Path) -> None:
    """Best-effort recursive delete used for cleanup of failed uploads."""
    shutil.rmtree(path, ignore_errors=True)


def format_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


_TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__", "spec", "specs"})


def is_python_test_path(rel_path: str) -> bool:
    """True when `rel_path` refers to a Python test module or file inside a test directory."""
    parts = [p.lower() for p in rel_path.replace("\\", "/").split("/") if p and p != "."]
    if not parts:
        return False
    filename = parts[-1]
    if not filename.endswith((".py", ".pyw")):
        return False
    if any(part in _TEST_DIR_NAMES for part in parts[:-1]):
        return True
    return filename.startswith("test_") or filename.endswith("_test.py") or filename == "conftest.py"
