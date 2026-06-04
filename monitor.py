import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import get_settings
from stats import StatsCollector, get_system_info

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("monitor")

app = FastAPI(title="server.monitor")
collector = StatsCollector()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/system")
def api_system():
    return get_system_info()


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})


@app.websocket("/ws/stats")
async def ws_stats(ws: WebSocket):
    await ws.accept()
    client_addr = ws.client.host if ws.client else "?"
    log.info("ws connect ip=%s", client_addr)
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
        log.info("ws disconnect ip=%s", client_addr)
    except Exception:
        log.exception("ws handler crashed")
        try:
            await ws.close()
        except Exception:
            pass
