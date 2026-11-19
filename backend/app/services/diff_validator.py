"""Strict, in-memory unified diff validator for Step 5 automated patch generation.

Security invariants:
- Never executes uploaded project code or external diff/patch binaries.
- Never modifies files on disk; validates and previews patches strictly in memory.
- Rejects absolute paths, directory traversal, Windows drive paths, symlinks,
  file creations/deletions/renames, binary diffs, multi-file diffs, and target mismatches.
"""

import difflib
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from app.core.config import Settings
from app.core.errors import PatchValidationError
from app.services.context_service import is_sensitive_path, redact_sensitive_text
from app.utils.file_utils import is_within_directory

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_DIFF_GIT_RE = re.compile(r"^diff --git\s+(\S+)\s+(\S+)$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")

_FORBIDDEN_HEADER_PREFIXES = (
    "new file mode",
    "deleted file mode",
    "rename from",
    "rename to",
    "copy from",
    "copy to",
    "old mode",
    "new mode",
    "similarity index",
    "dissimilarity index",
    "GIT binary patch",
    "Binary files ",
)


@dataclass(frozen=True)
class ValidatedDiffResult:
    canonical_diff: str
    target_rel_path: str
    hunks_count: int
    lines_added: int
    lines_removed: int
    original_file_sha256: str
    original_snippet: str
    proposed_snippet: str
    checks_passed: List[str]


def normalize_expected_rel_path(raw_path: str) -> str:
    """Validate and normalize a finding's relative path inside the workspace."""
    if not raw_path or _CONTROL_CHARS_RE.search(raw_path):
        raise PatchValidationError("Target file path is empty or contains invalid characters.")
    if "\\" in raw_path or _WINDOWS_DRIVE_RE.match(raw_path) or ":" in raw_path:
        raise PatchValidationError("Target file path must be a relative POSIX path inside the workspace.")
    if raw_path.startswith("/"):
        raise PatchValidationError("Target file path must not be an absolute path.")

    parts = [p for p in raw_path.split("/") if p != "."]
    if not parts or any(p in ("", "..") for p in parts):
        raise PatchValidationError("Target file path contains invalid segments or directory traversal.")

    normalized = "/".join(parts)
    if is_sensitive_path(normalized):
        raise PatchValidationError("Patch generation is not permitted for sensitive or credential files.")
    return normalized


def _validate_diff_header_path(raw_header_value: str, expected_prefix: Optional[str]) -> str:
    """Validate a path extracted from `diff --git`, `---`, or `+++` headers."""
    # Strip optional unified diff timestamp suffix after tab.
    path_part = raw_header_value.split("\t", 1)[0].rstrip("\r")
    if not path_part or path_part != path_part.strip():
        raise PatchValidationError("Diff header contains an empty or malformed file path.")
    if _CONTROL_CHARS_RE.search(path_part):
        raise PatchValidationError("Diff header path contains invalid control characters.")
    if path_part == "/dev/null":
        raise PatchValidationError("File additions or deletions (/dev/null) are not permitted.")
    if path_part.startswith('"') or path_part.endswith('"'):
        raise PatchValidationError("Quoted or escaped diff paths are not permitted.")
    if "\\" in path_part or _WINDOWS_DRIVE_RE.match(path_part) or ":" in path_part:
        raise PatchValidationError("Windows paths and backslashes are not permitted in diff paths.")
    if path_part.startswith("/") or path_part.startswith("~"):
        raise PatchValidationError("Absolute or home-relative paths are not permitted in unified diffs.")

    # Reject traversal before any prefix stripping as well.
    raw_segments = path_part.split("/")
    if any(seg == ".." for seg in raw_segments):
        raise PatchValidationError("Directory traversal ('..') is not permitted in diff paths.")

    # Strip at most one standard diff prefix (`a/` or `b/`).
    cleaned = path_part
    if expected_prefix and cleaned.startswith(f"{expected_prefix}/"):
        cleaned = cleaned[len(expected_prefix) + 1 :]

    if cleaned.startswith("./"):
        cleaned = cleaned[2:]

    if not cleaned or cleaned.startswith("/"):
        raise PatchValidationError("Absolute or empty path detected after diff prefix normalization.")

    segments = cleaned.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise PatchValidationError("Diff path contains empty segments or directory traversal.")

    return PurePosixPath(*segments).as_posix()


