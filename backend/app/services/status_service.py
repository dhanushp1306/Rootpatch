"""Project status: reports which optional resources actually exist.

Never fabricates results. Missing resources are reported as `missing`;
unreadable stored artifacts are reported as `error` (a genuine failure).
"""

from typing import Callable, Optional

from app.core.config import Settings
from app.core.errors import ProjectError
from app.schemas.project import (
    PatchStatusCounts,
    ProjectStatusResponse,
    ResourceStatus,
)
from app.services import (
    analysis_service,
    patch_service,
    scan_service,
    upload_service,
    validation_service,
)


def _missing() -> ResourceStatus:
    return ResourceStatus(state="missing", available=False)


def _error(exc: Exception) -> ResourceStatus:
    message = exc.message if isinstance(exc, ProjectError) else "Stored data could not be read."
    return ResourceStatus(state="error", available=False, detail=message)


def build_project_status(project_id: str, settings: Settings) -> ProjectStatusResponse:
    metadata = upload_service.load_project(project_id, settings)  # raises project_not_found
    project_dir = upload_service._project_dir(project_id, settings)

    project = ResourceStatus(
        state="available", available=True, updated_at=metadata.created_at
    )

    source_dir = project_dir / upload_service.SOURCE_DIR
    structure = (
        ResourceStatus(state="available", available=True)
        if source_dir.is_dir()
        else _missing()
    )

    scan_status = _missing()
    scan_path = project_dir / scan_service.SCAN_RESULT_NAME
    if scan_path.is_file():
        try:
            scan = scan_service.get_latest_scan(project_id, settings)
            scan_status = ResourceStatus(
                state="available",
                available=True,
                count=scan.total_findings,
                updated_at=scan.scanned_at,
            )
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            scan_status = _error(exc)

    analysis_status = _missing()
    analysis_path = project_dir / analysis_service.ANALYSIS_RESULT_NAME
    if analysis_path.is_file():
        try:
            store = analysis_service._load_history_store(analysis_path)
            if store is not None:
                analysis_status = ResourceStatus(
                    state="available",
                    available=True,
                    count=len(store.latest.analyses),
                    updated_at=store.latest.analyzed_at,
                )
        except Exception as exc:  # noqa: BLE001
            analysis_status = _error(exc)

    patches_status = _missing()
    counts = PatchStatusCounts()
    patch_path = project_dir / patch_service.PATCH_RESULT_NAME
    if patch_path.is_file():
        try:
            pstore = patch_service._load_patch_history(patch_path)
            if pstore is not None:
                by_status: dict[str, int] = {}
                for record in pstore.latest.patches:
                    key = str(getattr(record, "status", "unknown"))
                    by_status[key] = by_status.get(key, 0) + 1
                counts = PatchStatusCounts(
                    total=len(pstore.latest.patches), by_status=by_status
                )
                patches_status = ResourceStatus(
                    state="available",
                    available=True,
                    count=len(pstore.latest.patches),
                    updated_at=pstore.latest.generated_at,
                )
        except Exception as exc:  # noqa: BLE001
            patches_status = _error(exc)

    validations_status = _missing()
    validation_path = project_dir / validation_service.VALIDATION_RESULT_NAME
    if validation_path.is_file():
        try:
            vstore = validation_service._load_validation_store(validation_path)
            if vstore.validations:
                validations_status = ResourceStatus(
                    state="available",
                    available=True,
                    count=len(vstore.validations),
                )
        except Exception as exc:  # noqa: BLE001
            validations_status = _error(exc)

    return ProjectStatusResponse(
        project_id=metadata.project_id,
        project_name=metadata.project_name,
        project=project,
        structure=structure,
        scan=scan_status,
        analysis=analysis_status,
        patches=patches_status,
        validations=validations_status,
        patch_counts=counts,
        can_analyze=structure.available,
        can_generate_patches=analysis_status.available,
    )
