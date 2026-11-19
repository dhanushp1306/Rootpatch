"""Secure ZIP extraction.

Design: every archive entry is validated in a planning pass BEFORE anything
is written, so a malicious archive never leaves partial output. Entry names
and metadata are untrusted. Nothing is ever executed, and extracted files
never receive an executable permission bit.
"""

import re
import stat
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set, Tuple

from app.core.errors import ExtractionError
from app.utils.file_utils import format_bytes, is_within_directory, remove_tree

CHUNK_SIZE = 64 * 1024
MAX_PATH_LENGTH = 1024
MAX_COMPONENT_LENGTH = 255
MAX_PATH_DEPTH = 50

_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_IGNORED_TOP_LEVEL = frozenset({"__macosx"})
_IGNORED_FILE_NAMES = frozenset({".ds_store"})
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


@dataclass(frozen=True)
class ExtractionLimits:
    max_files: int
    max_total_bytes: int
    max_file_bytes: int


@dataclass
class ExtractionResult:
    files_extracted: int = 0
    total_bytes: int = 0
    skipped_entries: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PlannedEntry:
    info: zipfile.ZipInfo
    parts: Tuple[str, ...]
    is_dir: bool


def _display(name: str) -> str:
    shown = repr(name[:80])
    return shown + ("..." if len(name) > 80 else "")


def _fold(parts: Tuple[str, ...]) -> Tuple[str, ...]:
    """Case/Unicode-folded key so collisions are caught on case-insensitive filesystems."""
    return tuple(unicodedata.normalize("NFC", p).casefold() for p in parts)


def _normalise_entry_name(name: str) -> Tuple[str, ...]:
    """Validate an archive entry name and return its safe path components."""
    if not name or any(ord(c) < 32 for c in name):
        raise ExtractionError(f"Invalid entry name in archive: {_display(name)}")
    if len(name) > MAX_PATH_LENGTH:
        raise ExtractionError("Archive contains an entry with an excessively long path.")

    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or _DRIVE_PATTERN.match(normalised):
        raise ExtractionError(f"Absolute path not allowed in archive: {_display(name)}")

    parts = tuple(p for p in normalised.split("/") if p not in ("", "."))
    for part in parts:
        if part == "..":
            raise ExtractionError(f"Path traversal not allowed in archive: {_display(name)}")
        # Catches '...', '.. ' etc., which some platforms treat like '..'.
        if part.strip(" .") == "":
            raise ExtractionError(f"Unsafe path component in archive: {_display(name)}")
        if ":" in part:
            raise ExtractionError(f"Unsafe path component in archive: {_display(name)}")
        if len(part) > MAX_COMPONENT_LENGTH:
            raise ExtractionError("Archive contains an entry with an excessively long name.")
        if part.split(".")[0].strip().lower() in _WINDOWS_RESERVED:
            raise ExtractionError(f"Reserved file name not allowed: {_display(name)}")
    if len(parts) > MAX_PATH_DEPTH:
        raise ExtractionError("Archive contains paths nested too deeply.")
    return parts


def _reject_special_file_types(info: zipfile.ZipInfo) -> None:
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode):
        raise ExtractionError(
            f"Symbolic links are not allowed in archives: {_display(info.filename)}"
        )
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ExtractionError(
            f"Special file types are not allowed in archives: {_display(info.filename)}"
        )


def _should_skip(parts: Tuple[str, ...]) -> bool:
    return parts[0].lower() in _IGNORED_TOP_LEVEL or parts[-1].lower() in _IGNORED_FILE_NAMES


