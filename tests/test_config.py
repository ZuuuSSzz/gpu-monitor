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
