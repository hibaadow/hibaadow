"""Authentication, sessions, RBAC, CSRF defence and rate limiting."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, User

COOKIE = "atlas_session"
ROLES = {"viewer": 0, "trader": 1, "admin": 2}
MAX_FAILED = 5
LOCK_MINUTES = 15


def hash_password(pw: str) -> str:
    if len(pw) < 10:
        raise ValueError("password must be at least 10 characters")
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def issue_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {"sub": user.username, "role": user.role, "ver": user.session_version, "iat": now,
              "exp": now + timedelta(minutes=s.session_ttl_minutes)}
    return jwt.encode(claims, s.secret_key.get_secret_value(), algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    claims = decode_token(token)
    if not claims:
        return None
    user = db.query(User).filter_by(username=claims.get("sub")).one_or_none()
    if user is None or user.session_version != claims.get("ver"):
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    # CSRF: state-changing requests must carry a custom header (cannot be set cross-site without CORS approval)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-atlas-client") != "web":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing CSRF header")
    return user


def require(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLES.get(user.role, -1) < ROLES[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role} role required")
        return user

    return dep


def audit(db: Session, user: User | None, action: str, target: str | None = None, details: dict | None = None,
          request: Request | None = None) -> None:
    from .logging import redact

    db.add(AuditLog(username=user.username if user else None, action=action, target=target, details=redact(details or {}),
                    ip=client_ip(request) if request else None))


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding-window limiter. In-memory per process (use a shared store behind multiple API replicas)."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self.hits) > 50_000:
            self.hits.clear()
        return True


limiter = RateLimiter()


def login(db: Session, username: str, password: str) -> User:
    user = db.query(User).filter_by(username=username).one_or_none()
    now = datetime.now(timezone.utc)
    if user is None:
        bcrypt.checkpw(b"timing-equaliser", bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4)))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    locked = user.locked_until
    if locked is not None and locked.tzinfo is None:
        locked = locked.replace(tzinfo=timezone.utc)
    if locked and locked > now:
        raise HTTPException(status.HTTP_423_LOCKED, "account temporarily locked after repeated failures")
    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_FAILED:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = now
    return user


def ensure_admin(db: Session) -> str | None:
    """Create the first admin from ATLAS_ADMIN_PASSWORD if no users exist."""
    if db.query(User).count():
        return None
    s = get_settings()
    if not s.admin_password:
        return "no users exist: set ATLAS_ADMIN_PASSWORD or run `python -m atlas.cli create-user`"
    db.add(User(username=s.admin_username, password_hash=hash_password(s.admin_password.get_secret_value()), role="admin"))
    return f"bootstrap admin '{s.admin_username}' created"
