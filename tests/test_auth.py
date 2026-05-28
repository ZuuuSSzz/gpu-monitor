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
