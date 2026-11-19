# RootPatch

Explainable software bug detection and repair system (hackathon prototype).

Reference documents: `Rootpatch_Agent_Rules.md`, `Rootpatch_Project_Plan.md`.

## Backend quick start

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## Tests

```bash
cd backend
python -m pytest
```

Tests use temporary directories only; they never touch `backend/workspace/`.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| POST | `/api/projects/upload` | Upload a `.zip` (multipart field `file`); safely extracts and inspects it |
| GET | `/api/projects/{project_id}` | Project metadata + inspection report |
| GET | `/api/projects/{project_id}/structure` | Directory/file tree |
| POST | `/api/projects/{project_id}/scan` | Run static bug detection (AST, Ruff, Bandit) on uploaded Python code |
| GET | `/api/projects/{project_id}/scan` | Retrieve the latest saved scan report for a project |
| POST | `/api/projects/{project_id}/analyze` | Generate AI root cause analysis from the latest scan results |
| GET | `/api/projects/{project_id}/analysis` | Retrieve the latest saved root cause analysis report |
| GET | `/api/projects/{project_id}/analysis/{analysis_id}` | Retrieve an individual root cause analysis record |
| POST | `/api/projects/{project_id}/patches/generate` | Generate and validate unified-diff patches from scan & analysis results |
| GET | `/api/projects/{project_id}/patches` | Retrieve the latest generated patch batch for a project |
| GET | `/api/projects/{project_id}/patches/history` | Retrieve patch application audit history |
| GET | `/api/projects/{project_id}/patches/{patch_id}` | Retrieve an individual patch record |
| GET | `/api/projects/{project_id}/patches/{patch_id}/review` | Retrieve developer review details and live before/after code comparison |
| POST | `/api/projects/{project_id}/patches/{patch_id}/approve` | Explicitly approve a validated patch (does not apply it) |
| POST | `/api/projects/{project_id}/patches/{patch_id}/reject` | Explicitly reject a patch so it remains unapplied |
| POST | `/api/projects/{project_id}/patches/{patch_id}/apply` | Revalidate and atomically apply an explicitly approved patch |

Error responses use `{"detail": "<message>"}`. Status codes: 201 created, 400 invalid/unsafe
archive, 404 unknown project, scan, analysis, or patch, 409 invalid patch state or stale target,
413 size/count limit exceeded, 415 unsupported file type, 422 invalid diff or missing form field,
429 LLM rate limit, 502 LLM provider error, 503 missing LLM configuration, 504 LLM timeout.

## Upload workspace and limits

Each upload gets an isolated directory `backend/workspace/<project_id>/`:

- `original/upload.zip` – read-only copy of the upload
- `source/` – extracted working copy (uploaded code is never executed)
- `metadata.json` – project metadata and inspection report
- `scan_result.json` – latest Step 3 static bug detection report
- `analysis_result.json` – Step 4 root cause analysis report and history
- `patches_result.json` – Step 5/6 generated patches, validation, and review/application states
- `patch_history.json` – Step 6 patch application audit log
- `backups/` – immutable pre-application backups of modified source files

The workspace is git-ignored. Configure via environment variables (defaults in parentheses):

| Variable | Default |
|---|---|
| `ROOTPATCH_WORKSPACE_DIR` | `backend/workspace` |
| `ROOTPATCH_MAX_UPLOAD_BYTES` | 52428800 (50 MB) |
| `ROOTPATCH_MAX_EXTRACTED_FILES` | 5000 |
| `ROOTPATCH_MAX_EXTRACTED_TOTAL_BYTES` | 209715200 (200 MB) |
| `ROOTPATCH_MAX_EXTRACTED_FILE_BYTES` | 26214400 (25 MB) |
| `ROOTPATCH_MAX_STRUCTURE_NODES` | 5000 |
| `ROOTPATCH_MAX_SCAN_FILES` | 1000 |
| `ROOTPATCH_MAX_SCAN_FILE_BYTES` | 2097152 (2 MB) |
| `ROOTPATCH_SCANNER_TIMEOUT_SECONDS` | 30 |
| `ROOTPATCH_LLM_PROVIDER` | `gemini` (`gemini` or `openai`) |
| `ROOTPATCH_LLM_MODEL` | `gemini-4-hydrogen` |
| `ROOTPATCH_LLM_API_KEY` | unset (or `GEMINI_API_KEY` / `OPENAI_API_KEY`) |
| `ROOTPATCH_LLM_BASE_URL` | provider default |
| `ROOTPATCH_LLM_TIMEOUT_SECONDS` | 30 |
| `ROOTPATCH_CONTEXT_LINES_BEFORE` | 20 |
| `ROOTPATCH_CONTEXT_LINES_AFTER` | 20 |
| `ROOTPATCH_MAX_CONTEXT_FILE_BYTES` | 524288 (512 KB) |
| `ROOTPATCH_MAX_CONTEXT_CHARS_PER_FINDING` | 8000 |
| `ROOTPATCH_MAX_TOTAL_CONTEXT_CHARS` | 32000 |
| `ROOTPATCH_MAX_FINDINGS_PER_ANALYSIS` | 50 |
| `ROOTPATCH_CORS_ORIGINS` | local Vite / port 3000 origins |
