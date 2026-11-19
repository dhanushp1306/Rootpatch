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

Error responses use `{"detail": "<message>"}`. Status codes: 201 created, 400 invalid/unsafe
archive, 404 unknown project, 413 size/count limit exceeded, 415 unsupported file type,
422 missing form field.

## Upload workspace and limits

Each upload gets an isolated directory `backend/workspace/<project_id>/`:

- `original/upload.zip` – read-only copy of the upload
- `source/` – extracted working copy (uploaded code is never executed)
- `metadata.json` – project metadata and inspection report

The workspace is git-ignored. Configure via environment variables (defaults in parentheses):

| Variable | Default |
|---|---|
| `ROOTPATCH_WORKSPACE_DIR` | `backend/workspace` |
| `ROOTPATCH_MAX_UPLOAD_BYTES` | 52428800 (50 MB) |
| `ROOTPATCH_MAX_EXTRACTED_FILES` | 5000 |
| `ROOTPATCH_MAX_EXTRACTED_TOTAL_BYTES` | 209715200 (200 MB) |
| `ROOTPATCH_MAX_EXTRACTED_FILE_BYTES` | 26214400 (25 MB) |
| `ROOTPATCH_MAX_STRUCTURE_NODES` | 5000 |
| `ROOTPATCH_CORS_ORIGINS` | local Vite / port 3000 origins |
