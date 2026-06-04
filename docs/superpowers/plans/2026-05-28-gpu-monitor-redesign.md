# GPU Monitor Production Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the existing single-file GPU monitor into a production-grade live dashboard with WebSocket transport, modern UI, top-processes list, theme toggle, and env-based bcrypt auth.

**Architecture:** FastAPI backend serves static frontend, exposes one-shot `/api/system`, WebSocket `/ws/stats` (2s push), and `/healthz`. Frontend is plain HTML/CSS/JS — no framework. Live data only, no persistence. Stats collector is a pure module so the FastAPI layer stays thin.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, psutil, pynvml, pydantic-settings, passlib[bcrypt], itsdangerous. Frontend: vanilla JS, CSS custom properties, SVG, Chart.js for sparklines.

**Spec:** `docs/superpowers/specs/2026-05-28-gpu-monitor-redesign-design.md`

---

## File Structure

```
gpu-monitor/
├── monitor.py           # FastAPI app + routes (~180 lines)
├── stats.py             # Pure-function stats collector (~180 lines)
├── auth.py              # Basic auth + token signing (~50 lines)
├── config.py            # pydantic-settings (~30 lines)
├── hash_pw.py           # CLI helper to generate bcrypt hashes (~15 lines)
├── tests/
│   ├── test_stats.py    # stats collector unit tests
│   └── test_auth.py     # auth + token unit tests
├── static/
│   ├── index.html       # markup (~80 lines)
│   ├── style.css        # CSS vars + light/dark + layout (~250 lines)
│   └── app.js           # WS client, render, theme (~280 lines)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

**Pre-existing files left in place:** `monitor_backup.py`, `monitor_v2_backup.py`. The current `monitor.py` is REPLACED.

**Decomposition rationale:** `stats.py` is split out so the data-gathering logic is testable without spinning up FastAPI. `auth.py` is small but isolating it keeps `monitor.py` focused on routing. Frontend is split by responsibility (markup / style / behavior).

---

## Task 0: Project Initialization

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `.env.example`
- Init: git repo (if not already initialized)

- [ ] **Step 1: Initialize git if needed**

Run:
```bash
cd /home/user/gpu-monitor
git rev-parse --git-dir 2>/dev/null || git init
```

- [ ] **Step 2: Write `.gitignore`**

Create `.gitignore`:
```
__pycache__/
*.pyc
*.pyo
.env
.venv/
venv/
.pytest_cache/
*.egg-info/
```

- [ ] **Step 3: Write `requirements.txt`**

Create `requirements.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
psutil==6.0.0
pynvml==11.5.3
pydantic-settings==2.5.2
passlib[bcrypt]==1.7.4
itsdangerous==2.2.0
pytest==8.3.3
httpx==0.27.2
```

- [ ] **Step 4: Write `.env.example`**

Create `.env.example`:
```
# Comma-separated user:bcrypt_hash pairs. Generate hashes with: python hash_pw.py
MONITOR_USERS=admin:$2b$12$REPLACE_ME

# Random string used to sign WebSocket tokens. Generate with: python -c "import secrets;print(secrets.token_urlsafe(48))"
TOKEN_SECRET=REPLACE_ME_LONG_RANDOM

BIND_HOST=0.0.0.0
BIND_PORT=8000
POLL_INTERVAL=2.0
LOG_LEVEL=INFO
```

- [ ] **Step 5: Install deps**

Run:
```bash
pip install -r requirements.txt
```
Expected: All packages install. No errors.

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt .env.example
git commit -m "chore: initial project scaffolding"
```

---

## Task 1: Config Module

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/__init__.py` (empty file). Create `tests/test_config.py`:
```python
import os
from config import Settings


def test_settings_parses_users(monkeypatch):
    monkeypatch.setenv("MONITOR_USERS", "alice:hash1,bob:hash2")
    monkeypatch.setenv("TOKEN_SECRET", "x" * 32)
    s = Settings()
    assert s.users == {"alice": "hash1", "bob": "hash2"}


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("MONITOR_USERS", "u:h")
    monkeypatch.setenv("TOKEN_SECRET", "x" * 32)
    s = Settings()
    assert s.bind_host == "0.0.0.0"
    assert s.bind_port == 8000
    assert s.poll_interval == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `config` module not found.

- [ ] **Step 3: Implement `config.py`**

Create `config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    monitor_users: str
    token_secret: str
    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    poll_interval: float = 2.0
    log_level: str = "INFO"

    @property
    def users(self) -> dict[str, str]:
        out = {}
        for pair in self.monitor_users.split(","):
            if ":" in pair:
                u, h = pair.split(":", 1)
                out[u.strip()] = h.strip()
        return out


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/__init__.py tests/test_config.py
git commit -m "feat: env-based settings via pydantic-settings"
```

---

## Task 2: Auth Module — Bcrypt + Token Signing

**Files:**
- Create: `auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth.py`:
```python
import pytest
from passlib.hash import bcrypt
from auth import verify_user, issue_token, verify_token, TokenInvalid


SECRET = "a" * 48


def test_verify_user_ok():
    h = bcrypt.hash("hunter2")
    assert verify_user("alice", "hunter2", {"alice": h}) is True


def test_verify_user_wrong_password():
    h = bcrypt.hash("hunter2")
    assert verify_user("alice", "wrong", {"alice": h}) is False


def test_verify_user_unknown():
    assert verify_user("nobody", "anything", {"alice": "x"}) is False


def test_token_roundtrip():
    tok = issue_token("alice", SECRET)
    assert verify_token(tok, SECRET, max_age=60) == "alice"


def test_token_bad_secret():
    tok = issue_token("alice", SECRET)
    with pytest.raises(TokenInvalid):
        verify_token(tok, "different" * 8, max_age=60)


def test_token_expired():
    tok = issue_token("alice", SECRET)
    with pytest.raises(TokenInvalid):
        verify_token(tok, SECRET, max_age=-1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `auth` module not found.

- [ ] **Step 3: Implement `auth.py`**

Create `auth.py`:
```python
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired
from passlib.hash import bcrypt


class TokenInvalid(Exception):
    pass


def verify_user(username: str, password: str, users: dict[str, str]) -> bool:
    h = users.get(username)
    if not h:
        return False
    try:
        return bcrypt.verify(password, h)
    except (ValueError, TypeError):
        return False


def issue_token(username: str, secret: str) -> str:
    return TimestampSigner(secret).sign(username.encode()).decode()


