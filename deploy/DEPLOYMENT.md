# RootPatch Production Deployment Guide

This guide provides an ordered procedure for deploying RootPatch to a Linux VPS.
Replace every value marked `<...>` (for example `<your-domain>`, `<your-email>`) with
values for your own server before running the commands.

---

## 1. Architecture Overview

RootPatch uses a unified, single-origin architecture:

```text
[ Browser / Public User ]
           |
           v  HTTPS (:443)
[ Caddy Reverse Proxy & Static Host ]
     |--> /          --> Static React SPA (/var/www/rootpatch/frontend/dist)
     `--> /api/*     --> Uvicorn FastAPI Backend (127.0.0.1:8000)
                              |
                              +--> Persistent Workspace (/var/lib/rootpatch/workspace)
                              +--> Outbound HTTPS (LLM provider API)
                              `--> Docker Engine (/var/run/docker.sock)
                                        |
                                        `--> Sandboxed Test Containers
                                            (--network none, non-root, read-only root FS)
```

Notes:

* The backend binds only to `127.0.0.1:8000`; it is not reachable directly from the
  public internet. All public traffic goes through Caddy.
* Caddy enforces HTTP Basic Authentication before the frontend or `/api/*` is served.
* The backend runs a single Uvicorn worker (`--workers 1`) because RootPatch uses
  process-local locks for patch application/conflict prevention.
* Docker container restrictions reduce the attack surface of validated project code,
  but they do **not** provide complete host isolation. Access to the Docker daemon is
  effectively root-equivalent on the host (see Section 11).

---

## 2. Linux VPS Prerequisites

* **OS:** Ubuntu 24.04 LTS (or Debian 12)
* **Compute:** Minimum 2 vCPUs, 4 GB RAM (recommended: 4 GB+)
* **Storage:** 40+ GB NVMe SSD
* **Domain:** A public domain with an `A` record pointing to the server's public IPv4
  address (for example `rootpatch.example.com -> 203.0.113.10`).
* **Access:** SSH as `root` or a sudo user.

Install base packages:

```bash
apt update && apt upgrade -y

apt install -y curl git ufw python3 python3-pip python3-venv ca-certificates gnupg

# Node.js 20 LTS (for building the frontend)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# Caddy
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
  gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
  tee /etc/apt/sources.list.d/caddy-stable.list
apt update
apt install -y caddy
systemctl enable caddy
```

Configure the firewall:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

---

## 3. Docker Installation and Validation Image Build

Install Docker CE:

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

Create the application directories and dedicated service account first (Section 4),
then build the validation image:

```bash
cd /var/www/rootpatch
docker build -t rootpatch-python-validate:latest -f docker/Dockerfile.python-validate .

# Verify the image runs under the same strict restrictions used by the runner:
docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --user 65534:65534 \
  rootpatch-python-validate:latest pytest --version
# Expected: pytest 8.3.4
```

The image provides Python 3.11 with pytest, pytest-timeout, and pytest-mock
pre-installed so validation can run with `--network none`.

---

## 4. Dedicated Service Account and Permissions

Create an unprivileged system user for the backend and persistent storage:

```bash
useradd -r -s /bin/false -d /var/lib/rootpatch -m rootpatch
usermod -aG docker rootpatch

mkdir -p /var/www/rootpatch
mkdir -p /var/lib/rootpatch/workspace
mkdir -p /etc/rootpatch
mkdir -p /var/log/caddy

chown -R rootpatch:rootpatch /var/lib/rootpatch
chmod 750 /var/lib/rootpatch/workspace
chown -R caddy:caddy /var/log/caddy
```

Security note: adding `rootpatch` to the `docker` group grants Docker daemon access.
See Section 11.

---

## 5. Backend Production Dependencies and Environment Configuration

### 5.1 Clone the repository

```bash
cd /var/www/rootpatch
git clone https://github.com/<your-org>/rootpatch.git .
chown -R rootpatch:rootpatch /var/www/rootpatch
```

### 5.2 Backend virtual environment

```bash
cd /var/www/rootpatch/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install --no-cache-dir -r requirements-prod.txt
deactivate

chown -R rootpatch:rootpatch /var/www/rootpatch
```

### 5.3 Production environment file

```bash
cp /var/www/rootpatch/deploy/.env.production.example /etc/rootpatch/rootpatch.env
```

Edit `/etc/rootpatch/rootpatch.env` and set at least:

```env
ROOTPATCH_WORKSPACE_DIR=/var/lib/rootpatch/workspace
ROOTPATCH_CORS_ORIGINS=https://<your-domain>
ROOTPATCH_LLM_PROVIDER=openai-compatible
ROOTPATCH_LLM_MODEL=<your-model>
ROOTPATCH_LLM_API_KEY=<your-llm-api-key>
ROOTPATCH_LLM_BASE_URL=<your-llm-base-url>
ROOTPATCH_LLM_TIMEOUT_SECONDS=60
ROOTPATCH_VALIDATION_PYTHON_IMAGE=rootpatch-python-validate:latest
```

Lock down the secret file:

```bash
chown root:rootpatch /etc/rootpatch/rootpatch.env
chmod 640 /etc/rootpatch/rootpatch.env
```

Secrets remain in `/etc/rootpatch/rootpatch.env` only; do not commit them to source
control and do not place them in the frontend build.

### 5.4 Install the systemd unit

```bash
cp /var/www/rootpatch/deploy/rootpatch-backend.service /etc/systemd/system/rootpatch-backend.service
systemctl daemon-reload
systemctl enable --now rootpatch-backend.service

systemctl status rootpatch-backend.service --no-pager
curl -s http://127.0.0.1:8000/api/health
# Expected: {"status":"healthy","app":"RootPatch","version":"0.1.0",...}
```

The unit uses exactly one worker and binds to localhost only:

```text
ExecStart=.../uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 ...
```

---

## 6. Persistent Workspace Creation and Permissions

The workspace is created in Section 4. Verify ownership and permissions:

```bash
ls -ld /var/lib/rootpatch/workspace
chown -R rootpatch:rootpatch /var/lib/rootpatch/workspace
chmod 750 /var/lib/rootpatch/workspace
```

Do not delete or modify existing workspace data. RootPatch accumulates uploaded
projects, extracted source trees, generated patches, and validation artifacts over
time. Plan storage and backups accordingly (Section 11).

---

## 7. Frontend Production Build

```bash
cd /var/www/rootpatch/frontend
npm ci
npm run build

ls -la /var/www/rootpatch/frontend/dist/index.html
chown -R rootpatch:rootpatch /var/www/rootpatch/frontend/dist
```

In production, `getApiBaseUrl()` resolves to an empty string, so the frontend
uses same-origin relative requests (`/api/...`) through Caddy. Do not set
`VITE_API_BASE_URL` to a visitor-facing localhost URL.

---

## 8. Caddy Installation and HTTPS Configuration

Copy and edit the Caddyfile:

```bash
cp /var/www/rootpatch/deploy/Caddyfile /etc/caddy/Caddyfile
```

Replace `rootpatch.yourdomain.com` with `<your-domain>` in `/etc/caddy/Caddyfile`.
Caddy provisions and renews Let's Encrypt certificates automatically for a public
domain.

Validate and restart:

```bash
caddy validate --config /etc/caddy/Caddyfile
caddy fmt --overwrite /etc/caddy/Caddyfile
systemctl restart caddy
systemctl status caddy --no-pager
```

Caddy serves the frontend from `/var/www/rootpatch/frontend/dist` and proxies
`/api/*` to `127.0.0.1:8000`. The 60 MB request body limit supports the 50 MB
upload limit with overhead.

---

## 9. Basic Authentication Setup

### 9.1 Generate a password hash

On the server (or any machine with Caddy installed), generate a bcrypt hash:

```bash
caddy hash-password --plaintext '<choose-a-strong-password>'
# Output example: $2a$14$...
```

Never store the plaintext password in the repository or Caddyfile.

### 9.2 Provide credentials to Caddy

Create a restricted environment file for the Caddy service:

```bash
cat >/etc/caddy/rootpatch-auth.env <<'EOF'
ROOTPATCH_BASIC_AUTH_USER=<choose-a-username>
ROOTPATCH_BASIC_AUTH_HASH=<paste-bcrypt-hash-here>
EOF
chown root:caddy /etc/caddy/rootpatch-auth.env
chmod 640 /etc/caddy/rootpatch-auth.env
```

Make the Caddy systemd service load it:

```bash
systemctl edit caddy
```

Add:

```ini
[Service]
EnvironmentFile=/etc/caddy/rootpatch-auth.env
```

Then reload and restart:

```bash
systemctl daemon-reload
systemctl restart caddy
```

The Caddyfile references these variables:

```caddy
basic_auth {
    {$ROOTPATCH_BASIC_AUTH_USER} {$ROOTPATCH_BASIC_AUTH_HASH}
}
```

### 9.3 Updating credentials

1. Generate a new hash with `caddy hash-password --plaintext '<new-password>'`.
2. Update `ROOTPATCH_BASIC_AUTH_HASH` (and `ROOTPATCH_BASIC_AUTH_USER` if needed)
   in `/etc/caddy/rootpatch-auth.env`.
3. Restart Caddy: `systemctl restart caddy`.
4. Verify with `curl -u <user>:<new-password> https://<your-domain>/api/health`.

Because the backend binds only to localhost, API endpoints cannot be reached
around the Caddy authentication layer from the public internet.

---

## 10. Health Endpoint Verification

```bash
# Unauthenticated request should be rejected:
curl -i https://<your-domain>/api/health
# Expected: 401 Unauthorized

# Authenticated request should succeed:
curl -u <user>:<password> https://<your-domain>/api/health
# Expected: {"status":"healthy","app":"RootPatch","version":"0.1.0",...}

# Frontend should load:
curl -I https://<your-domain>/
```

Also verify a test upload, static scan, AI analysis, patch generation, and patch
validation end-to-end.

---

## 11. Storage Growth, Backup, and Retention

### 11.1 Storage growth

The workspace grows with every uploaded project. Each project may contain extracted
source files, generated patches, scan results, analysis results, and validation
artifacts. The 50 MB upload limit does not bound total on-disk usage because
extracted archives can be up to 200 MB per project.

Monitor disk usage:

```bash
du -sh /var/lib/rootpatch/workspace
df -h /var/lib/rootpatch
```

### 11.2 Backup

Back up the persistent workspace and configuration regularly (for example with
an external backup tool or a scheduled job outside this application):

```bash
# Example manual backup:
tar -czf /root/rootpatch-workspace-$(date +%F).tar.gz /var/lib/rootpatch/workspace
cp /etc/rootpatch/rootpatch.env /root/rootpatch.env.$(date +%F).bak
cp /etc/caddy/Caddyfile /root/Caddyfile.$(date +%F).bak
```

Store backups off-server. Do not store backups in the live workspace directory.

### 11.3 Retention

No automatic deletion is configured by default. Retention decisions are the
operator's responsibility. A dry-run cleanup utility is included for manual use:

```bash
/var/www/rootpatch/backend/.venv/bin/python \
  /var/www/rootpatch/deploy/cleanup_workspace.py \
  --workspace-dir /var/lib/rootpatch/workspace --days 7
```

It is dry-run by default and only removes project directories older than the
retention window. Review dry-run output before using `--execute`. Do not schedule
automatic deletion without confirming backups and active-project protection.

### 11.4 Docker daemon security

Docker daemon access is effectively root-equivalent on the host. The
`rootpatch` user is in the `docker` group so the backend can run validation
containers. Any process with Docker socket access can potentially access host
resources. Mitigations:

* Run RootPatch on a dedicated VPS, not a shared host with other critical services.
* Keep the backend bound to localhost and protected by Caddy Basic Authentication.
* Consider rootless Docker for higher-security environments.
* Keep AppArmor/SELinux enabled.
* Treat container restrictions (network disabled, read-only root filesystem,
  dropped capabilities, non-root user) as defense-in-depth for validated project
  code, not as complete host isolation.

---

## 12. Troubleshooting and Rollback

### Troubleshooting

* **Backend will not start:** check `journalctl -u rootpatch-backend.service -e`
  and verify `/etc/rootpatch/rootpatch.env` permissions (`root:rootpatch`, `640`).
* **Caddy certificate errors:** ensure the domain's `A` record resolves to the VPS
  and ports 80/443 are open.
* **401 on all requests:** verify `ROOTPATCH_BASIC_AUTH_HASH` in
  `/etc/caddy/rootpatch-auth.env` and restart Caddy.
* **Validation says Docker unavailable:** confirm `docker info` works as the
  `rootpatch` user and that the validation image exists
  (`docker images rootpatch-python-validate:latest`).
* **Disk full:** inspect `/var/lib/rootpatch/workspace` and run the cleanup
  utility in dry-run mode first.

### Rollback

1. Stop the new release:
   ```bash
   systemctl stop rootpatch-backend.service
   systemctl stop caddy
   ```
2. Restore the previous application directory from backup or git checkout.
3. Reinstall backend dependencies if needed:
   ```bash
   cd /var/www/rootpatch/backend
   source .venv/bin/activate
   pip install --no-cache-dir -r requirements-prod.txt
   deactivate
   ```
4. Restore configuration if changed:
   ```bash
   cp /root/Caddyfile.<date>.bak /etc/caddy/Caddyfile
   cp /root/rootpatch.env.<date>.bak /etc/rootpatch/rootpatch.env
   ```
5. Restart services:
   ```bash
   systemctl daemon-reload
   systemctl start rootpatch-backend.service
   systemctl start caddy
   ```
6. Verify health:
   ```bash
   curl -u <user>:<password> https://<your-domain>/api/health
   ```

Do not delete workspace data during rollback.

---

## 13. Verification Checklist

* [ ] `https://<your-domain>` loads the frontend over valid HTTPS.
* [ ] `https://<your-domain>/api/health` returns `{"status":"healthy"}` when authenticated.
* [ ] Unauthenticated requests to `/` and `/api/*` return `401`.
* [ ] Project upload succeeds (up to 50 MB).
* [ ] Static scan runs successfully.
* [ ] AI root-cause analysis connects to the configured LLM provider.
* [ ] Patch generation produces unified diffs.
* [ ] Patch validation runs in the hardened Docker container.
* [ ] Workspace persists across backend restarts.
