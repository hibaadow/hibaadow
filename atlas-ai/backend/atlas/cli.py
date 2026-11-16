"""Admin CLI.

    python -m atlas.cli init-db
    python -m atlas.cli create-user <username> --role admin|trader|viewer   (prompts for password)
"""
from __future__ import annotations

import argparse
import getpass
import sys

from .db import init_db, session_scope
from .models import User
from .security import hash_password


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="atlas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    cu = sub.add_parser("create-user")
    cu.add_argument("username")
    cu.add_argument("--role", default="trader", choices=["admin", "trader", "viewer"])
    cu.add_argument("--password-stdin", action="store_true", help="read password from stdin (for automation)")
    a = ap.parse_args(argv)
    init_db()
    if a.cmd == "init-db":
        print("database initialised")
        return 0
    pw = sys.stdin.readline().rstrip("\n") if a.password_stdin else getpass.getpass("password (min 10 chars): ")
    with session_scope() as db:
        u = db.query(User).filter_by(username=a.username).one_or_none()
        if u:
            u.password_hash = hash_password(pw)
            u.role = a.role
            u.session_version += 1
            print(f"updated {a.username} ({a.role})")
        else:
            db.add(User(username=a.username, password_hash=hash_password(pw), role=a.role))
            print(f"created {a.username} ({a.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
