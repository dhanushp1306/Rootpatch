"""Safe workspace retention cleanup utility for RootPatch.

SECURITY & SAFETY GUARANTEES:
1. Dry-run by default: Does NOT delete anything unless `--execute` is explicitly passed.
2. Active project protection: Skips projects that are currently processing, generating,
   or have running validation jobs.
3. Path containment: Strictly validates that target directories match `proj-*` and
   reside within the configured workspace root.
4. Retention window: Only targets projects whose latest modification timestamp is older
   than `--days` (default: 7 days).
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path

_PROJECT_DIR_PATTERN = re.compile(r"^proj-[0-9a-f]{8,32}$")
_ACTIVE_STATUSES = frozenset({"processing", "generating", "scanning", "running"})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("rootpatch.cleanup")


def is_project_active(project_dir: Path) -> bool:
    """Check metadata and validation results to ensure no active workflow is interrupted."""
    metadata_path = project_dir / "metadata.json"
    if metadata_path.is_file():
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            if str(data.get("status", "")).lower() in _ACTIVE_STATUSES:
                return True
        except Exception:
            pass

    validation_path = project_dir / "validation_result.json"
    if validation_path.is_file():
        try:
            val_data = json.loads(validation_path.read_text(encoding="utf-8"))
            latest = val_data.get("latest", {})
            if str(latest.get("status", "")).lower() in _ACTIVE_STATUSES:
                return True
        except Exception:
            pass

    return False


def get_latest_project_mtime(project_dir: Path) -> float:
    """Find the most recent modification timestamp across all files in the project."""
    latest_mtime = project_dir.stat().st_mtime
    for root, _, files in os.walk(project_dir):
        for f in files:
            try:
                mtime = os.path.getmtime(os.path.join(root, f))
                if mtime > latest_mtime:
                    latest_mtime = mtime
            except OSError:
                continue
    return latest_mtime


def run_cleanup(workspace_dir: Path, retention_days: int, dry_run: bool) -> int:
    if not workspace_dir.is_dir():
        logger.error("Workspace directory does not exist: %s", workspace_dir)
        return 1

    cutoff_seconds = time.time() - (retention_days * 86400)
    logger.info("Scanning workspace: %s (Retention cutoff: %d days)", workspace_dir, retention_days)
    logger.info("Mode: %s", "DRY-RUN (no files will be deleted)" if dry_run else "EXECUTE (deletions enabled)")

    total_projects = 0
    eligible_for_delete = []

    for entry in workspace_dir.iterdir():
        if not entry.is_dir():
            continue
        if not _PROJECT_DIR_PATTERN.fullmatch(entry.name):
            continue

        total_projects += 1
        if is_project_active(entry):
            logger.info("Skipping active project: %s", entry.name)
            continue

        latest_mtime = get_latest_project_mtime(entry)
        age_days = (time.time() - latest_mtime) / 86400

        if latest_mtime < cutoff_seconds:
            eligible_for_delete.append((entry, age_days))
        else:
            logger.debug("Project %s is active within retention window (%.1f days old)", entry.name, age_days)

    logger.info("Total projects found: %d. Eligible for deletion: %d.", total_projects, len(eligible_for_delete))

    for proj_dir, age in eligible_for_delete:
        if dry_run:
            logger.info("[DRY-RUN] Would delete: %s (last modified %.1f days ago)", proj_dir.name, age)
        else:
            try:
                shutil.rmtree(proj_dir)
                logger.info("[DELETED] Removed expired project: %s (last modified %.1f days ago)", proj_dir.name, age)
            except Exception as exc:
                logger.error("Failed to delete %s: %s", proj_dir.name, exc)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="RootPatch Safe Workspace Retention Cleaner")
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=Path(os.environ.get("ROOTPATCH_WORKSPACE_DIR", "/var/lib/rootpatch/workspace")),
        help="Path to RootPatch workspace directory",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Retention period in days (projects older than this will be removed)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Perform actual deletions (default is safe dry-run mode)",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    sys.exit(run_cleanup(args.workspace_dir, args.days, dry_run))


if __name__ == "__main__":
    main()
