"""Safe, bounded source-code context collection for Step 4 root cause analysis.

All files are read strictly within the assigned project workspace, sensitive
values are redacted, and uploaded code is never executed.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple

from app.core.config import Settings
from app.schemas.scan import FindingRecord
from app.utils.file_utils import is_within_directory

_SENSITIVE_FILENAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials",
        "credentials.json",
    }
)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SAFE_ENV_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})

# Matches secret variable assignments like: password = "abc", api_key: str = 'xyz'
_ASSIGN_SECRET_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|secret|secret_key|api_key|apikey|token|"
    r"auth_token|access_token|refresh_token|private_key|client_secret)\b"
    r"(?:\s*:\s*[^=\n]+)?\s*=\s*)(['\"])(?:\\.|(?!\2).)*\2"
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{16,}|ghp_[0-9A-Za-z]{20,}|AKIA[0-9A-Z]{16})\b"
)
_URL_CRED_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/@\s]+:)([^@\s]+)(@)")
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class FindingSourceContext:
    finding_id: str
    file_path: str
    line_number: int
    enclosing_symbol: Optional[str] = None
    related_imports: List[str] = field(default_factory=list)
    snippet: str = ""
    start_line: int = 1
    end_line: int = 1
    context_available: bool = True
    truncated: bool = False
    notes: List[str] = field(default_factory=list)


def is_sensitive_path(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    if name in _SAFE_ENV_NAMES:
        return False
    if name in _SENSITIVE_FILENAMES or name.startswith(".env."):
        return True
    return name.endswith(_SENSITIVE_SUFFIXES)


def redact_sensitive_text(text: str) -> str:
    """Redact credentials, tokens, private keys, and URL passwords from text."""
    if not text:
        return text
    cleaned = _PEM_BLOCK_RE.sub("[REDACTED_PRIVATE_KEY]", text)
    cleaned = _ASSIGN_SECRET_RE.sub(r"\1'***REDACTED***'", cleaned)
    cleaned = _BEARER_RE.sub(r"\1 ***REDACTED***", cleaned)
    cleaned = _KNOWN_TOKEN_RE.sub("***REDACTED_TOKEN***", cleaned)
    cleaned = _URL_CRED_RE.sub(r"\1***REDACTED***\3", cleaned)
    return cleaned


def sanitize_untrusted_text(text: str) -> str:
    """Remove control chars, neutralize XML boundary tags, and redact secrets."""
    if not text:
        return ""
    cleaned = _CONTROL_CHARS_RE.sub("", text)
    cleaned = redact_sensitive_text(cleaned)
    # Prevent untrusted source comments/strings from closing prompt data tags.
    cleaned = cleaned.replace("</untrusted_source>", "&lt;/untrusted_source&gt;")
    cleaned = cleaned.replace("<untrusted_source>", "&lt;untrusted_source&gt;")
    cleaned = cleaned.replace("</untrusted_finding>", "&lt;/untrusted_finding&gt;")
    return cleaned


def _find_enclosing_symbol_and_imports(
    source: str, target_line: int
) -> Tuple[Optional[str], List[str]]:
    """Inspect AST safely in memory to locate enclosing class/function and imports."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, []

    imports: List[str] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                imports.append(f"import {alias.name}")
        elif isinstance(stmt, ast.ImportFrom):
            mod = stmt.module or ""
            names = ", ".join(a.name for a in stmt.names[:5])
            imports.append(f"from {mod} import {names}")

    enclosing_parts: List[str] = []

    def _walk(body: Sequence[ast.stmt]) -> None:
        for stmt in body:
            start = getattr(stmt, "lineno", 0)
            end = getattr(stmt, "end_lineno", start) or start
            if start <= target_line <= end:
                if isinstance(stmt, ast.ClassDef):
                    enclosing_parts.append(f"class {stmt.name} (lines {start}-{end})")
                    _walk(stmt.body)
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async def" if isinstance(stmt, ast.AsyncFunctionDef) else "def"
                    enclosing_parts.append(f"{prefix} {stmt.name} (lines {start}-{end})")
                    _walk(stmt.body)
                break

    _walk(tree.body)
    return (" -> ".join(enclosing_parts) if enclosing_parts else None), imports[:10]