def _plan_entries(
    infos: List[zipfile.ZipInfo], limits: ExtractionLimits
) -> Tuple[List[_PlannedEntry], List[str]]:
    if len(infos) > limits.max_files:
        raise ExtractionError(
            f"Archive contains {len(infos)} entries; the limit is {limits.max_files}.", 413
        )

    planned: List[_PlannedEntry] = []
    skipped: List[str] = []
    file_keys: Set[Tuple[str, ...]] = set()
    dir_keys: Set[Tuple[str, ...]] = set()
    declared_total = 0

    for info in infos:
        if info.flag_bits & 0x1:
            raise ExtractionError("Encrypted archive entries are not supported.")
        _reject_special_file_types(info)

        parts = _normalise_entry_name(info.filename)
        if not parts:
            continue  # e.g. './' - harmless no-op
        if _should_skip(parts):
            skipped.append("/".join(parts))
            continue

        is_dir = info.is_dir()
        key = _fold(parts)
        ancestors = [key[:i] for i in range(1, len(key))]

        for ancestor in ancestors:
            if ancestor in file_keys:
                raise ExtractionError(
                    f"Conflicting paths in archive (file used as directory): {_display(info.filename)}"
                )

        if is_dir:
            if key in file_keys:
                raise ExtractionError(
                    f"Conflicting paths in archive (file and directory): {_display(info.filename)}"
                )
            dir_keys.add(key)
        else:
            if key in file_keys:
                raise ExtractionError(
                    f"Duplicate path in archive: {_display(info.filename)}"
                )
            if key in dir_keys:
                raise ExtractionError(
                    f"Conflicting paths in archive (file and directory): {_display(info.filename)}"
                )
            file_keys.add(key)
            if info.file_size > limits.max_file_bytes:
                raise ExtractionError(
                    f"File {_display(info.filename)} exceeds the per-file limit of "
                    f"{format_bytes(limits.max_file_bytes)}.",
                    413,
                )
            declared_total += info.file_size
            if declared_total > limits.max_total_bytes:
                raise ExtractionError(
                    f"Archive exceeds the total uncompressed size limit of "
                    f"{format_bytes(limits.max_total_bytes)}.",
                    413,
                )

        dir_keys.update(ancestors)
        planned.append(_PlannedEntry(info=info, parts=parts, is_dir=is_dir))

    return planned, skipped


def _write_entries(
    archive: zipfile.ZipFile,
    planned: List[_PlannedEntry],
    root: Path,
    limits: ExtractionLimits,
) -> Tuple[int, int]:
    files = 0
    total = 0
    for entry in planned:
        target = root.joinpath(*entry.parts)
        # Defence in depth: the planning pass already rejected unsafe names.
        if not is_within_directory(root, target):
            raise ExtractionError("Archive entry resolves outside the project workspace.")

        if entry.is_dir:
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        # "xb": never overwrite an existing file. Permissions are not copied
        # from the archive, so no file becomes executable.
        with archive.open(entry.info) as src, open(target, "xb") as out:
            while True:
                chunk = src.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                total += len(chunk)
                # Enforce limits on ACTUAL bytes, not only declared sizes.
                if written > limits.max_file_bytes or total > limits.max_total_bytes:
                    raise ExtractionError("Archive exceeds extraction size limits.", 413)
                out.write(chunk)
        files += 1
    return files, total


def extract_zip(
    archive_path: Path, destination: Path, limits: ExtractionLimits
) -> ExtractionResult:
    """Safely extract `archive_path` into the empty/nonexistent `destination`.

    On any failure the destination is removed, so no partial output remains.
    """
    if destination.exists() and any(destination.iterdir()):
        raise ExtractionError("Extraction destination must be empty.", 500)

    try:
        archive = zipfile.ZipFile(archive_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ExtractionError("The uploaded file is not a valid ZIP archive.") from exc

    with archive:
        planned, skipped = _plan_entries(archive.infolist(), limits)
        if not any(not entry.is_dir for entry in planned):
            raise ExtractionError("The ZIP archive contains no files.")

        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        try:
            files, total = _write_entries(archive, planned, root, limits)
        except ExtractionError:
            remove_tree(destination)
            raise
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError,
                RuntimeError, OSError) as exc:
            remove_tree(destination)
            raise ExtractionError(
                "Failed to extract the archive; it may be corrupt or use an unsupported feature."
            ) from exc

    return ExtractionResult(files_extracted=files, total_bytes=total, skipped_entries=skipped)
