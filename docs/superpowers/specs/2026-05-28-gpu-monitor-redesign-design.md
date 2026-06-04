# GPU Monitor — Production Redesign

**Status:** Approved design, ready for implementation plan
**Date:** 2026-05-28
**Owner:** abdullahammar025@gmail.com

## Goal

Upgrade the existing single-file FastAPI GPU monitor into a production-grade, professional-looking live dashboard for sysadmin use. Live data only (no historical persistence). Single-page layout, WebSocket-driven, hybrid visual style (modern layout + monospace numbers).

## Non-Goals (YAGNI)

- No historical persistence / SQLite / time-series storage.
- No multi-server support.
- No threshold alert notifications (browser push). Visual pulse only.
- No process kill or control actions. Read-only.
- No built-in HTTPS termination. Use nginx/Caddy in front in production.
- No mobile-first layout. Responsive down to ~768px, but desktop is the target.

## Architecture

### Backend
- `monitor.py` — FastAPI app. Routes:
  - `GET /` — Basic-auth gate, serves `static/index.html`.
  - `GET /static/*` — static assets (JS, CSS).
  - `GET /api/system` — one-shot static info (hostname, OS, kernel, driver, CUDA version). Also issues a short-lived signed token used to authenticate the WebSocket.
  - `WS /ws/stats?token=<jwt>` — pushes one JSON stats frame every `POLL_INTERVAL` seconds.
  - `GET /healthz` — no-auth liveness probe. Returns 200 if NVML and psutil are responsive.
- `config.py` — `pydantic-settings` loads from `.env`. Holds users (bcrypt hashes), bind host/port, poll interval, log level, token secret.

### Frontend
```
static/
  index.html   # markup only
  app.js       # WS client, render, theme toggle, sparklines, reconnect
  style.css    # CSS variables + light/dark themes
```

### Transport
WebSocket `/ws/stats`. Server pushes one JSON frame every 2s (configurable). Client auto-reconnects with exponential backoff: 1s → 2s → 4s → 8s → cap 10s.

## Data Flow

1. Browser hits `/` → Basic auth → static HTML.
2. JS fetches `/api/system` once → header info + a short-lived (60s) signed token.
3. JS opens `wss://.../ws/stats?token=...` → server validates token, starts pushing.
4. Each frame updates DOM (200ms value tween), pushes value into in-memory sparkline buffers (60 points ≈ 2 min).
5. On threshold cross, frontend toggles `.warn` / `.crit` classes (color + pulse).
6. On disconnect, badge → "OFFLINE", client reconnects with backoff.

## WebSocket Frame Schema

```json
{
  "ts": 1716902400,
  "status": "OK",
  "uptime_s": 1218400,
  "cpu": {
    "total": 42.1,
    "cores": [38.0, 41.2, ...],
    "freq": 3200,
    "freq_max": 4500,
    "load": [1.2, 1.5, 1.8],
    "proc_count": 412
  },
  "ram": { "used_gb": 19.2, "total_gb": 32, "pct": 60, "cached_gb": 4.1, "avail_gb": 12.8 },
  "swap": { "used_gb": 0.1, "total_gb": 8, "pct": 1 },
  "disk": { "used_gb": 412, "total_gb": 1000, "pct": 41 },
  "net":  { "up_mbs": 1.2, "down_mbs": 12.4 },
  "gpus": [
    {
      "idx": 0, "name": "RTX 4090",
      "util": 87, "mem_util": 64,
      "vram_used": 18.2, "vram_total": 24, "vram_pct": 76,
      "temp": 72, "power": 380, "power_cap": 450,
      "clock": 2520, "mem_clock": 10500, "fan": 62,
      "procs": [{ "pid": 12345, "name": "python", "vram_mb": 12400 }]
    }
  ],
  "top_procs": [
    { "pid": 12345, "user": "client", "name": "python train.py",
      "cpu": 98.2, "mem_mb": 4200, "gpu_mem_mb": 12400 }
  ]
}
```

## Stats Collector Notes

- `psutil.cpu_percent(interval=None)` — non-blocking delta from last call. Fixes the current 0.3s blocking call.
- Each metric (CPU, RAM, swap, disk, net, NVML calls) wrapped in `try/except`. A single failure produces a `null` field; the frame still ships.
- Top processes: `psutil.process_iter(['pid','name','username','cpu_percent','memory_info'])`, sort by `cpu_percent`, cap at 10.
- GPU→PID mapping via `nvmlDeviceGetComputeRunningProcesses` + `nvmlDeviceGetGraphicsRunningProcesses`. Cached for 5s; NVML enumeration is expensive.
- One global background task per WS connection so clients can have independent poll intervals later (currently all 2s).

## UI Layout (single page, no tabs)

```
Header: server.monitor · hostname · OS · kernel · uptime · driver · CUDA  [● STATUS] [theme]
─────────────────────────────────────────────────────────────────────────────────────────
Row 1 (KPI tiles ×4):   CPU%   GPU% (max across GPUs)   RAM%   NET (MB/s)
                        each: SVG donut ring + sparkline
─────────────────────────────────────────────────────────────────────────────────────────
Row 2 (CPU card):       ring + per-core auto-wrap mini-bars + freq + load avg
─────────────────────────────────────────────────────────────────────────────────────────
Row 3 (GPU cards):      one card per GPU. Util ring · VRAM bar · temp · power · clock · fan.
                        Sub-list of processes attributed to that GPU.
─────────────────────────────────────────────────────────────────────────────────────────
Row 4 (2-column):       RAM/SWAP card                   DISK/NETWORK card
─────────────────────────────────────────────────────────────────────────────────────────
Row 5 (Top processes):  Sortable table, top 10 — pid · user · name · CPU% · MEM MB · GPU MEM
```

