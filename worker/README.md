# RootPatch Local Windows Docker Validation Worker

This worker runs on Windows 11 with Docker Desktop in Linux container mode. It polls
the RootPatch backend over outbound HTTPS, claims validation jobs, downloads
immutable snapshots, runs them in restricted Docker containers, and submits results.

## Install

```powershell
cd worker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure

Copy `.env.example` to `.env` and set a strong `ROOTPATCH_WORKER_TOKEN`.

The matching SHA-256 hash must be configured on the backend as
`ROOTPATCH_WORKER_TOKEN_HASH`.

## Run

```powershell
python main.py
```

Process one job and exit:

```powershell
python main.py --once
```

## Security notes

- Docker is never exposed over TCP.
- Only outbound HTTPS is used.
- Uploaded project code runs only inside restricted Docker containers.
- Temporary snapshots are deleted after each job.
- Do not store the worker token in source control.
