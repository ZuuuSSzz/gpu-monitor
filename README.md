# server.monitor

Live single-page dashboard for CPU / RAM / GPU / Disk / Network on a Linux server. WebSocket-driven. Read-only.

> **No authentication.** This dashboard exposes hostnames, process names, and resource data to anyone who can reach the port. Run it only on a trusted internal network (bind to a private interface or localhost).

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env

uvicorn monitor:app --host 0.0.0.0 --port 8000
```

Open `http://<host>:8000/`.

## Docker

Requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
on the host for GPU stats. Without it the dashboard still runs and shows
CPU / RAM / disk / network (GPU section reports `nvml_ok: false`).

```bash
# Build and run with GPU access
docker compose up -d --build
```

Open `http://<host>:8000/`. Compose publishes on all interfaces (`8000:8000`) for
LAN access — this dashboard has **no auth**, so only run it on a trusted network.
For localhost-only, change the port mapping in `docker-compose.yml` to `127.0.0.1:8000:8000`.

Without compose:

```bash
docker build -t gpu-monitor .
docker run -d --name gpu-monitor --gpus all -p 127.0.0.1:8000:8000 gpu-monitor
```

CPU/RAM-only (no GPU): drop `--gpus all`, or remove the `deploy:` block from `docker-compose.yml`.

Tunables via env: `POLL_INTERVAL` (seconds), `LOG_LEVEL`.

## Production

Run a single uvicorn worker — the stats collector caches state per process. Put nginx or Caddy in front for TLS.

### systemd unit

`/etc/systemd/system/server-monitor.service`:
```ini
[Unit]
Description=server.monitor
After=network.target

[Service]
Type=simple
User=monitor
WorkingDirectory=/opt/server-monitor
EnvironmentFile=/opt/server-monitor/.env
ExecStart=/opt/server-monitor/.venv/bin/uvicorn monitor:app --host 0.0.0.0 --port 8000 --workers 1
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Caddyfile example

```
monitor.example.com {
    reverse_proxy localhost:8000
}
```

## Endpoints

- `GET /` — Dashboard.
- `GET /api/system` — System info.
- `WS /ws/stats` — Live frames (~every 2s).
- `GET /healthz` — Liveness.

## Tests

```bash
pytest -v
```
