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

## Frontend (`frontend/`)

React + Vite + TypeScript + Tailwind CSS dashboard for the complete RootPatch workflow (upload, structure explorer, static scan, AI root-cause analysis, patch review/approval/application, isolated container validation, and audit history).

```bash
cd frontend
npm install
cp .env.example .env   # optional: defaults VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Frontend dev server runs at `http://localhost:5173` (proxying `/api` to `VITE_API_BASE_URL`).

### Frontend verification commands

```bash
cd frontend
npm test        # Run Vitest + React Testing Library suite
npm run typecheck
npm run build   # Production TypeScript check & Vite bundle into frontend/dist
```

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
| POST | `/api/projects/{project_id}/patches/{patch_id}/validate` | Run isolated container test validation & baseline regression check on an applied patch |
| GET | `/api/projects/{project_id}/patches/{patch_id}/validations` | Retrieve validation run history for a specific patch |
| GET | `/api/projects/{project_id}/validations` | Retrieve all validation runs persisted for a project |
| GET | `/api/projects/{project_id}/validations/{validation_id}` | Retrieve an individual validation report |

Error responses use `{"detail": "<message>"}`. Status codes: 201 created, 400 invalid/unsafe
archive, 404 unknown project, scan, analysis, patch, or validation report, 409 invalid patch
state (e.g. unapplied patch validation) or stale target, 413 size/count limit exceeded, 415
unsupported file type, 422 invalid diff, unsafe command override, or missing form field, 429 LLM
rate limit, 502 LLM provider error, 503 missing LLM configuration, 504 LLM timeout.

## Upload workspace and limits

Each upload gets an isolated directory `backend/workspace/<project_id>/`:

- `original/upload.zip` – read-only copy of the upload
- `source/` – extracted working copy (uploaded code is never executed directly on the host)
- `metadata.json` – project metadata and inspection report
- `scan_result.json` – latest Step 3 static bug detection report
- `analysis_result.json` – Step 4 root cause analysis report and history
- `patches_result.json` – Step 5/6 generated patches, validation, and review/application states
- `patch_history.json` – Step 6 patch application audit log
- `validation_result.json` – Step 7 isolated container test validation reports and history
- `backups/` – immutable pre-application backups of modified source files

> **Container isolation (Step 7):** Patch validation executes tests exclusively inside a hardened,
> network-disabled (`--network none`), read-only rootfs, non-root Docker container with CPU/memory/PID
> limits and strict timeouts. If Docker is unavailable, validation reports status `BLOCKED` and
> never falls back to host execution.

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
| `ROOTPATCH_LLM_PROVIDER` | `gemini` (`gemini`, `openai`, `xai`, or `grok`) |
| `ROOTPATCH_LLM_MODEL` | `gemini-4-hydrogen` (`grok-4.7` when provider is `xai` or `grok`) |
| `ROOTPATCH_LLM_API_KEY` | unset (or `GEMINI_API_KEY` / `OPENAI_API_KEY` / `XAI_API_KEY`) |
| `ROOTPATCH_LLM_BASE_URL` | provider default |
| `ROOTPATCH_LLM_TIMEOUT_SECONDS` | 30 |
| `ROOTPATCH_CONTEXT_LINES_BEFORE` | 20 |
| `ROOTPATCH_CONTEXT_LINES_AFTER` | 20 |
| `ROOTPATCH_MAX_CONTEXT_FILE_BYTES` | 524288 (512 KB) |
| `ROOTPATCH_MAX_CONTEXT_CHARS_PER_FINDING` | 8000 |
| `ROOTPATCH_MAX_TOTAL_CONTEXT_CHARS` | 32000 |
| `ROOTPATCH_MAX_FINDINGS_PER_ANALYSIS` | 50 |
| `ROOTPATCH_VALIDATION_TIMEOUT_SECONDS` | 60 |
| `ROOTPATCH_VALIDATION_MEMORY_LIMIT` | `512m` |
| `ROOTPATCH_VALIDATION_CPUS` | `1.0` |
| `ROOTPATCH_VALIDATION_PIDS_LIMIT` | 64 |
| `ROOTPATCH_MAX_VALIDATION_OUTPUT_BYTES` | 65536 (64 KB) |
| `ROOTPATCH_VALIDATION_PYTHON_IMAGE` | `python:3.11-slim` |
| `ROOTPATCH_VALIDATION_NODE_IMAGE` | `node:20-slim` |
| `ROOTPATCH_VALIDATION_NETWORK_DISABLED` | `true` |
| `ROOTPATCH_CORS_ORIGINS` | local Vite / port 3000 origins |
