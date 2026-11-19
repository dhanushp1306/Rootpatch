"""Static test framework detection and safe test command validation (Step 7).

Inspects project structure, test filenames, and safe configuration text WITHOUT
executing any uploaded code. Produces allowlisted, shell-free command vectors
for isolated container execution.
"""

import json
import os
import re
import shlex
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.core.config import Settings
from app.core.errors import TestValidationError as _TestValidationError
from app.schemas.validation import (
    TestDetectionResult as _TestDetectionResult,
    TestFrameworkName,
)
from app.services.inspection_service import IGNORED_DIRECTORIES
from app.utils.file_utils import is_python_test_path, is_within_directory

_TestValidationError.__test__ = False
_TestDetectionResult.__test__ = False

MAX_CONFIG_READ_BYTES = 256 * 1024
MAX_TEST_INSPECT_BYTES = 64 * 1024
MAX_COMMAND_LENGTH = 512
MAX_COMMAND_TOKENS = 24

_JS_TEST_PATTERN = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")
_TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__", "spec", "specs"})

_SHELL_META_TOKENS = frozenset({";", "|", "&", "&&", "||", ">", ">>", "<", "<<"})
_SHELL_META_CHARS = re.compile(r"[;&|`$><\r\n\x00]")
_DISALLOWED_PYTHON_FLAGS = frozenset({"-c", "-e", "--command", "-"})
_DISALLOWED_NODE_FLAGS = frozenset({"-e", "--eval", "-p", "--print", "-c", "--check", "-r", "--require"})
_UNSAFE_ARG_PREFIXES = ("--rootdir=/", "--confcutdir=/", "-o=", "--basetemp=/")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _safe_read_text(path: Path, limit: int = MAX_CONFIG_READ_BYTES) -> Optional[str]:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > limit:
        raw = raw[:limit]
    return raw.decode("utf-8", errors="replace")


def _validate_relative_arg_path(token: str) -> None:
    if token.startswith("/"):
        if token == "/workspace" or token.startswith("/workspace/"):
            rel = token[len("/workspace"):].lstrip("/")
            if ".." in rel.split("/"):
                raise _TestValidationError("Test command argument escapes the project workspace.")
            return
        raise _TestValidationError(
            "Absolute host paths are not allowed in custom test commands.", 422
        )
    if _WINDOWS_DRIVE.match(token) or token.startswith("\\"):
        raise _TestValidationError("Unsafe path argument in custom test command.", 422)
    norm = token.replace("\\", "/")
    if ".." in [part for part in norm.split("/") if part]:
        raise _TestValidationError(
            "Path traversal ('..') is not allowed in custom test commands.", 422
        )


def _validate_extra_args(tokens: Sequence[str], *, allow_node_flags: bool = False) -> None:
    for tok in tokens:
        if _SHELL_META_CHARS.search(tok) or tok in _SHELL_META_TOKENS:
            raise _TestValidationError(
                "Shell metacharacters and command chaining are not allowed in test commands.", 422
            )
        if tok in _DISALLOWED_PYTHON_FLAGS and not allow_node_flags:
            raise _TestValidationError(f"Disallowed flag '{tok}' in custom test command.", 422)
        if allow_node_flags and tok in _DISALLOWED_NODE_FLAGS:
            raise _TestValidationError(f"Disallowed flag '{tok}' in custom test command.", 422)
        for prefix in _UNSAFE_ARG_PREFIXES:
            if tok.startswith(prefix):
                raise _TestValidationError(
                    "Host filesystem path options are not allowed in custom test commands.", 422
                )
        if tok.startswith("-"):
            if "=" in tok:
                _, rhs = tok.split("=", 1)
                if rhs.startswith("/") or ".." in rhs.split("/"):
                    _validate_relative_arg_path(rhs)
        else:
            _validate_relative_arg_path(tok)