def collect_finding_contexts(
    project_root: Path,
    findings: Sequence[FindingRecord],
    settings: Settings,
) -> Tuple[List[FindingSourceContext], List[str]]:
    """Collect bounded, sanitized source-code context for each finding."""
    resolved_root = project_root.resolve()
    remaining_budget = settings.max_total_context_chars
    contexts: List[FindingSourceContext] = []
    warnings: List[str] = []
    file_cache: dict[str, Optional[str]] = {}
    file_errors: dict[str, str] = {}

    for finding in findings:
        rel_path = finding.file_path.replace("\\", "/").lstrip("/")
        if not rel_path or ".." in Path(rel_path).parts or Path(rel_path).is_absolute():
            contexts.append(
                FindingSourceContext(
                    finding_id=finding.id,
                    file_path=finding.file_path,
                    line_number=finding.line_number,
                    context_available=False,
                    notes=["Skipped context extraction due to unsafe relative path."],
                )
            )
            continue

        if is_sensitive_path(rel_path):
            contexts.append(
                FindingSourceContext(
                    finding_id=finding.id,
                    file_path=rel_path,
                    line_number=finding.line_number,
                    context_available=False,
                    notes=["Sensitive file excluded from LLM context."],
                )
            )
            continue

        if remaining_budget <= 0:
            contexts.append(
                FindingSourceContext(
                    finding_id=finding.id,
                    file_path=rel_path,
                    line_number=finding.line_number,
                    context_available=False,
                    truncated=True,
                    notes=["Total context budget exhausted; only finding metadata supplied."],
                )
            )
            continue

        if rel_path not in file_cache:
            candidate = (resolved_root / rel_path).resolve()
            if not is_within_directory(resolved_root, candidate) or (resolved_root / rel_path).is_symlink():
                file_cache[rel_path] = None
                file_errors[rel_path] = "Path escapes workspace or is a symbolic link."
            elif not candidate.is_file():
                file_cache[rel_path] = None
                file_errors[rel_path] = "Target source file not found in workspace."
            else:
                try:
                    st = candidate.stat()
                    if st.st_size > settings.max_context_file_bytes:
                        file_cache[rel_path] = None
                        file_errors[rel_path] = (
                            f"File exceeds context size limit ({settings.max_context_file_bytes} bytes)."
                        )
                    else:
                        file_cache[rel_path] = candidate.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    file_cache[rel_path] = None
                    file_errors[rel_path] = "File is not valid UTF-8 text."
                except OSError:
                    file_cache[rel_path] = None
                    file_errors[rel_path] = "File could not be read."

        source = file_cache[rel_path]
        if source is None:
            contexts.append(
                FindingSourceContext(
                    finding_id=finding.id,
                    file_path=rel_path,
                    line_number=finding.line_number,
                    context_available=False,
                    notes=[file_errors.get(rel_path, "Source context unavailable.")],
                )
            )
            continue

        lines = source.splitlines()
        total_lines = len(lines)
        start_line = max(1, finding.line_number - settings.max_context_lines_before)
        end_line = min(total_lines, finding.line_number + settings.max_context_lines_after)

        numbered_lines: List[str] = []
        for idx in range(start_line, end_line + 1):
            marker = ">>" if idx == finding.line_number else "  "
            safe_line = sanitize_untrusted_text(lines[idx - 1])
            numbered_lines.append(f"{marker} L{idx}: {safe_line}")

        snippet = "\n".join(numbered_lines)
        per_cap = min(settings.max_context_chars_per_finding, remaining_budget)
        truncated = False
        notes: List[str] = []
        if len(snippet) > per_cap:
            snippet = snippet[:per_cap] + "\n... [context truncated due to size limit]"
            truncated = True
            notes.append("Source snippet truncated to respect context size limits.")

        remaining_budget = max(0, remaining_budget - len(snippet))
        enclosing_symbol, imports = _find_enclosing_symbol_and_imports(source, finding.line_number)

        contexts.append(
            FindingSourceContext(
                finding_id=finding.id,
                file_path=rel_path,
                line_number=finding.line_number,
                enclosing_symbol=enclosing_symbol,
                related_imports=[sanitize_untrusted_text(imp) for imp in imports],
                snippet=snippet,
                start_line=start_line,
                end_line=end_line,
                context_available=True,
                truncated=truncated,
                notes=notes,
            )
        )

    truncated_count = sum(1 for c in contexts if c.truncated)
    if truncated_count:
        warnings.append(
            f"Source context was truncated for {truncated_count} finding(s) due to context limits."
        )

    # Also detect files referenced via shared imports across findings if useful
    seen_files: Set[str] = {c.file_path for c in contexts if c.context_available}
    if len(seen_files) > 1:
        warnings.append(
            f"Context collected across {len(seen_files)} workspace file(s) without executing uploaded code."
        )

    return contexts, warnings
