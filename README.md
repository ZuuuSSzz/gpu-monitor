# server.monitor

Live single-page dashboard for CPU / RAM / GPU / Disk / Network on a Linux server. WebSocket-driven. Read-only.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env

# Generate a bcrypt user (paste output into MONITOR_USERS in .env)
python hash_pw.py

# Generate a TOKEN_SECRET (paste output into .env)
python -c "import secrets;print(secrets.token_urlsafe(48))"

uvicorn monitor:app --host 0.0.0.0 --port 8000
```

Open `http://<host>:8000/`. Use the credentials you created.

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

- `GET /` — Dashboard (Basic auth).
- `GET /api/system` — System info + short-lived WS token (Basic auth).
- `WS /ws/stats?token=…` — Live frames (~every 2s).
- `GET /healthz` — Liveness (no auth).

## Tests

```bash
pytest -v
```