def validate_test_command_override(
    raw_command: str | Sequence[str], settings: Settings
) -> _TestDetectionResult:
    """Strictly validate a user-supplied test command override against an allowlist.

    Rejects shell invocation, command chaining, arbitrary interpreter flags (`python -c`,
    `node -e`), and path escapes. Never invokes a shell.
    """
    if isinstance(raw_command, str):
        stripped = raw_command.strip()
        if not stripped:
            raise _TestValidationError("Custom test command cannot be empty.", 422)
        if len(stripped) > MAX_COMMAND_LENGTH:
            raise _TestValidationError(
                f"Custom test command exceeds maximum length of {MAX_COMMAND_LENGTH} characters.",
                422,
            )
        if _SHELL_META_CHARS.search(stripped):
            raise _TestValidationError(
                "Shell metacharacters and command chaining are not allowed in test commands.",
                422,
            )
        try:
            tokens = shlex.split(stripped, posix=True)
        except ValueError as exc:
            raise _TestValidationError("Malformed custom test command syntax.", 422) from exc
    else:
        tokens = [str(t) for t in raw_command]
        joined_len = sum(len(t) for t in tokens)
        if not tokens or joined_len > MAX_COMMAND_LENGTH:
            raise _TestValidationError("Custom test command is empty or too long.", 422)

    if not tokens or len(tokens) > MAX_COMMAND_TOKENS:
        raise _TestValidationError(
            f"Custom test command must contain between 1 and {MAX_COMMAND_TOKENS} arguments.",
            422,
        )

    for tok in tokens:
        if not tok or _SHELL_META_CHARS.search(tok) or tok in _SHELL_META_TOKENS:
            raise _TestValidationError(
                "Shell metacharacters and empty tokens are not allowed in test commands.",
                422,
            )

    head = tokens[0].lower()
    if "/" in head or "\\" in head:
        raise _TestValidationError(
            "Explicit executable paths are not allowed; use an allowlisted runner name.",
            422,
        )

    framework: TestFrameworkName
    ecosystem: str
    image: str
    final_cmd: List[str]

    if head == "pytest":
        rest = list(tokens[1:])
        _validate_extra_args(rest)
        if not any(a.startswith("cache_dir=") for a in rest):
            rest = ["-o", "cache_dir=/tmp/.pytest_cache", *rest]
        framework = "pytest"
        ecosystem = "Python"
        image = settings.validation_python_image
        final_cmd = ["python", "-m", "pytest", *rest]

    elif head in ("python", "python3"):
        if len(tokens) < 3 or tokens[1] != "-m":
            raise _TestValidationError(
                "Python test overrides must use 'python -m pytest ...' or 'python -m unittest ...'.",
                422,
            )
        module = tokens[2].lower()
        rest = list(tokens[3:])
        if module == "pytest":
            _validate_extra_args(rest)
            if not any(a.startswith("cache_dir=") for a in rest):
                rest = ["-o", "cache_dir=/tmp/.pytest_cache", *rest]
            framework = "pytest"
            final_cmd = ["python", "-m", "pytest", *rest]
        elif module == "unittest":
            _validate_extra_args(rest)
            framework = "unittest"
            final_cmd = ["python", "-m", "unittest", *(rest or ["discover", "-v"])]
        else:
            raise _TestValidationError(
                f"Module '{tokens[2]}' is not an allowlisted Python test runner.",
                422,
            )
        ecosystem = "Python"
        image = settings.validation_python_image

    elif head == "npm":
        if len(tokens) < 2 or tokens[1] != "test":
            raise _TestValidationError(
                "Only 'npm test' is allowed for npm test command overrides.",
                422,
            )
        rest = list(tokens[2:])
        _validate_extra_args(rest, allow_node_flags=True)
        framework = "npm"
        ecosystem = "Node.js"
        image = settings.validation_node_image
        final_cmd = ["npm", "test", *rest]

    elif head == "npx":
        idx = 1
        if idx < len(tokens) and tokens[idx] == "--no-install":
            idx += 1
        if idx >= len(tokens):
            raise _TestValidationError("Missing allowlisted runner after 'npx'.", 422)
        runner = tokens[idx].lower()
        if runner not in ("vitest", "jest"):
            raise _TestValidationError(
                f"Runner '{tokens[idx]}' is not allowlisted for npx validation.",
                422,
            )
        rest = list(tokens[idx + 1 :])
        _validate_extra_args(rest, allow_node_flags=True)
        if runner == "vitest" and "run" not in rest:
            rest = ["run", *rest]
        if runner == "jest" and "--runInBand" not in rest:
            rest = ["--runInBand", *rest]
        framework = "vitest" if runner == "vitest" else "jest"
        ecosystem = "Node.js"
        image = settings.validation_node_image
        final_cmd = ["npx", "--no-install", runner, *rest]

    elif head == "node":
        if len(tokens) < 2 or tokens[1] != "--test":
            raise _TestValidationError(
                "Node test overrides must start with 'node --test'.",
                422,
            )
        rest = list(tokens[2:])
        _validate_extra_args(rest, allow_node_flags=True)
        framework = "node_test"
        ecosystem = "Node.js"
        image = settings.validation_node_image
        final_cmd = ["node", "--test", *rest]

    else:
        raise _TestValidationError(
            f"Unsupported or disallowed test command '{tokens[0]}'. Allowed runners: pytest, python -m pytest, python -m unittest, npm test, npx vitest, npx jest, node --test.",
            422,
        )

    return _TestDetectionResult(
        detected=True,
        ecosystem=ecosystem,
        framework=framework,
        command=final_cmd,
        container_image=image,
    )


