# RootPatch

Explainable software bug detection and repair system (hackathon prototype).

Reference documents: `Rootpatch_Agent_Rules.md`, `Rootpatch_Project_Plan.md`.

## Backend quick start

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Health check: http://localhost:8000/api/health

## Tests

```bash
cd backend
python -m pytest
```
