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