def _collect_project_test_inventory(
    project_root: Path,
) -> Dict[str, List[str]]:
    resolved_root = project_root.resolve()
    py_tests: List[str] = []
    py_conftests: List[str] = []
    js_tests: List[str] = []
    other_tests: List[str] = []
    configs: List[str] = []
    manifests: List[str] = []

    for dirpath, dirnames, filenames in os.walk(resolved_root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        safe_dirs = []
        for d in dirnames:
            cand = current / d
            if cand.is_symlink() or d in IGNORED_DIRECTORIES or d == "backups":
                continue
            if is_within_directory(resolved_root, cand):
                safe_dirs.append(d)
        dirnames[:] = safe_dirs

        rel_dir = current.relative_to(resolved_root).as_posix()
        rel_parts = () if rel_dir == "." else tuple(rel_dir.split("/"))
        in_test_dir = any(p.lower() in _TEST_DIR_NAMES for p in rel_parts)

        for name in filenames:
            full = current / name
            if full.is_symlink() or not full.is_file():
                continue
            if not is_within_directory(resolved_root, full):
                continue

            rel_path = name if rel_dir == "." else f"{rel_dir}/{name}"
            lower = name.lower()
            ext = Path(name).suffix.lower()

            if lower in (
                "pytest.ini",
                "pyproject.toml",
                "setup.cfg",
                "tox.ini",
                "package.json",
                "go.mod",
                "cargo.toml",
                "pom.xml",
                "build.gradle",
                "build.gradle.kts",
            ) or re.match(r"^requirements[-_.\w]*\.txt$", lower):
                manifests.append(rel_path)

            if lower in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "package.json"):
                configs.append(rel_path)

            if ext in (".py", ".pyw"):
                if lower == "conftest.py":
                    py_conftests.append(rel_path)
                elif is_python_test_path(rel_path):
                    py_tests.append(rel_path)
            elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
                if _JS_TEST_PATTERN.search(lower) or in_test_dir:
                    js_tests.append(rel_path)
            elif ext == ".go" and lower.endswith("_test.go"):
                other_tests.append(rel_path)
            elif ext == ".java" and re.search(r"(Test|Tests|IT)\.java$", name):
                other_tests.append(rel_path)

    return {
        "py_tests": py_tests,
        "py_conftests": py_conftests,
        "js_tests": js_tests,
        "other_tests": other_tests,
        "configs": configs,
        "manifests": manifests,
    }