## Visual Style — Hybrid

- Body font: **Inter** (sans-serif), 14px.
- Numbers / values / code: **JetBrains Mono** (kept).
- Real **SVG donut rings** for headline KPIs. Gradient stroke.
- Slim CSS-gradient bars for secondary metrics. ASCII bars retired.
- Cards: 1px border + soft shadow. Subtle glassmorphism, no heavy blur.
- Animations: 200ms value tween (requestAnimationFrame), pulse on threshold crossing, smooth sparkline updates.
- Theme toggle in header, persisted in `localStorage`. CSS variables flipped via `[data-theme="light"]`.

### Color Coding
- < 60% → green
- 60–85% → amber
- \> 85% → red (+ pulse)

### Dark Palette (default)
- bg `#0a0c10`, panel `#11141d`, border `#222838`, text `#c7d0e0`, dim `#5a6378`
- green `#3ddc84`, amber `#f5c451`, red `#ff5c6c`, blue `#4d9fff`, purple `#b073ff`, cyan `#3de0e0`

### Light Palette
- bg `#f7f8fa`, panel `#ffffff`, border `#e3e6ec`, text `#1a1f2e`, dim `#6b7280`
- Accents slightly desaturated versions of the dark accents.

## Auth & Config

### Users
- Stored as bcrypt hashes in env: `MONITOR_USERS=admin:$2b$...,client:$2b$...`
- `secrets.compare_digest` is not used for bcrypt — `passlib.hash.bcrypt.verify` handles constant-time compare internally.
- A small helper script `hash_pw.py` for generating new hashes (one-off utility).

### WebSocket Auth
- `/api/system` returns a short-lived (60s) signed token (`itsdangerous.TimestampSigner` or PyJWT, signed with `TOKEN_SECRET` from env).
- Client passes token as query param when opening WS.
- Server validates token on WS accept; on failure closes with code `1008`.

### `.env.example`
```
MONITOR_USERS=admin:$2b$12$...,client:$2b$12$...
TOKEN_SECRET=change_me_to_a_long_random_string
BIND_HOST=0.0.0.0
BIND_PORT=8000
POLL_INTERVAL=2.0
LOG_LEVEL=INFO
```

## Logging

- Standard library `logging`, structured single-line output (timestamp, level, logger, message).
- Logs to stdout (systemd / docker friendly).
- Events: startup, NVML init success/failure, auth failure, WS connect / disconnect (with client ip + user), stats collector exceptions.

## Error Handling

- NVML init failure → server still starts. GPU section returns empty `gpus: []` with a `nvml_error` field set. Frontend shows "NVML unavailable".
- Per-metric `try/except` in the collector → missing values are `null`, frontend renders `—`.
- WS server-side task exception → caught, connection closed cleanly. Client reconnects.
- Frontend WS error/close → exponential backoff reconnect, "OFFLINE" badge, last-known values held.

## File Structure

```
gpu-monitor/
├── monitor.py           # FastAPI app, WS, stats collector  (~250 lines)
├── config.py            # Settings via pydantic-settings     (~30 lines)
├── hash_pw.py           # one-off helper to generate bcrypt hashes (~10 lines)
├── .env.example
├── .gitignore           # ignore .env, __pycache__, *.pyc
├── requirements.txt
├── README.md            # install, run, systemd example
└── static/
    ├── index.html       # markup, ~80 lines
    ├── app.js           # ~250 lines
    └── style.css        # ~200 lines (with light/dark vars)
```

`monitor_backup.py` and `monitor_v2_backup.py` left in place as the user's safety net.

## Dependencies

```
fastapi
uvicorn[standard]
psutil
pynvml
pydantic-settings
passlib[bcrypt]
itsdangerous          # or PyJWT — itsdangerous is lighter
python-multipart      # only if needed; FastAPI may not pull it for this surface
```

## Production Notes (documented in README, not generated as code)

- Recommended: run behind nginx or Caddy for TLS termination.
- Sample systemd unit included in README.
- Run command: `uvicorn monitor:app --host 0.0.0.0 --port 8000 --workers 1` (single worker — stats collector state is per-process).

## Testing Strategy

- Manual smoke test: load page, confirm WS connects, all KPI tiles populate, GPU card matches `nvidia-smi`, theme toggle persists.
- No automated test suite in this iteration (small app, single dev). If tests are added later, target the stats collector pure functions (extract from FastAPI handlers).

## Open Risks

- bcrypt verify on every Basic-auth-protected request adds ~50–100ms. Acceptable here — only `/`, `/api/system`, and the static files go through Basic auth; WS is token-based after that, so the hot path is free.
- Single-worker `uvicorn` is required because the stats collector caches state (last net counters, GPU→PID map) in-process. Documented in README.
