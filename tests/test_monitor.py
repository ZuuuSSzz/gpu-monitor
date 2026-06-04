import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import importlib
    import monitor
    importlib.reload(monitor)
    return TestClient(monitor.app)


def test_root_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_api_system_returns_info(client):
    r = client.get("/api/system")
    assert r.status_code == 200
    body = r.json()
    assert "hostname" in body
    assert "ws_token" not in body


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ws_stats_streams_a_frame(client):
    with client.websocket_connect("/ws/stats") as ws:
        frame = ws.receive_json()
        for key in ("ts", "status", "cpu", "ram", "gpus", "top_procs"):
            assert key in frame
