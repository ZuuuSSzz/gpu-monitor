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