def _select_target_python_tests(
    target_file: Optional[str], py_tests: List[str]
) -> List[str]:
    if not target_file or not py_tests:
        return []
    stem = Path(target_file).stem.lower()
    if not stem or stem == "__init__":
        return []
    matched = [
        t
        for t in py_tests
        if stem in Path(t).stem.lower()
    ]
    return matched


def _detect_python_framework(
    project_root: Path,
    py_tests: List[str],
    py_conftests: List[str],
    manifests: List[str],
) -> Tuple[TestFrameworkName, List[str]]:
    limitations: List[str] = []
    has_pytest_marker = bool(py_conftests)

    for rel in manifests:
        lower_name = Path(rel).name.lower()
        text = _safe_read_text(project_root / rel)
        if not text:
            continue
        lower_text = text.lower()
        if lower_name in ("pytest.ini", "tox.ini"):
            has_pytest_marker = True
        elif lower_name == "pyproject.toml" and (
            "[tool.pytest" in lower_text or "pytest" in lower_text
        ):
            has_pytest_marker = True
        elif lower_name == "setup.cfg" and (
            "[tool:pytest]" in lower_text or "[pytest]" in lower_text
        ):
            has_pytest_marker = True
        elif lower_name.startswith("requirements") and "pytest" in lower_text:
            has_pytest_marker = True

    uses_unittest = False
    uses_pytest_code = False
    for rel in py_tests[:50]:
        text = _safe_read_text(project_root / rel, MAX_TEST_INSPECT_BYTES)
        if not text:
            continue
        if "import unittest" in text or "from unittest" in text:
            uses_unittest = True
        if (
            "import pytest" in text
            or "from pytest" in text
            or re.search(r"^def\s+test_", text, re.MULTILINE)
        ):
            uses_pytest_code = True

    if has_pytest_marker or uses_pytest_code or not uses_unittest:
        return "pytest", limitations
    return "unittest", limitations


def _detect_node_framework(
    project_root: Path,
    js_tests: List[str],
    settings: Settings,
) -> Optional[_TestDetectionResult]:
    pkg_path = project_root / "package.json"
    pkg_text = _safe_read_text(pkg_path)
    if pkg_text is None:
        return None

    try:
        pkg = json.loads(pkg_text)
    except ValueError:
        return _TestDetectionResult(
            detected=False,
            ecosystem="Node.js",
            framework="unsupported",
            config_files_found=["package.json"],
            test_files_found=js_tests,
            reason="package.json is not valid JSON; cannot safely detect Node.js test runner.",
        )

    if not isinstance(pkg, dict):
        return None

    scripts = pkg.get("scripts")
    test_script = scripts.get("test") if isinstance(scripts, dict) else None
    if not isinstance(test_script, str) or not test_script.strip():
        if js_tests:
            return _TestDetectionResult(
                detected=False,
                ecosystem="Node.js",
                framework="unsupported",
                config_files_found=["package.json"],
                test_files_found=js_tests,
                reason="JavaScript/TypeScript test files exist, but package.json defines no scripts.test command.",
            )
        return None

    normalized_script = test_script.strip()
    if "no test specified" in normalized_script.lower():
        return _TestDetectionResult(
            detected=False,
            ecosystem="Node.js",
            framework="none",
            config_files_found=["package.json"],
            test_files_found=js_tests,
            reason="package.json uses the default placeholder test script ('no test specified').",
        )

    if _SHELL_META_CHARS.search(normalized_script):
        return _TestDetectionResult(
            detected=False,
            ecosystem="Node.js",
            framework="unsupported",
            config_files_found=["package.json"],
            test_files_found=js_tests,
            reason="package.json scripts.test contains shell chaining/metacharacters and was blocked from automated execution.",
        )

    lowered = normalized_script.lower()
    if "vitest" in lowered:
        return _TestDetectionResult(
            detected=True,
            ecosystem="Node.js",
            framework="vitest",
            command=["npx", "--no-install", "vitest", "run"],
            container_image=settings.validation_node_image,
            test_files_found=js_tests,
            config_files_found=["package.json"],
        )
    if "jest" in lowered:
        return _TestDetectionResult(
            detected=True,
            ecosystem="Node.js",
            framework="jest",
            command=["npx", "--no-install", "jest", "--runInBand"],
            container_image=settings.validation_node_image,
            test_files_found=js_tests,
            config_files_found=["package.json"],
        )
    if re.search(r"\bnode\s+--test\b", lowered):
        return _TestDetectionResult(
            detected=True,
            ecosystem="Node.js",
            framework="node_test",
            command=["node", "--test"],
            container_image=settings.validation_node_image,
            test_files_found=js_tests,
            config_files_found=["package.json"],
        )
    if "mocha" in lowered:
        return _TestDetectionResult(
            detected=True,
            ecosystem="Node.js",
            framework="npm",
            command=["npm", "test"],
            container_image=settings.validation_node_image,
            test_files_found=js_tests,
            config_files_found=["package.json"],
        )

    return _TestDetectionResult(
        detected=False,
        ecosystem="Node.js",
        framework="unsupported",
        config_files_found=["package.json"],
        test_files_found=js_tests,
        reason="package.json scripts.test uses an unrecognized or unsupported test runner.",
    )


