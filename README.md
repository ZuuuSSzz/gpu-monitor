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
