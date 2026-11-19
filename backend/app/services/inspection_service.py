"""Static inspection of an extracted project.

Only file names, locations and sizes are examined. File CONTENTS are never
read or executed, so inspection cannot be influenced by uploaded code, and
potentially sensitive files are reported by name only.
"""

import os
import re
import stat
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app.schemas.project import (
    InspectionReport,
    LanguageInfo,
    ProjectFile,
    SourceDirectory,
    StructureNode,
    TopLevelEntry,
)

MAX_LISTED_ITEMS = 200
MAX_EXAMPLES = 3

LANGUAGE_BY_EXTENSION: Dict[str, str] = {
    ".py": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rs": "Rust",
    ".c": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".sh": "Shell",
}

IGNORED_DIRECTORIES = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", "site-packages",
})

TEST_DIRECTORY_NAMES = frozenset({"tests", "test", "__tests__", "spec", "specs"})

MANIFEST_ECOSYSTEMS: Dict[str, str] = {
    "requirements.txt": "Python", "pyproject.toml": "Python", "setup.py": "Python",
    "setup.cfg": "Python", "pipfile": "Python", "pipfile.lock": "Python",
    "poetry.lock": "Python",
    "package.json": "Node.js", "package-lock.json": "Node.js",
    "yarn.lock": "Node.js", "pnpm-lock.yaml": "Node.js",
    "pom.xml": "Java (Maven)", "build.gradle": "JVM (Gradle)",
    "build.gradle.kts": "JVM (Gradle)",
    "cargo.toml": "Rust", "cargo.lock": "Rust",
    "go.mod": "Go", "go.sum": "Go",
    "gemfile": "Ruby", "composer.json": "PHP",
}
_REQUIREMENTS_PATTERN = re.compile(r"^requirements[-_.\w]*\.txt$")

CONFIG_NAMES = frozenset({
    "tsconfig.json", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".dockerignore", ".gitignore", "makefile", "pytest.ini", "tox.ini", ".flake8",
    "ruff.toml", ".ruff.toml", "mypy.ini", ".editorconfig", ".pre-commit-config.yaml",
    ".env.example",
})
_CONFIG_PATTERNS = (
    re.compile(r"^tsconfig\.[\w-]+\.json$"),
    re.compile(r"^dockerfile\.[\w.-]+$"),
    re.compile(r"^(jest|vite|webpack|rollup|babel)\.config\.[cm]?[jt]s$"),
    re.compile(r"^\.eslintrc(\.\w+)?$"),
    re.compile(r"^\.prettierrc(\.\w+)?$"),
)

_DOC_PREFIXES = ("readme", "changelog", "contributing", "license", "authors")
_DOC_EXTENSIONS = frozenset({".md", ".rst", ".adoc"})

_SENSITIVE_NAMES = frozenset({
    ".env", ".npmrc", ".pypirc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json",
})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SAFE_ENV_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})

_JS_TEST_PATTERN = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")
_JAVA_TEST_PATTERN = re.compile(r"(Test|Tests|IT)\.java$")


def find_project_root(source_dir: Path) -> Path:
    """If the archive has a single top-level directory, that is the project root."""
    try:
        entries = [e for e in source_dir.iterdir() if not e.is_symlink()]
    except OSError:
        return source_dir
    clean_entries = [e for e in entries if e.name.lower() not in {"__macosx", ".ds_store"}]
    if len(clean_entries) == 1 and clean_entries[0].is_dir():
        return clean_entries[0]
    return source_dir


def _manifest_ecosystem(lower_name: str) -> Optional[str]:
    if lower_name in MANIFEST_ECOSYSTEMS:
        return MANIFEST_ECOSYSTEMS[lower_name]
    if _REQUIREMENTS_PATTERN.match(lower_name):
        return "Python"
    return None


def _is_config(lower_name: str) -> bool:
    return lower_name in CONFIG_NAMES or any(p.match(lower_name) for p in _CONFIG_PATTERNS)


def _is_documentation(lower_name: str, extension: str) -> bool:
    return lower_name.startswith(_DOC_PREFIXES) or extension in _DOC_EXTENSIONS


def _is_sensitive(lower_name: str) -> bool:
    if lower_name in _SAFE_ENV_NAMES:
        return False
    if lower_name in _SENSITIVE_NAMES or lower_name.startswith(".env."):
        return True
    return lower_name.endswith(_SENSITIVE_SUFFIXES)


