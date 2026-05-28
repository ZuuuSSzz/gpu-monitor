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
