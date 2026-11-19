"""Orchestrates upload -> safe extraction -> inspection -> persisted metadata.

Workspace layout (one isolated directory per server-generated project ID):

    workspace/<project_id>/original/upload.zip   immutable copy of the upload
    workspace/<project_id>/source/               extracted working copy
    workspace/<project_id>/metadata.json         project metadata + inspection report
"""

import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import ProjectError, ProjectNotFoundError, UploadError
from app.schemas.project import ArchiveInfo, ProjectMetadata, StructureResponse
from app.services.extraction_service import ExtractionLimits, extract_zip
from app.services.inspection_service import build_structure, find_project_root, inspect_project
from app.utils.file_utils import (
    format_bytes,
    is_valid_project_id,
    remove_tree,
    sanitize_display_name,
)

CHUNK_SIZE = 1024 * 1024
ORIGINAL_DIR = "original"
ARCHIVE_NAME = "upload.zip"
SOURCE_DIR = "source"
METADATA_NAME = "metadata.json"


def _save_stream(stream: BinaryIO, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(destination, "xb") as out:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise UploadError(
                    f"Upload exceeds the maximum allowed size of {format_bytes(max_bytes)}.", 413
                )
            out.write(chunk)
    return written


def create_project_from_upload(upload: UploadFile, settings: Settings) -> ProjectMetadata:
    filename = upload.filename or ""
    if not filename:
        raise UploadError("The uploaded file has no file name.", 400)
    # The extension is only a first filter; the content is verified below.
    if not filename.lower().endswith(".zip"):
        raise UploadError("Unsupported file type. Only .zip archives are accepted.", 415)

    project_id = uuid.uuid4().hex
    workspace = settings.workspace_dir
    workspace.mkdir(parents=True, exist_ok=True)
    project_dir = workspace / project_id
    project_dir.mkdir()

    try:
        archive_path = project_dir / ORIGINAL_DIR / ARCHIVE_NAME
        _save_stream(upload.file, archive_path, settings.max_upload_bytes)
        if not zipfile.is_zipfile(archive_path):
            raise UploadError("The uploaded file is not a valid ZIP archive.", 400)

        source_dir = project_dir / SOURCE_DIR
        limits = ExtractionLimits(
            max_files=settings.max_extracted_files,
            max_total_bytes=settings.max_extracted_total_bytes,
            max_file_bytes=settings.max_extracted_file_bytes,
        )
        extraction = extract_zip(archive_path, source_dir, limits)

        project_root = find_project_root(source_dir)
        fallback_name = Path(filename).name[: -len(".zip")]
        raw_name = project_root.name if project_root != source_dir else fallback_name
        project_name = sanitize_display_name(raw_name)

        report = inspect_project(
            project_id=project_id,
            project_name=project_name,
            project_root=project_root,
            source_root=source_dir,
            skipped_archive_entries=len(extraction.skipped_entries),
        )
        metadata = ProjectMetadata(
            project_id=project_id,
            project_name=project_name,
            original_filename=sanitize_display_name(Path(filename).name, "upload.zip"),
            created_at=datetime.now(timezone.utc).isoformat(),
            status="ready",
            archive=ArchiveInfo(
                files_extracted=extraction.files_extracted,
                extracted_bytes=extraction.total_bytes,
                skipped_entries=len(extraction.skipped_entries),
            ),
            inspection=report,
        )
        (project_dir / METADATA_NAME).write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

        try:  # keep the original upload read-only as an immutable reference
            os.chmod(archive_path, 0o444)
        except OSError:
            pass
        return metadata
    except Exception:
        remove_tree(project_dir)  # never leave partial projects behind
        raise


def _project_dir(project_id: str, settings: Settings) -> Path:
    if not is_valid_project_id(project_id):
        raise ProjectNotFoundError()
    path = settings.workspace_dir / project_id
    if not path.is_dir():
        raise ProjectNotFoundError()
    return path


def load_project(project_id: str, settings: Settings) -> ProjectMetadata:
    metadata_path = _project_dir(project_id, settings) / METADATA_NAME
    if not metadata_path.is_file():
        raise ProjectNotFoundError()
    try:
        return ProjectMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectError("Stored project metadata could not be read.", 500) from exc


def get_project_structure(project_id: str, settings: Settings) -> StructureResponse:
    metadata = load_project(project_id, settings)
    source_dir = _project_dir(project_id, settings) / SOURCE_DIR
    if not source_dir.is_dir():
        raise ProjectNotFoundError()
    project_root = find_project_root(source_dir)
    tree, count, truncated = build_structure(project_root, settings.max_structure_nodes)
    return StructureResponse(
        project_id=metadata.project_id,
        root_directory=metadata.inspection.root_directory,
        total_nodes=count,
        truncated=truncated,
        tree=tree,
    )
