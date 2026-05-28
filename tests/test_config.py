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


def test_settings_users_skips_malformed_entries(monkeypatch):
    """Malformed entries (missing colon, empty username) are silently skipped.

    Intentional: a typo in .env should not crash startup. Operators still get
    a clear "Unauthorized" response when they try to log in.
    """
    monkeypatch.setenv("MONITOR_USERS", "alice:h1,no_colon,:empty_user,bob:h2")
    monkeypatch.setenv("TOKEN_SECRET", "x" * 32)
    s = Settings()
    assert s.users == {"alice": "h1", "": "empty_user", "bob": "h2"}