def _is_test_file(name: str, extension: str, in_test_dir: bool, language: Optional[str]) -> bool:
    lower = name.lower()
    by_name = False
    if extension == ".py":
        by_name = lower.startswith("test_") or lower.endswith("_test.py") or lower == "conftest.py"
    elif extension in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        by_name = bool(_JS_TEST_PATTERN.search(lower))
    elif extension == ".go":
        by_name = lower.endswith("_test.go")
    elif extension == ".java":
        by_name = bool(_JAVA_TEST_PATTERN.search(name))
    return by_name or (in_test_dir and language is not None)


def inspect_project(
    project_id: str,
    project_name: str,
    project_root: Path,
    source_root: Path,
    skipped_archive_entries: int = 0,
) -> InspectionReport:
    total_files = 0
    total_dirs = 0
    total_size = 0
    extension_counts: Counter = Counter()
    language_files: Dict[str, List[str]] = {}
    language_exts: Dict[str, Set[str]] = {}
    source_dir_counts: Counter = Counter()
    manifests: List[ProjectFile] = []
    configs: List[ProjectFile] = []
    docs: List[str] = []
    test_dirs: List[str] = []
    test_files: List[str] = []
    sensitive: List[str] = []
    ignored_dirs_found: Set[str] = set()
    symlinks_skipped = 0

    for dirpath, dirnames, filenames in os.walk(project_root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        rel_dir = current.relative_to(project_root).as_posix()
        rel_dir_parts: Tuple[str, ...] = () if rel_dir == "." else tuple(rel_dir.split("/"))
        in_ignored = any(p in IGNORED_DIRECTORIES for p in rel_dir_parts)

        real_dirs = []
        for d in dirnames:
            if (current / d).is_symlink():
                symlinks_skipped += 1
                continue
            real_dirs.append(d)
            total_dirs += 1
            if d in IGNORED_DIRECTORIES:
                ignored_dirs_found.add(d)
            elif (not in_ignored) and d.lower() in TEST_DIRECTORY_NAMES:
                test_dirs.append(d if rel_dir == "." else f"{rel_dir}/{d}")
        dirnames[:] = real_dirs

        in_test_dir = any(p.lower() in TEST_DIRECTORY_NAMES for p in rel_dir_parts)

        for name in filenames:
            full = current / name
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                symlinks_skipped += 1
                continue

            total_files += 1
            total_size += st.st_size
            extension = Path(name).suffix.lower()
            extension_counts[extension or "(none)"] += 1
            if in_ignored:
                continue

            rel_path = name if rel_dir == "." else f"{rel_dir}/{name}"
            lower = name.lower()

            if _is_sensitive(lower):
                sensitive.append(rel_path)

            ecosystem = _manifest_ecosystem(lower)
            if ecosystem is not None:
                manifests.append(ProjectFile(path=rel_path, name=name, ecosystem=ecosystem))
            elif _is_config(lower):
                configs.append(ProjectFile(path=rel_path, name=name))

            if _is_documentation(lower, extension):
                docs.append(rel_path)

            language = LANGUAGE_BY_EXTENSION.get(extension)
            if language:
                language_files.setdefault(language, []).append(rel_path)
                language_exts.setdefault(language, set()).add(extension)

            if _is_test_file(name, extension, in_test_dir, language):
                test_files.append(rel_path)
            elif language:
                source_dir_counts[rel_dir] += 1

    languages = [
        LanguageInfo(
            name=lang,
            file_count=len(paths),
            extensions=sorted(language_exts[lang]),
            example_files=paths[:MAX_EXAMPLES],
        )
        for lang, paths in sorted(language_files.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    source_directories = [
        SourceDirectory(path=path, source_file_count=count)
        for path, count in sorted(source_dir_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:MAX_LISTED_ITEMS]

    try:
        top_level = [
            TopLevelEntry(name=e.name, type="directory" if e.is_dir() else "file")
            for e in sorted(project_root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            if not e.is_symlink()
        ]
    except OSError:
        top_level = []

    root_rel = project_root.relative_to(source_root).as_posix()

    warnings = _build_warnings(
        languages=languages,
        has_tests=bool(test_files),
        has_manifests=bool(manifests),
        sensitive=sensitive,
        ignored_dirs=sorted(ignored_dirs_found),
        skipped_archive_entries=skipped_archive_entries,
        single_root=project_root != source_root,
        symlinks_skipped=symlinks_skipped,
        total_files=total_files,
        truncated=any(len(x) > MAX_LISTED_ITEMS for x in (manifests, configs, docs, test_files)),
    )

    return InspectionReport(
        project_id=project_id,
        project_name=project_name,
        root_directory=root_rel,
        total_files=total_files,
        total_directories=total_dirs,
        total_size_bytes=total_size,
        file_extensions=dict(extension_counts.most_common()),
        languages=languages,
        python_detected="Python" in language_files,
        source_directories=source_directories,
        configuration_files=configs[:MAX_LISTED_ITEMS],
        dependency_manifests=manifests[:MAX_LISTED_ITEMS],
        documentation_files=docs[:MAX_LISTED_ITEMS],
        test_directories=sorted(test_dirs)[:MAX_LISTED_ITEMS],
        test_files=test_files[:MAX_LISTED_ITEMS],
        test_file_count=len(test_files),
        top_level_entries=top_level,
        warnings=warnings,
    )


def _build_warnings(
    *,
    languages: List[LanguageInfo],
    has_tests: bool,
    has_manifests: bool,
    sensitive: List[str],
    ignored_dirs: List[str],
    skipped_archive_entries: int,
    single_root: bool,
    symlinks_skipped: int,
    total_files: int,
    truncated: bool,
) -> List[str]:
    warnings: List[str] = []
    names = {lang.name for lang in languages}

    if total_files == 0:
        warnings.append("The project contains no files.")
    if not languages:
        warnings.append("No recognised source files were found; no language could be detected.")
    elif "Python" not in names:
        warnings.append(
            "No Python source files were found. RootPatch currently analyses Python projects only."
        )
    else:
        others = sorted(n for n in names if n != "Python")
        if others:
            count = sum(lang.file_count for lang in languages if lang.name != "Python")
            warnings.append(
                f"{count} non-Python source file(s) detected ({', '.join(others)}). "
                "RootPatch currently analyses Python only; these files will not be analysed."
            )
    if languages and not has_tests:
        warnings.append("No test files or test directories were detected.")
    if not has_manifests:
        warnings.append("No dependency manifest was detected.")
    if sensitive:
        shown = ", ".join(sensitive[:10]) + (" ..." if len(sensitive) > 10 else "")
        warnings.append(
            f"Potentially sensitive file(s) detected: {shown}. Contents were not read and "
            "these files should be excluded from analysis prompts."
        )
    if ignored_dirs:
        warnings.append(
            f"Vendor/cache directories excluded from language, test and manifest detection: "
            f"{', '.join(ignored_dirs)}."
        )
    if skipped_archive_entries:
        warnings.append(
            f"{skipped_archive_entries} archive metadata entr(ies) (e.g. __MACOSX, .DS_Store) were skipped."
        )
    if not single_root:
        warnings.append(
            "The archive has no single top-level directory; the archive root is treated as the project root."
        )
    if symlinks_skipped:
        warnings.append(f"{symlinks_skipped} symbolic link(s) were ignored.")
    if truncated:
        warnings.append(f"Some lists were truncated to {MAX_LISTED_ITEMS} entries.")
    return warnings


class _Budget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.used = 0
        self.truncated = False


def _build_dir(path: Path, rel: str, name: str, budget: _Budget) -> StructureNode:
    node = StructureNode(name=name, path=rel, type="directory", children=[])
    try:
        with os.scandir(path) as iterator:
            entries = sorted(
                iterator, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower())
            )
    except OSError:
        return node

    for entry in entries:
        if entry.is_symlink():
            continue
        if budget.used >= budget.maximum:
            budget.truncated = True
            break
        child_rel = entry.name if rel == "." else f"{rel}/{entry.name}"
        if entry.is_dir(follow_symlinks=False):
            budget.used += 1
            node.children.append(_build_dir(Path(entry.path), child_rel, entry.name, budget))
        elif entry.is_file(follow_symlinks=False):
            budget.used += 1
            node.children.append(
                StructureNode(
                    name=entry.name,
                    path=child_rel,
                    type="file",
                    size_bytes=entry.stat(follow_symlinks=False).st_size,
                )
            )
    return node


def build_structure(project_root: Path, max_nodes: int) -> Tuple[StructureNode, int, bool]:
    """Return (tree, node_count, truncated) for the project directory."""
    budget = _Budget(max_nodes)
    tree = _build_dir(project_root, ".", project_root.name or ".", budget)
    return tree, budget.used, budget.truncated