def resolve_workspace_target_file(project_root: Path, expected_rel_path: str) -> Path:
    """Safely resolve `expected_rel_path` strictly inside `project_root` with no symlinks."""
    normalized = normalize_expected_rel_path(expected_rel_path)
    resolved_root = project_root.resolve()

    cursor = resolved_root
    for part in normalized.split("/"):
        cursor = cursor / part
        if cursor.is_symlink():
            raise PatchValidationError("Target path traverses or references a symbolic link.")

    resolved_target = cursor.resolve()
    if not is_within_directory(resolved_root, resolved_target):
        raise PatchValidationError("Target file escapes the approved project workspace.")
    if not resolved_target.is_file():
        raise PatchValidationError("Target source file does not exist in the project workspace.")
    return resolved_target


def _build_change_snippets(
    orig_lines: List[str],
    patched_lines: List[str],
    changed_orig_indices: List[int],
    context_radius: int = 3,
) -> Tuple[str, str]:
    """Produce bounded, secret-redacted before/after snippets around the modified lines."""
    if not changed_orig_indices:
        return "", ""

    first_idx = max(0, min(changed_orig_indices) - context_radius)
    last_orig_idx = min(len(orig_lines), max(changed_orig_indices) + context_radius + 1)
    delta = len(patched_lines) - len(orig_lines)
    last_patched_idx = min(
        len(patched_lines),
        max(first_idx + 1, max(changed_orig_indices) + delta + context_radius + 1),
    )

    orig_slice = "\n".join(
        f"L{idx + 1}: {orig_lines[idx]}" for idx in range(first_idx, last_orig_idx)
    )
    patched_slice = "\n".join(
        f"L{idx + 1}: {patched_lines[idx]}" for idx in range(first_idx, last_patched_idx)
    )
    return redact_sensitive_text(orig_slice), redact_sensitive_text(patched_slice)