def verify_token(token: str, secret: str, max_age: int = 60) -> str:
    signer = TimestampSigner(secret)
    try:
        value = signer.unsign(token, max_age=max_age)
        return value.decode()
    except (BadSignature, SignatureExpired) as e:
        raise TokenInvalid(str(e)) from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add auth.py tests/test_auth.py
git commit -m "feat: bcrypt user verify and signed WS tokens"
```

---

## Task 3: Stats Collector — Pure Functions

**Files:**
- Create: `stats.py`
- Test: `tests/test_stats.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_stats.py`:
```python
from stats import StatsCollector, classify_status


def test_classify_status_ok():
    assert classify_status(cpu=10, ram=20, gpu_vram_max=30, gpu_util_max=40) == "OK"


def test_classify_status_busy():
    assert classify_status(cpu=70, ram=50, gpu_vram_max=50, gpu_util_max=50) == "Busy"


def test_classify_status_overloaded():
    assert classify_status(cpu=95, ram=50, gpu_vram_max=50, gpu_util_max=50) == "Overloaded"


def test_classify_status_overloaded_via_vram():
    assert classify_status(cpu=10, ram=20, gpu_vram_max=95, gpu_util_max=50) == "Overloaded"


def test_collector_produces_frame_with_required_keys():
    c = StatsCollector()
    c.tick()  # warm net delta
    frame = c.tick()
    for key in ("ts", "status", "uptime_s", "cpu", "ram", "swap", "disk", "net", "gpus", "top_procs"):
        assert key in frame, f"missing {key}"
    assert isinstance(frame["cpu"]["total"], (int, float))
    assert isinstance(frame["cpu"]["cores"], list)
    assert isinstance(frame["top_procs"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stats.py -v`
Expected: FAIL — `stats` module not found.

- [ ] **Step 3: Implement `stats.py`**

Create `stats.py`:
```python
import logging
import platform
import time
from typing import Any

import psutil

log = logging.getLogger(__name__)

try:
    import pynvml
    pynvml.nvmlInit()
    NVML_OK = True
except Exception as e:
    log.warning("NVML init failed: %s", e)
    NVML_OK = False


def classify_status(cpu: float, ram: float, gpu_vram_max: float, gpu_util_max: float) -> str:
    if cpu > 90 or ram > 90 or gpu_vram_max > 90:
        return "Overloaded"
    if cpu > 60 or ram > 75 or gpu_util_max > 70:
        return "Busy"
    return "OK"


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def get_system_info() -> dict[str, Any]:
    uname = platform.uname()
    driver = ""
    cuda = ""
    if NVML_OK:
        driver = _safe(lambda: pynvml.nvmlSystemGetDriverVersion(), b"") or b""
        if isinstance(driver, bytes):
            driver = driver.decode()
        cuda_int = _safe(lambda: pynvml.nvmlSystemGetCudaDriverVersion(), 0) or 0
        if cuda_int:
            cuda = f"{cuda_int // 1000}.{(cuda_int % 1000) // 10}"
    return {
        "hostname": uname.node,
        "os": f"{uname.system} {uname.release}",
        "kernel": uname.version,
        "driver": driver,
        "cuda": cuda,
        "nvml_ok": NVML_OK,
    }


class StatsCollector:
    def __init__(self):
        self._last_net_t = time.time()
        self._last_net_sent = 0
        self._last_net_recv = 0
        self._gpu_proc_cache: tuple[float, dict[int, list[dict]]] = (0.0, {})
        self._boot_time = psutil.boot_time()
        psutil.cpu_percent(interval=None, percpu=False)
        psutil.cpu_percent(interval=None, percpu=True)

    def _net(self) -> dict[str, float]:
        n = psutil.net_io_counters()
        now = time.time()
        dt = max(now - self._last_net_t, 0.001)
        first = self._last_net_sent == 0 and self._last_net_recv == 0
        up = (n.bytes_sent - self._last_net_sent) / dt / 1024**2
        down = (n.bytes_recv - self._last_net_recv) / dt / 1024**2
        self._last_net_t = now
        self._last_net_sent = n.bytes_sent
        self._last_net_recv = n.bytes_recv
        if first:
            return {"up_mbs": 0.0, "down_mbs": 0.0}
        return {"up_mbs": round(up, 2), "down_mbs": round(down, 2)}

    def _gpu_procs(self) -> dict[int, list[dict]]:
        now = time.time()
        if now - self._gpu_proc_cache[0] < 5.0:
            return self._gpu_proc_cache[1]
        out: dict[int, list[dict]] = {}
        if NVML_OK:
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                procs = []
                for getter in (pynvml.nvmlDeviceGetComputeRunningProcesses,
                               pynvml.nvmlDeviceGetGraphicsRunningProcesses):
                    for p in _safe(lambda g=getter, hh=h: g(hh), []) or []:
                        pname = _safe(lambda pid=p.pid: psutil.Process(pid).name(), "?")
                        procs.append({"pid": p.pid, "name": pname,
                                      "vram_mb": round((p.usedGpuMemory or 0) / 1024**2)})
                out[i] = procs
        self._gpu_proc_cache = (now, out)
        return out

    def _gpus(self) -> list[dict]:
        if not NVML_OK:
            return []
        procs_by_gpu = self._gpu_procs()
        gpus = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = _safe(lambda: pynvml.nvmlDeviceGetName(h), b"GPU")
            if isinstance(name, bytes):
                name = name.decode()
            u = _safe(lambda: pynvml.nvmlDeviceGetUtilizationRates(h))
            m = _safe(lambda: pynvml.nvmlDeviceGetMemoryInfo(h))
            t = _safe(lambda: pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU), 0)
            pwr = round((_safe(lambda: pynvml.nvmlDeviceGetPowerUsage(h), 0) or 0) / 1000)
            pwr_cap = round((_safe(lambda: pynvml.nvmlDeviceGetEnforcedPowerLimit(h), 0) or 0) / 1000)
            clk = _safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS), 0)
            mclk = _safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM), 0)
            fan = _safe(lambda: pynvml.nvmlDeviceGetFanSpeed(h), 0)
            vram_used = round(m.used / 1024**3, 2) if m else 0
            vram_total = round(m.total / 1024**3, 2) if m else 0
            vram_pct = round(m.used / m.total * 100, 1) if m and m.total else 0
            gpus.append({
                "idx": i, "name": name,
                "util": u.gpu if u else 0, "mem_util": u.memory if u else 0,
                "vram_used": vram_used, "vram_total": vram_total, "vram_pct": vram_pct,
                "temp": t, "power": pwr, "power_cap": pwr_cap,
                "clock": clk, "mem_clock": mclk, "fan": fan,
                "procs": procs_by_gpu.get(i, []),
            })
        return gpus

    def _top_procs(self, limit: int = 10) -> list[dict]:
        rows = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_info"]):
            info = p.info
            rows.append({
                "pid": info["pid"],
                "user": info.get("username") or "",
                "name": info.get("name") or "",
                "cpu": info.get("cpu_percent") or 0.0,
                "mem_mb": round((info["memory_info"].rss if info.get("memory_info") else 0) / 1024**2),
            })
        rows.sort(key=lambda r: r["cpu"], reverse=True)
        return rows[:limit]

    def tick(self) -> dict[str, Any]:
        cpu_total = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
        freq = _safe(psutil.cpu_freq)
        load = _safe(psutil.getloadavg, (0, 0, 0))
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        net = self._net()
        gpus = self._gpus()
        top = self._top_procs()
        vram_max = max((g["vram_pct"] for g in gpus), default=0)
        util_max = max((g["util"] for g in gpus), default=0)
        return {
            "ts": int(time.time()),
            "status": classify_status(cpu_total, ram.percent, vram_max, util_max),
            "uptime_s": int(time.time() - self._boot_time),
            "cpu": {
                "total": round(cpu_total, 1),
                "cores": [round(c, 1) for c in cpu_cores],
                "freq": round(freq.current) if freq else 0,
                "freq_max": round(freq.max) if freq else 0,
                "load": [round(x, 2) for x in load],
                "proc_count": len(psutil.pids()),
            },
            "ram": {
                "used_gb": round(ram.used / 1024**3, 2),
                "total_gb": round(ram.total / 1024**3, 2),
                "pct": ram.percent,
                "cached_gb": round(ram.cached / 1024**3, 2),
                "avail_gb": round(ram.available / 1024**3, 2),
            },
            "swap": {
                "used_gb": round(swap.used / 1024**3, 2),
                "total_gb": round(swap.total / 1024**3, 2),
                "pct": swap.percent,
            },
            "disk": {
                "used_gb": round(disk.used / 1024**3, 1),
                "total_gb": round(disk.total / 1024**3, 1),
                "pct": disk.percent,
            },
            "net": net,
            "gpus": gpus,
            "top_procs": top,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stats.py -v`
Expected: 5 PASSED. (Note: collector tests run against the live system. If no NVIDIA GPU is present, `gpus` will simply be `[]` — test only checks the key exists.)

- [ ] **Step 5: Commit**

```bash
git add stats.py tests/test_stats.py
git commit -m "feat: stats collector with non-blocking sampling and GPU proc map"
```

---

## Task 4: Password Hash CLI Helper

**Files:**
- Create: `hash_pw.py`

- [ ] **Step 1: Write `hash_pw.py`**

Create `hash_pw.py`:
```python
"""Generate a bcrypt hash for MONITOR_USERS entries.

Usage:
    python hash_pw.py
"""
import getpass
from passlib.hash import bcrypt


def main():
    user = input("username: ").strip()
    pw = getpass.getpass("password: ")
    if not user or not pw:
        raise SystemExit("username and password required")
    h = bcrypt.hash(pw)
    print(f"\nAdd this to .env (append to MONITOR_USERS, comma-separated):\n{user}:{h}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test**

Run:
```bash
echo -e "testuser\ntestpw" | python hash_pw.py
```
Expected: prints a line like `testuser:$2b$12$...`

- [ ] **Step 3: Commit**

```bash
git add hash_pw.py
git commit -m "feat: bcrypt hash generator helper"
```

---

## Task 5: FastAPI App — Routes & WebSocket

**Files:**
- Create: `monitor.py` (REPLACES the existing one)
- Test: `tests/test_monitor.py`

- [ ] **Step 1: Back up existing monitor.py**

Run:
```bash
mv monitor.py monitor_v3_backup.py
git add monitor_v3_backup.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_monitor.py`:
```python
import os
import pytest
from passlib.hash import bcrypt
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    h = bcrypt.hash("pw")
    monkeypatch.setenv("MONITOR_USERS", f"alice:{h}")
    monkeypatch.setenv("TOKEN_SECRET", "x" * 48)
    import importlib
    import monitor
    importlib.reload(monitor)
    return TestClient(monitor.app)


def test_root_requires_auth(client):
    r = client.get("/")
    assert r.status_code == 401


def test_root_serves_html(client):
    r = client.get("/", auth=("alice", "pw"))
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_api_system_returns_info_and_token(client):
    r = client.get("/api/system", auth=("alice", "pw"))
    assert r.status_code == 200
    body = r.json()
    assert "hostname" in body
    assert "ws_token" in body
    assert len(body["ws_token"]) > 20


def test_healthz_no_auth(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_system_wrong_password(client):
    r = client.get("/api/system", auth=("alice", "WRONG"))
    assert r.status_code == 401
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_monitor.py -v`
Expected: FAIL — `monitor` module imports old code or doesn't exist.

- [ ] **Step 4: Implement `monitor.py`**

Create `monitor.py`:
```python
import asyncio
import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from auth import TokenInvalid, issue_token, verify_token, verify_user
from config import get_settings
from stats import StatsCollector, get_system_info

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("monitor")

app = FastAPI(title="server.monitor")
security = HTTPBasic()
collector = StatsCollector()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _check(creds: HTTPBasicCredentials = Depends(security)) -> str:
    if not verify_user(creds.username, creds.password, settings.users):
        log.warning("auth failed user=%s", creds.username)
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


@app.get("/")
def root(user: str = Depends(_check)):
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/system")
def api_system(user: str = Depends(_check)):
    info = get_system_info()
    info["ws_token"] = issue_token(user, settings.token_secret)
    return info


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})


@app.websocket("/ws/stats")
async def ws_stats(ws: WebSocket):
    token = ws.query_params.get("token", "")
    try:
        user = verify_token(token, settings.token_secret, max_age=120)
    except TokenInvalid as e:
        log.info("ws auth rejected: %s", e)
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()
    client_addr = ws.client.host if ws.client else "?"
    log.info("ws connect user=%s ip=%s", user, client_addr)
    try:
        while True:
            try:
                frame = collector.tick()
            except Exception:
                log.exception("collector tick failed")
                frame = {"error": "collector_failed"}
            await ws.send_json(frame)
            await asyncio.sleep(settings.poll_interval)
    except WebSocketDisconnect:
        log.info("ws disconnect user=%s ip=%s", user, client_addr)
    except Exception:
        log.exception("ws handler crashed")
        try:
            await ws.close()
        except Exception:
            pass
```

- [ ] **Step 5: Create empty static/index.html so app boots**

Run:
```bash
mkdir -p static
echo "<html><body>placeholder</body></html>" > static/index.html
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_monitor.py -v`
Expected: 5 PASSED.

- [ ] **Step 7: Commit**

```bash
git add monitor.py monitor_v3_backup.py tests/test_monitor.py static/index.html
git commit -m "feat: FastAPI app with token-auth WebSocket and healthz"
```

---

## Task 6: Frontend — index.html Skeleton

**Files:**
- Modify: `static/index.html` (replace placeholder)

- [ ] **Step 1: Write `static/index.html`**

Replace `static/index.html`:
```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>server.monitor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <div class="brand">
      <span class="brand-name">server<span class="accent">.monitor</span></span>
      <span class="sys" id="sys-line">connecting…</span>
    </div>
    <div class="top-right">
      <span id="badge" class="badge badge-ok">● HEALTHY</span>
      <button id="theme-toggle" class="iconbtn" title="Toggle theme" aria-label="Toggle theme">◐</button>
    </div>
  </header>

  <main class="grid">
    <!-- KPI tiles -->
    <section class="kpis">
      <div class="kpi" id="kpi-cpu"><div class="kpi-label">CPU</div><div class="ring-wrap"></div><div class="kpi-spark"></div></div>
      <div class="kpi" id="kpi-gpu"><div class="kpi-label">GPU</div><div class="ring-wrap"></div><div class="kpi-spark"></div></div>
      <div class="kpi" id="kpi-ram"><div class="kpi-label">RAM</div><div class="ring-wrap"></div><div class="kpi-spark"></div></div>
      <div class="kpi" id="kpi-net"><div class="kpi-label">NET</div><div class="kpi-value mono"><span id="kpi-net-val">— MB/s</span></div><div class="kpi-spark"></div></div>
    </section>

    <!-- CPU card -->
    <section class="card cpu-card">
      <div class="card-head"><h2>CPU</h2><span class="card-sub mono" id="cpu-sub">—</span></div>
      <div class="cpu-body">
        <div class="cpu-ring-slot"></div>
        <div class="cpu-meta">
          <div class="kv"><span>Frequency</span><span class="mono" id="cpu-freq">—</span></div>
          <div class="kv"><span>Load 1/5/15m</span><span class="mono" id="cpu-load">—</span></div>
          <div class="kv"><span>Processes</span><span class="mono" id="cpu-procs">—</span></div>
        </div>
      </div>
      <h3 class="subhead">Per-core</h3>
      <div class="cores" id="cores"></div>
    </section>

    <!-- GPU cards container -->
    <section class="gpus" id="gpus"></section>

    <!-- RAM + Disk/Net row -->
    <section class="card mem-card">
      <div class="card-head"><h2>Memory</h2><span class="card-sub mono" id="ram-sub">—</span></div>
      <div class="bar-row"><span class="bar-label">RAM</span><div class="bar"><div class="bar-fill" id="ram-bar"></div></div><span class="bar-val mono" id="ram-pct">—</span></div>
      <div class="bar-row"><span class="bar-label">Swap</span><div class="bar"><div class="bar-fill" id="swap-bar"></div></div><span class="bar-val mono" id="swap-pct">—</span></div>
      <div class="kv-grid">
        <div class="kv"><span>Used</span><span class="mono" id="ram-used">—</span></div>
        <div class="kv"><span>Cached</span><span class="mono" id="ram-cached">—</span></div>
        <div class="kv"><span>Available</span><span class="mono" id="ram-avail">—</span></div>
        <div class="kv"><span>Total</span><span class="mono" id="ram-total">—</span></div>
      </div>
    </section>

    <section class="card net-card">
      <div class="card-head"><h2>Disk &amp; Network</h2></div>
      <div class="bar-row"><span class="bar-label">Disk /</span><div class="bar"><div class="bar-fill" id="disk-bar"></div></div><span class="bar-val mono" id="disk-pct">—</span></div>
      <div class="kv"><span>Disk</span><span class="mono" id="disk-ut">—</span></div>
      <div class="kv"><span>⬇ Download</span><span class="mono accent" id="net-down">—</span></div>
      <div class="kv"><span>⬆ Upload</span><span class="mono" id="net-up">—</span></div>
      <canvas id="net-spark" class="net-spark"></canvas>
    </section>

    <!-- Top procs -->
    <section class="card procs-card">
      <div class="card-head"><h2>Top processes</h2><span class="card-sub">by CPU %</span></div>
      <table class="procs">
        <thead><tr><th>PID</th><th>User</th><th>Name</th><th class="r">CPU %</th><th class="r">MEM MB</th></tr></thead>
        <tbody id="procs-body"></tbody>
      </table>
    </section>
  </main>

  <footer class="foot" id="foot">connecting…</footer>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Smoke test (page loads)**

Run:
```bash
uvicorn monitor:app --port 8000 &
sleep 2
curl -u "alice:pw" -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/
kill %1
```
Expected: `200`. (Replace `alice:pw` with whatever you put in `.env` — if you haven't set `.env` up, create one first using `hash_pw.py`.)

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: dashboard HTML markup"
```

---

## Task 7: Frontend — CSS (variables, themes, layout)

**Files:**
- Create: `static/style.css`

- [ ] **Step 1: Write `static/style.css`**

Create `static/style.css`:
```css
:root {
  --bg: #0a0c10;
  --panel: #11141d;
  --panel-2: #161a26;
  --border: #222838;
  --text: #c7d0e0;
  --text-strong: #e8edf7;
  --dim: #5a6378;
  --green: #3ddc84;
  --amber: #f5c451;
  --red: #ff5c6c;
  --blue: #4d9fff;
  --purple: #b073ff;
  --cyan: #3de0e0;
  --shadow: 0 1px 0 rgba(255,255,255,0.02), 0 8px 24px rgba(0,0,0,0.35);
  --radius: 10px;
  --gap: 1rem;
  --mono: 'JetBrains Mono', ui-monospace, Menlo, monospace;
}
:root[data-theme="light"] {
  --bg: #f4f6fa;
  --panel: #ffffff;
  --panel-2: #f7f8fb;
  --border: #e3e6ec;
  --text: #1a1f2e;
  --text-strong: #0b1020;
  --dim: #6b7280;
  --green: #16a34a;
  --amber: #d97706;
  --red: #dc2626;
  --blue: #2563eb;
  --shadow: 0 1px 0 rgba(0,0,0,0.02), 0 8px 24px rgba(15,23,42,0.06);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg); color: var(--text);
  font-size: 14px; line-height: 1.45;
}
.mono { font-family: var(--mono); }
.accent { color: var(--green); }

.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.9rem 1.25rem;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 10;
}
.brand { display: flex; flex-direction: column; gap: 2px; }
.brand-name { font-weight: 700; letter-spacing: 0.3px; }
.sys { font-size: 0.75rem; color: var(--dim); font-family: var(--mono); }
.top-right { display: flex; align-items: center; gap: 0.7rem; }
.iconbtn {
  background: var(--panel-2); border: 1px solid var(--border); color: var(--text);
  width: 32px; height: 32px; border-radius: 8px; cursor: pointer; font-size: 1rem;
  transition: background 0.15s;
}
.iconbtn:hover { background: var(--border); }

.badge {
  font-size: 0.72rem; font-weight: 600; padding: 0.28rem 0.7rem;
  border-radius: 999px; letter-spacing: 0.5px;
}
.badge-ok    { background: color-mix(in srgb, var(--green) 14%, transparent); color: var(--green);
               border: 1px solid color-mix(in srgb, var(--green) 35%, transparent); }
.badge-busy  { background: color-mix(in srgb, var(--amber) 14%, transparent); color: var(--amber);
               border: 1px solid color-mix(in srgb, var(--amber) 35%, transparent); }
.badge-crit  { background: color-mix(in srgb, var(--red) 14%, transparent); color: var(--red);
               border: 1px solid color-mix(in srgb, var(--red) 35%, transparent); }
.badge-off   { background: color-mix(in srgb, var(--dim) 14%, transparent); color: var(--dim);
               border: 1px solid color-mix(in srgb, var(--dim) 35%, transparent); }

.grid {
  display: grid; gap: var(--gap);
  padding: var(--gap);
  max-width: 1400px; margin: 0 auto;
  grid-template-columns: repeat(12, 1fr);
}
.card {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem 1.1rem;
  box-shadow: var(--shadow);
}
.card.warn  { border-color: color-mix(in srgb, var(--amber) 50%, var(--border)); }
.card.crit  { border-color: color-mix(in srgb, var(--red) 60%, var(--border));
              animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse {
  0%, 100% { box-shadow: var(--shadow); }
  50%      { box-shadow: 0 0 0 3px color-mix(in srgb, var(--red) 22%, transparent), var(--shadow); }
}
.card-head {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: 0.8rem;
}
.card-head h2 { font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--text-strong); }
.card-sub { color: var(--dim); font-size: 0.78rem; }
.subhead { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; color: var(--dim); margin: 1rem 0 0.5rem; }

.kpis { grid-column: span 12; display: grid; gap: var(--gap); grid-template-columns: repeat(4, 1fr); }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, 1fr); } }
.kpi {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1rem; box-shadow: var(--shadow);
  display: grid; grid-template-rows: auto 1fr auto; gap: 0.5rem;
  min-height: 150px;
}
.kpi-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.2px; color: var(--dim); font-weight: 600; }
.kpi-value { font-family: var(--mono); font-size: 1.6rem; font-weight: 700; color: var(--text-strong); }
.kpi-spark { height: 32px; }
.ring-wrap { display: flex; justify-content: center; align-items: center; }

.cpu-card  { grid-column: span 12; }
.cpu-body  { display: grid; grid-template-columns: auto 1fr; gap: 1.5rem; align-items: center; }
.cpu-meta  { display: grid; gap: 0.4rem; }
.cores     { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 0.5rem; }
.core      { font-size: 0.72rem; }
.core-top  { display: flex; justify-content: space-between; color: var(--dim); margin-bottom: 2px; font-family: var(--mono); }
.core-bar  { height: 6px; background: var(--panel-2); border-radius: 3px; overflow: hidden; }
.core-bar > div { height: 100%; transition: width 0.3s ease, background 0.3s; }

.gpus      { grid-column: span 12; display: grid; gap: var(--gap); }
.gpu-card  { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem 1.1rem; box-shadow: var(--shadow); }
.gpu-head  { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.7rem; }
.gpu-name  { color: var(--cyan); font-weight: 700; font-size: 0.85rem; font-family: var(--mono); }
.gpu-head .util-val { font-family: var(--mono); font-weight: 700; }
.gpu-grid  { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.6rem; margin-top: 0.7rem; }
.gpu-cell  { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 0.55rem 0.7rem; }
.gpu-cell .k { font-size: 0.65rem; text-transform: uppercase; color: var(--dim); letter-spacing: 0.8px; }
.gpu-cell .v { font-family: var(--mono); font-weight: 700; margin-top: 2px; }
.gpu-procs { margin-top: 0.7rem; }
.gpu-procs table { width: 100%; font-size: 0.78rem; font-family: var(--mono); border-collapse: collapse; }
.gpu-procs td { padding: 0.2rem 0.4rem; border-top: 1px solid var(--border); }
.gpu-procs td:last-child { text-align: right; }

.mem-card  { grid-column: span 6; }
.net-card  { grid-column: span 6; }
@media (max-width: 900px) { .mem-card, .net-card { grid-column: span 12; } }
.bar-row { display: grid; grid-template-columns: 64px 1fr 56px; gap: 0.7rem; align-items: center; margin: 0.4rem 0; }
.bar-label { font-size: 0.74rem; color: var(--dim); }
.bar { height: 8px; background: var(--panel-2); border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; width: 0%; transition: width 0.4s ease, background 0.4s; }
.bar-val { font-family: var(--mono); font-size: 0.82rem; text-align: right; }
.kv      { display: flex; justify-content: space-between; padding: 0.3rem 0; border-bottom: 1px dashed var(--border); font-size: 0.82rem; }
.kv:last-child { border-bottom: none; }
.kv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 1rem; margin-top: 0.4rem; }
.net-spark { width: 100%; height: 80px; margin-top: 0.7rem; }

.procs-card { grid-column: span 12; }
table.procs { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
table.procs th, table.procs td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); text-align: left; }
table.procs th { font-size: 0.7rem; text-transform: uppercase; color: var(--dim); letter-spacing: 1px; font-weight: 600; }
table.procs td.mono, table.procs th.r { font-family: var(--mono); }
table.procs th.r, table.procs td.r { text-align: right; }

.foot { text-align: center; color: var(--dim); font-size: 0.72rem; padding: 0.8rem; }

.color-ok   { color: var(--green); }
.color-warn { color: var(--amber); }
.color-crit { color: var(--red); }
.fill-ok    { background: var(--green); }
.fill-warn  { background: var(--amber); }
.fill-crit  { background: var(--red); }
```

- [ ] **Step 2: Commit**

```bash
git add static/style.css
git commit -m "feat: dashboard CSS with light/dark themes"
```

---

## Task 8: Frontend — app.js (WS client, render, theme, sparklines)

**Files:**
- Create: `static/app.js`

- [ ] **Step 1: Write `static/app.js`**

Create `static/app.js`:
```javascript
(function () {
  const SPARK_LEN = 60;
  const charts = {};
  let netChart = null;
  let ws = null;
  let backoff = 1000;
  let gpusBuilt = false;
  let gpuCount = 0;

  // ---------------- helpers ----------------
  const $ = (id) => document.getElementById(id);
  const fmtUptime = (s) => {
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${d}d ${h}h ${m}m`;
  };
  const classFor = (pct) => (pct < 60 ? "ok" : pct < 85 ? "warn" : "crit");
  const hexFor = (pct, vars) => {
    const v = getComputedStyle(document.documentElement);
    return pct < 60 ? v.getPropertyValue("--green").trim()
         : pct < 85 ? v.getPropertyValue("--amber").trim()
         :            v.getPropertyValue("--red").trim();
  };

  // Number tween: smoothly animate text content
  const tweens = new Map();
  function tween(el, to, fmt = (v) => v.toFixed(1)) {
    if (!el) return;
    const from = tweens.get(el) ?? to;
    const start = performance.now();
    const dur = 200;
    function step(t) {
      const k = Math.min(1, (t - start) / dur);
      const cur = from + (to - from) * k;
      el.textContent = fmt(cur);
      if (k < 1) requestAnimationFrame(step);
      else tweens.set(el, to);
    }
    requestAnimationFrame(step);
  }

  // ---------------- SVG ring ----------------
  function ensureRing(parent, id, size = 110) {
    let svg = parent.querySelector("svg");
    if (svg) return svg;
    const ns = "http://www.w3.org/2000/svg";
    svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.classList.add("ring");
    const cx = size / 2, cy = size / 2, r = size / 2 - 10;
    const bg = document.createElementNS(ns, "circle");
    bg.setAttribute("cx", cx); bg.setAttribute("cy", cy); bg.setAttribute("r", r);
    bg.setAttribute("fill", "none");
    bg.setAttribute("stroke", "var(--panel-2)");
    bg.setAttribute("stroke-width", "10");
    const fg = document.createElementNS(ns, "circle");
    fg.setAttribute("cx", cx); fg.setAttribute("cy", cy); fg.setAttribute("r", r);
    fg.setAttribute("fill", "none");
    fg.setAttribute("stroke", "var(--green)");
    fg.setAttribute("stroke-width", "10");
    fg.setAttribute("stroke-linecap", "round");
    fg.setAttribute("transform", `rotate(-90 ${cx} ${cy})`);
    const C = 2 * Math.PI * r;
    fg.setAttribute("stroke-dasharray", C);
    fg.setAttribute("stroke-dashoffset", C);
    fg.style.transition = "stroke-dashoffset 0.4s ease, stroke 0.3s";
    fg.dataset.c = C;
    fg.classList.add("ring-fg");
    const txt = document.createElementNS(ns, "text");
    txt.setAttribute("x", cx); txt.setAttribute("y", cy + 5);
    txt.setAttribute("text-anchor", "middle");
    txt.setAttribute("fill", "currentColor");
    txt.setAttribute("font-family", "JetBrains Mono, ui-monospace, monospace");
    txt.setAttribute("font-size", "20");
    txt.setAttribute("font-weight", "700");
    txt.textContent = "0%";
    txt.classList.add("ring-text");
    svg.appendChild(bg); svg.appendChild(fg); svg.appendChild(txt);
    parent.appendChild(svg);
    return svg;
  }
  function setRing(svg, pct) {
    if (!svg) return;
    const fg = svg.querySelector(".ring-fg");
    const txt = svg.querySelector(".ring-text");
    const C = parseFloat(fg.dataset.c);
    fg.setAttribute("stroke-dashoffset", C * (1 - pct / 100));
    const cl = classFor(pct);
    fg.setAttribute("stroke", cl === "ok" ? "var(--green)" : cl === "warn" ? "var(--amber)" : "var(--red)");
    txt.textContent = Math.round(pct) + "%";
  }

  // ---------------- sparklines ----------------
  function makeSpark(parent, color) {
    let canvas = parent.querySelector("canvas");
    if (!canvas) {
      canvas = document.createElement("canvas");
      parent.appendChild(canvas);
    }
    return new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: Array(SPARK_LEN).fill(""),
        datasets: [{
          data: Array(SPARK_LEN).fill(0),
          borderColor: color, backgroundColor: color + "22",
          fill: true, tension: 0.35, pointRadius: 0, borderWidth: 1.5,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false, min: 0, max: 100 } },
      },
    });
  }
  function pushSpark(c, v) {
    if (!c) return;
    c.data.datasets[0].data.push(v);
    c.data.datasets[0].data.shift();
    c.update("none");
  }

  // ---------------- bar ----------------
  function setBar(id, pct, pctId) {
    const fill = $(id);
    if (fill) {
      fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
      fill.className = "bar-fill fill-" + classFor(pct);
    }
    if (pctId) {
      const el = $(pctId);
      if (el) el.textContent = Math.round(pct) + "%";
    }
  }

  // ---------------- GPU cards ----------------
  function buildGpus(gpus) {
    const root = $("gpus");
    root.innerHTML = gpus.map((g, i) => `
      <article class="card gpu-card" id="gpu-${i}">
        <div class="gpu-head">
          <span class="gpu-name">▸ GPU${i}  ${g.name}</span>
          <span class="util-val" id="g${i}-util">0%</span>
        </div>
        <div class="bar-row"><span class="bar-label">Util</span><div class="bar"><div class="bar-fill" id="g${i}-ubar"></div></div><span class="bar-val mono" id="g${i}-upct">—</span></div>
        <div class="bar-row"><span class="bar-label">VRAM</span><div class="bar"><div class="bar-fill" id="g${i}-vbar"></div></div><span class="bar-val mono" id="g${i}-vpct">—</span></div>
        <div class="gpu-grid">
          <div class="gpu-cell"><div class="k">Temp</div><div class="v" id="g${i}-temp">—</div></div>
          <div class="gpu-cell"><div class="k">Power</div><div class="v" id="g${i}-pwr">—</div></div>
          <div class="gpu-cell"><div class="k">Core Clk</div><div class="v" id="g${i}-clk">—</div></div>
          <div class="gpu-cell"><div class="k">Mem Clk</div><div class="v" id="g${i}-mclk">—</div></div>
          <div class="gpu-cell"><div class="k">Fan</div><div class="v" id="g${i}-fan">—</div></div>
          <div class="gpu-cell"><div class="k">VRAM</div><div class="v" id="g${i}-vraw">—</div></div>
        </div>
        <div class="gpu-procs">
          <h3 class="subhead">Processes</h3>
          <table><tbody id="g${i}-procs"></tbody></table>
        </div>
      </article>`).join("");
    gpusBuilt = true;
    gpuCount = gpus.length;
  }

  function renderGpu(i, g) {
    setBar(`g${i}-ubar`, g.util, `g${i}-upct`);
    setBar(`g${i}-vbar`, g.vram_pct, `g${i}-vpct`);
    $(`g${i}-util`).textContent = g.util + "%";
    $(`g${i}-util`).className = "util-val color-" + classFor(g.util);
    $(`g${i}-temp`).textContent = g.temp + "°C";
    $(`g${i}-temp`).className = "v color-" + (g.temp < 70 ? "ok" : g.temp < 85 ? "warn" : "crit");
    $(`g${i}-pwr`).textContent = `${g.power}/${g.power_cap} W`;
    $(`g${i}-clk`).textContent = g.clock + " MHz";
    $(`g${i}-mclk`).textContent = g.mem_clock + " MHz";
    $(`g${i}-fan`).textContent = g.fan + "%";
    $(`g${i}-vraw`).textContent = `${g.vram_used}/${g.vram_total} GB`;
    const card = $(`gpu-${i}`);
    if (card) {
      card.classList.remove("warn", "crit");
      if (g.temp >= 85 || g.vram_pct >= 90) card.classList.add("crit");
      else if (g.temp >= 75 || g.vram_pct >= 75) card.classList.add("warn");
    }
    const procs = $(`g${i}-procs`);
    if (procs) {
      procs.innerHTML = (g.procs || []).slice(0, 5).map(p =>
        `<tr><td>${p.pid}</td><td>${escape(p.name)}</td><td>${p.vram_mb} MB</td></tr>`).join("")
        || `<tr><td colspan="3" style="color:var(--dim)">—</td></tr>`;
    }
  }

  function escape(s) {
    return String(s).replace(/[<>&"']/g, c => ({
      "<": "&lt;", ">": "&gt;", "&": "&amp;", "\"": "&quot;", "'": "&#39;"
    }[c]));
  }

  // ---------------- frame render ----------------
  function render(d) {
    // badge
    const badge = $("badge");
    const map = { OK: "ok", Busy: "busy", Overloaded: "crit" };
    badge.className = "badge badge-" + (map[d.status] || "ok");
    badge.textContent = "● " + (d.status || "").toUpperCase();

    // KPI rings
    setRing(charts.cpuRing, d.cpu.total);
    setRing(charts.ramRing, d.ram.pct);
    const gpuMax = d.gpus.length ? Math.max(...d.gpus.map(g => g.util)) : 0;
    setRing(charts.gpuRing, gpuMax);
    $("kpi-net-val").textContent = `↓${d.net.down_mbs} ↑${d.net.up_mbs} MB/s`;

    // KPI sparklines
    pushSpark(charts.cpuSpark, d.cpu.total);
    pushSpark(charts.ramSpark, d.ram.pct);
    pushSpark(charts.gpuSpark, gpuMax);
    if (charts.netSpark) {
      const ds = charts.netSpark.data.datasets;
      ds[0].data.push(d.net.down_mbs); ds[0].data.shift();
      ds[1].data.push(d.net.up_mbs);   ds[1].data.shift();
      charts.netSpark.update("none");
    }

    // CPU detail
    $("cpu-sub").textContent = `${d.cpu.total.toFixed(1)}%`;
    $("cpu-freq").textContent = `${d.cpu.freq} / ${d.cpu.freq_max} MHz`;
    $("cpu-load").textContent = d.cpu.load.join("  ");
    $("cpu-procs").textContent = d.cpu.proc_count;
    setRing(charts.cpuBigRing, d.cpu.total);
    $("cores").innerHTML = d.cpu.cores.map((c, i) =>
      `<div class="core">
         <div class="core-top"><span>CPU${i}</span><span>${c.toFixed(0)}%</span></div>
         <div class="core-bar"><div class="fill-${classFor(c)}" style="width:${c}%"></div></div>
       </div>`).join("");

    // GPUs
    if (!gpusBuilt || gpuCount !== d.gpus.length) buildGpus(d.gpus);
    d.gpus.forEach((g, i) => renderGpu(i, g));

    // RAM + Swap
    $("ram-sub").textContent = `${d.ram.used_gb} / ${d.ram.total_gb} GB`;
    setBar("ram-bar", d.ram.pct, "ram-pct");
    setBar("swap-bar", d.swap.pct, "swap-pct");
    $("ram-used").textContent   = d.ram.used_gb + " GB";
    $("ram-cached").textContent = d.ram.cached_gb + " GB";
    $("ram-avail").textContent  = d.ram.avail_gb + " GB";
    $("ram-total").textContent  = d.ram.total_gb + " GB";

    // Disk + Net
    setBar("disk-bar", d.disk.pct, "disk-pct");
    $("disk-ut").textContent = `${d.disk.used_gb} / ${d.disk.total_gb} GB`;
    $("net-down").textContent = d.net.down_mbs + " MB/s";
    $("net-up").textContent   = d.net.up_mbs + " MB/s";

    // top procs
    $("procs-body").innerHTML = (d.top_procs || []).map(p =>
      `<tr>
         <td class="mono">${p.pid}</td>
         <td>${escape(p.user)}</td>
         <td>${escape(p.name)}</td>
         <td class="r">${p.cpu.toFixed(1)}</td>
         <td class="r">${p.mem_mb}</td>
       </tr>`).join("");

    // footer
    $("foot").textContent =
      `last update ${new Date(d.ts * 1000).toLocaleTimeString()} · push ${d.uptime_s ? "ok" : "ok"}`;
  }

  // ---------------- websocket ----------------
  async function connect() {
    try {
      const sys = await fetch("/api/system", { credentials: "include" }).then(r => {
        if (!r.ok) throw new Error("auth");
        return r.json();
      });
      $("sys-line").textContent =
        `${sys.hostname} · ${sys.os} · kernel ${sys.kernel || "?"} · NVIDIA ${sys.driver || "—"} · CUDA ${sys.cuda || "—"}`;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${location.host}/ws/stats?token=${encodeURIComponent(sys.ws_token)}`;
      ws = new WebSocket(url);
      ws.onopen = () => { backoff = 1000; };
      ws.onmessage = (e) => {
        try { render(JSON.parse(e.data)); } catch (err) { console.error(err); }
      };
      ws.onclose = scheduleReconnect;
      ws.onerror = () => { try { ws.close(); } catch {} };
    } catch (e) {
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    const badge = $("badge");
    if (badge) { badge.className = "badge badge-off"; badge.textContent = "● OFFLINE"; }
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 10000);
  }

  // ---------------- theme ----------------
  function initTheme() {
    const saved = localStorage.getItem("theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    $("theme-toggle").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
    });
  }

  // ---------------- init ----------------
  window.addEventListener("load", () => {
    initTheme();
    // KPI rings + sparks
    charts.cpuRing = ensureRing($("kpi-cpu").querySelector(".ring-wrap"), "kpi-cpu-ring", 110);
    charts.gpuRing = ensureRing($("kpi-gpu").querySelector(".ring-wrap"), "kpi-gpu-ring", 110);
    charts.ramRing = ensureRing($("kpi-ram").querySelector(".ring-wrap"), "kpi-ram-ring", 110);
    charts.cpuSpark = makeSpark($("kpi-cpu").querySelector(".kpi-spark"), getComputedStyle(document.documentElement).getPropertyValue("--blue").trim() || "#4d9fff");
    charts.gpuSpark = makeSpark($("kpi-gpu").querySelector(".kpi-spark"), getComputedStyle(document.documentElement).getPropertyValue("--cyan").trim() || "#3de0e0");
    charts.ramSpark = makeSpark($("kpi-ram").querySelector(".kpi-spark"), getComputedStyle(document.documentElement).getPropertyValue("--purple").trim() || "#b073ff");
    charts.netSpark = (() => {
      const canvas = $("net-spark");
      return new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
          labels: Array(SPARK_LEN).fill(""),
          datasets: [
            { data: Array(SPARK_LEN).fill(0), borderColor: "#3ddc84", backgroundColor: "#3ddc8422", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 1.5 },
            { data: Array(SPARK_LEN).fill(0), borderColor: "#4d9fff", backgroundColor: "#4d9fff22", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 1.5 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { display: false } },
          scales: { x: { display: false }, y: { display: false, min: 0 } },
        },
      });
    })();
    // KPI net tile shows a sparkline too — reuse smaller chart in tile
    charts.netKpiSpark = makeSpark($("kpi-net").querySelector(".kpi-spark"), getComputedStyle(document.documentElement).getPropertyValue("--green").trim() || "#3ddc84");
    // Big CPU ring in the CPU card
    charts.cpuBigRing = ensureRing(document.querySelector(".cpu-ring-slot"), "cpu-big-ring", 140);

    connect();
  });
})();
```

- [ ] **Step 2: Manual smoke test**

Ensure `.env` has a real user. Generate one if needed:
```bash
python hash_pw.py  # follow prompts, paste output into MONITOR_USERS in .env
# also set TOKEN_SECRET
python -c "import secrets;print(secrets.token_urlsafe(48))"  # paste into .env
```
Run:
```bash
uvicorn monitor:app --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000/` in a browser, login. Confirm:
- Header shows hostname + OS + driver.
- KPI rings animate.
- CPU card shows per-core bars.
- GPU card appears (if NVIDIA GPU available).
- Top processes table populates.
- Theme toggle flips dark ↔ light and persists on reload.
- Kill the server → badge becomes OFFLINE; restart → reconnects.

- [ ] **Step 3: Commit**

```bash
git add static/app.js
git commit -m "feat: dashboard client (WS, rings, sparklines, theme, reconnect)"
```

---

## Task 9: README & Production Notes

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

Create `README.md`:
```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with quickstart, systemd, Caddy"
```

---

## Task 10: Final Verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: All tests pass (config: 2, auth: 6, stats: 5, monitor: 5).

- [ ] **Step 2: Manual end-to-end check**

Start the server:
```bash
uvicorn monitor:app --host 127.0.0.1 --port 8000
```

In a separate terminal:
```bash
curl -s http://127.0.0.1:8000/healthz | python -m json.tool
# expect {"status":"ok"}

curl -u "<user>:<pw>" -s http://127.0.0.1:8000/api/system | python -m json.tool
# expect hostname, os, kernel, driver, cuda, nvml_ok, ws_token
```

Open the dashboard in browser. Confirm:
1. Login works.
2. All KPI tiles populate within 4s.
3. GPU card shows live data matching `nvidia-smi`.
4. Top processes table updates and matches `top -bn1`.
5. Theme toggle persists across reload.
6. Stop server → badge flips OFFLINE within 2s → restart → reconnects within 10s.
7. `pkill -STOP` on a process should NOT crash the page (psutil handles).

- [ ] **Step 3: Tag the release**

```bash
git tag -a v1.0.0 -m "Production redesign"
git log --oneline | head -20
```

---

## Self-Review Notes

- All spec requirements covered: WebSocket transport (Task 5), env-based bcrypt auth (Tasks 1–2), stats collector with proc list + GPU procs (Task 3), hybrid visual style + theme toggle (Tasks 7–8), top processes table (Tasks 6–8), system info header (Tasks 5–8), healthz (Task 5), pulse on threshold (Tasks 7–8).
- No placeholders, no "TBD", no "similar to" cross-refs without code.
- Type/name consistency checked: `tick()`, `get_system_info()`, `verify_user()`, `issue_token()`, `verify_token()`, `TokenInvalid` all referenced consistently across tasks.
- Single-implementation-pass scope: ~900 lines of code across 8 files, plus tests. One developer / one session.