def detect_test_configuration(
    project_root: Path,
    settings: Settings,
    *,
    target_file: Optional[str] = None,
    target_tests_only: bool = False,
) -> _TestDetectionResult:
    """Detect the project's test framework and construct a safe container test command."""
    inv = _collect_project_test_inventory(project_root)
    py_tests = inv["py_tests"]
    py_conftests = inv["py_conftests"]
    js_tests = inv["js_tests"]
    other_tests = inv["other_tests"]
    configs = inv["configs"]
    manifests = inv["manifests"]

    if py_tests:
        framework, limitations = _detect_python_framework(
            project_root, py_tests, py_conftests, manifests
        )
        selected = _select_target_python_tests(target_file, py_tests) if target_tests_only else []

        if framework == "pytest":
            cmd = [
                "python",
                "-m",
                "pytest",
                "-v",
                "--tb=short",
                "-o",
                "cache_dir=/tmp/.pytest_cache",
                *selected,
            ]
        else:
            if selected:
                cmd = ["python", "-m", "unittest", "-v", *selected]
            else:
                cmd = ["python", "-m", "unittest", "discover", "-v"]

        if target_tests_only and not selected:
            limitations.append(
                "No targeted test file matched the patched module name; running the full detected test suite."
            )

        return _TestDetectionResult(
            detected=True,
            ecosystem="Python",
            framework=framework,
            command=cmd,
            container_image=settings.validation_python_image,
            test_files_found=py_tests,
            config_files_found=configs,
            limitations=limitations,
        )

    node_result = _detect_node_framework(project_root, js_tests, settings)
    if node_result is not None:
        return node_result

    if js_tests or other_tests or any(
        Path(m).name.lower() in ("go.mod", "cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts")
        for m in manifests
    ):
        return _TestDetectionResult(
            detected=False,
            ecosystem=None,
            framework="unsupported",
            test_files_found=js_tests + other_tests,
            config_files_found=configs,
            reason="Project language or test setup is not currently supported for isolated test execution.",
        )

    return _TestDetectionResult(
        detected=False,
        ecosystem=None,
        framework="none",
        test_files_found=[],
        config_files_found=configs,
        reason="No runnable test suite or test files were detected in the project.",
    )