def _validate_and_apply_in_memory(
    diff_text: str,
    project_root: Path,
    expected_rel_path: str,
    settings: Settings,
    llm_declared_target: Optional[str] = None,
) -> Tuple[ValidatedDiffResult, str]:
    """Strictly validate a unified diff against an existing workspace file without modifying disk."""
    normalized_expected = normalize_expected_rel_path(expected_rel_path)

    if llm_declared_target is not None:
        declared_norm = _validate_diff_header_path(llm_declared_target.strip(), None)
        if declared_norm != normalized_expected:
            raise PatchValidationError(
                "Patch target_file does not match the finding's source file."
            )

    if not diff_text or not diff_text.strip():
        raise PatchValidationError("Generated unified diff is empty.")

    diff_bytes = diff_text.encode("utf-8", errors="strict")
    if len(diff_bytes) > settings.max_patch_diff_bytes:
        raise PatchValidationError(
            f"Generated unified diff exceeds maximum allowed size ({settings.max_patch_diff_bytes} bytes)."
        )

    target_file = resolve_workspace_target_file(project_root, normalized_expected)
    try:
        raw_file_bytes = target_file.read_bytes()
    except OSError as exc:
        raise PatchValidationError("Target source file could not be read for diff validation.") from exc

    if len(raw_file_bytes) > settings.max_context_file_bytes:
        raise PatchValidationError(
            f"Target file exceeds maximum editable context size ({settings.max_context_file_bytes} bytes)."
        )

    try:
        original_source = raw_file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchValidationError("Target file is not valid UTF-8 text.") from exc

    original_sha256 = hashlib.sha256(raw_file_bytes).hexdigest()
    orig_lines = original_source.splitlines()

    raw_lines = [line.rstrip("\r") for line in diff_text.splitlines()]
    # Ignore leading/trailing blank lines outside the diff body.
    while raw_lines and not raw_lines[0].strip():
        raw_lines.pop(0)
    while raw_lines and not raw_lines[-1].strip():
        raw_lines.pop()

    if not raw_lines:
        raise PatchValidationError("Generated unified diff contains no content.")

    idx = 0
    seen_diff_git = False
    seen_index = False
    old_header_path: Optional[str] = None
    new_header_path: Optional[str] = None

    # 1. Parse single-file header section.
    while idx < len(raw_lines):
        line = raw_lines[idx]
        for forbidden in _FORBIDDEN_HEADER_PREFIXES:
            if line.startswith(forbidden):
                raise PatchValidationError(
                    f"Unsupported or unsafe diff operation detected ({forbidden.strip()})."
                )

        if line.startswith("diff --git "):
            if seen_diff_git or old_header_path is not None:
                raise PatchValidationError("Multi-file patches are not permitted.")
            match = _DIFF_GIT_RE.fullmatch(line)
            if not match:
                raise PatchValidationError("Malformed 'diff --git' header.")
            left_path = _validate_diff_header_path(match.group(1), "a")
            right_path = _validate_diff_header_path(match.group(2), "b")
            if left_path != right_path or left_path != normalized_expected:
                raise PatchValidationError(
                    "Diff header target does not match the expected workspace source file."
                )
            seen_diff_git = True
            idx += 1
            continue

        if line.startswith("index "):
            if seen_index or old_header_path is not None:
                raise PatchValidationError("Unexpected or duplicate git index header in diff.")
            if "0000000" in line:
                raise PatchValidationError("File additions or deletions are not permitted.")
            seen_index = True
            idx += 1
            continue

        if line.startswith("--- "):
            if old_header_path is not None:
                raise PatchValidationError("Multi-file patches are not permitted.")
            old_header_path = _validate_diff_header_path(line[4:], "a")
            idx += 1
            if idx >= len(raw_lines) or not raw_lines[idx].startswith("+++ "):
                raise PatchValidationError("Missing '+++ ' target header immediately after '--- ' header.")
            new_header_path = _validate_diff_header_path(raw_lines[idx][4:], "b")
            idx += 1
            break

        if line.startswith("+++ ") or line.startswith("@@"):
            raise PatchValidationError("Unified diff must begin with valid '--- ' and '+++ ' file headers.")

        raise PatchValidationError("Malformed header line in generated unified diff.")

    if old_header_path is None or new_header_path is None:
        raise PatchValidationError("Unified diff is missing required '--- ' and '+++ ' file headers.")

    if old_header_path != new_header_path:
        raise PatchValidationError("File renames or mismatched source/target headers are not permitted.")

    if old_header_path != normalized_expected:
        raise PatchValidationError(
            "Generated diff targets an unexpected file instead of the finding's source file."
        )

    # 2. Parse and strictly validate all hunks against `orig_lines`.
    hunks: List[Tuple[int, int, int, int, List[Tuple[str, str]]]] = []
    while idx < len(raw_lines):
        line = raw_lines[idx]
        if not line:
            idx += 1
            continue

        for forbidden in _FORBIDDEN_HEADER_PREFIXES:
            if line.startswith(forbidden):
                raise PatchValidationError(
                    f"Unsupported or unsafe diff operation detected ({forbidden.strip()})."
                )
        if line.startswith(("diff --git ", "--- ", "+++ ")):
            raise PatchValidationError("Multi-file patches are not permitted; only one file may be modified.")

        hunk_match = _HUNK_HEADER_RE.fullmatch(line)
        if not hunk_match:
            raise PatchValidationError("Malformed content or unexpected text outside diff hunks.")

        old_start = int(hunk_match.group(1))
        old_count = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
        new_start = int(hunk_match.group(3))
        new_count = int(hunk_match.group(4)) if hunk_match.group(4) is not None else 1
        idx += 1

        if len(hunks) >= settings.max_patch_hunks:
            raise PatchValidationError(
                f"Unified diff exceeds maximum allowed hunks ({settings.max_patch_hunks})."
            )

        ops: List[Tuple[str, str]] = []
        old_seen = 0
        new_seen = 0
        while old_seen < old_count or new_seen < new_count:
            if idx >= len(raw_lines):
                raise PatchValidationError("Truncated hunk: fewer lines than declared in hunk header.")
            hline = raw_lines[idx]
            idx += 1
            if hline.startswith(" "):
                ops.append((" ", hline[1:]))
                old_seen += 1
                new_seen += 1
            elif hline.startswith("-"):
                ops.append(("-", hline[1:]))
                old_seen += 1
            elif hline.startswith("+"):
                ops.append(("+", hline[1:]))
                new_seen += 1
            elif hline == "\\ No newline at end of file":
                continue
            else:
                raise PatchValidationError("Malformed line prefix inside unified diff hunk.")

        if old_seen != old_count or new_seen != new_count:
            raise PatchValidationError("Hunk line counts do not match hunk header.")

        # Allow trailing `\ No newline at end of file` right after hunk body.
        if idx < len(raw_lines) and raw_lines[idx] == "\\ No newline at end of file":
            idx += 1

        hunks.append((old_start, old_count, new_start, new_count, ops))

    if not hunks:
        raise PatchValidationError("Unified diff contains no change hunks.")

    # 3. Apply hunks strictly in memory to verify context & line correspondence.
    patched_lines: List[str] = []
    orig_cursor = 0
    lines_added = 0
    lines_removed = 0
    changed_orig_indices: List[int] = []

    for old_start, old_count, _new_start, _new_count, ops in hunks:
        if len(orig_lines) == 0:
            if old_start != 0 or old_count != 0:
                raise PatchValidationError("Hunk line range exceeds empty target file.")
            hunk_start_idx = 0
        elif old_count == 0:
            if old_start < 0 or old_start > len(orig_lines):
                raise PatchValidationError("Pure-insertion hunk line range is outside the target file.")
            hunk_start_idx = old_start
        else:
            if old_start < 1:
                raise PatchValidationError("Hunk start line must be >= 1 for existing non-empty files.")
            hunk_start_idx = old_start - 1

        if hunk_start_idx < orig_cursor:
            raise PatchValidationError("Unified diff contains overlapping or out-of-order hunks.")
        if hunk_start_idx + old_count > len(orig_lines):
            raise PatchValidationError("Unified diff hunk extends beyond the end of the target file.")

        patched_lines.extend(orig_lines[orig_cursor:hunk_start_idx])
        local_cursor = hunk_start_idx

        for tag, text in ops:
            if tag == " ":
                if local_cursor >= len(orig_lines) or orig_lines[local_cursor] != text:
                    raise PatchValidationError(
                        "Unified diff context lines do not match the current workspace file."
                    )
                patched_lines.append(text)
                local_cursor += 1
            elif tag == "-":
                if local_cursor >= len(orig_lines) or orig_lines[local_cursor] != text:
                    raise PatchValidationError(
                        "Unified diff removed lines do not match the current workspace file."
                    )
                changed_orig_indices.append(local_cursor)
                lines_removed += 1
                local_cursor += 1
            elif tag == "+":
                changed_orig_indices.append(max(0, local_cursor - 1))
                patched_lines.append(text)
                lines_added += 1

        orig_cursor = local_cursor

    patched_lines.extend(orig_lines[orig_cursor:])

    if lines_added == 0 and lines_removed == 0:
        raise PatchValidationError("Unified diff contains no actual line additions or removals.")
    if patched_lines == orig_lines:
        raise PatchValidationError("Unified diff produces no effective change to the target file.")

    canonical_lines = list(
        difflib.unified_diff(
            orig_lines,
            patched_lines,
            fromfile=f"a/{normalized_expected}",
            tofile=f"b/{normalized_expected}",
            n=3,
            lineterm="",
        )
    )
    if not canonical_lines:
        raise PatchValidationError("Unified diff produces no effective change to the target file.")

    canonical_diff = "\n".join(canonical_lines) + "\n"
    original_snippet, proposed_snippet = _build_change_snippets(
        orig_lines, patched_lines, changed_orig_indices
    )

    checks_passed = [
        "non_empty_diff",
        "diff_size_within_limit",
        "single_existing_file_only",
        "workspace_confined_no_symlinks",
        "no_traversal_or_absolute_paths",
        "no_file_add_delete_rename_or_binary",
        "hunk_counts_and_context_verified_in_memory",
        "effective_non_noop_change",
    ]

    result = ValidatedDiffResult(
        canonical_diff=canonical_diff,
        target_rel_path=normalized_expected,
        hunks_count=len(hunks),
        lines_added=lines_added,
        lines_removed=lines_removed,
        original_file_sha256=original_sha256,
        original_snippet=original_snippet,
        proposed_snippet=proposed_snippet,
        checks_passed=checks_passed,
    )

    line_sep = "\r\n" if "\r\n" in original_source else "\n"
    had_trailing_nl = original_source.endswith(("\n", "\r"))
    if patched_lines:
        patched_text = line_sep.join(patched_lines) + (line_sep if had_trailing_nl else "")
    else:
        patched_text = ""

    return result, patched_text


def validate_and_preview_unified_diff(
    diff_text: str,
    project_root: Path,
    expected_rel_path: str,
    settings: Settings,
    llm_declared_target: Optional[str] = None,
) -> ValidatedDiffResult:
    """Strictly validate a unified diff against an existing workspace file without modifying disk."""
    result, _patched_text = _validate_and_apply_in_memory(
        diff_text=diff_text,
        project_root=project_root,
        expected_rel_path=expected_rel_path,
        settings=settings,
        llm_declared_target=llm_declared_target,
    )
    return result


def apply_unified_diff_in_memory(
    diff_text: str,
    project_root: Path,
    expected_rel_path: str,
    settings: Settings,
) -> Tuple[ValidatedDiffResult, str]:
    """Revalidate `diff_text` against the current workspace file and return (result, patched_text)."""
    return _validate_and_apply_in_memory(
        diff_text=diff_text,
        project_root=project_root,
        expected_rel_path=expected_rel_path,
        settings=settings,
        llm_declared_target=expected_rel_path,
    )
