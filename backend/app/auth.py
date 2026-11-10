"""Accounts and sessions. The name on every human audit event comes from the session, never
from anything the client sends."""

import hashlib
import hmac
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select

from . import audit
from .db import read_session, write_tx
from .models import Session as LoginSession
from .models import User

SESSION_DAYS = 30
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 300

_bearer = HTTPBearer(auto_error=False)
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def _password_matches(password: str, stored: str) -> bool:
    salt = bytes.fromhex(stored.split("$")[0])
    return hmac.compare_digest(hash_password(password, salt), stored)


def has_users() -> bool:
    with read_session() as s:
        return bool(s.scalar(select(func.count()).select_from(User)))


def _throttled(name: str) -> bool:
    now = time.monotonic()
    with _failures_lock:
        recent = [t for t in _failures.get(name, []) if now - t < FAILURE_WINDOW_SECONDS]
        _failures[name] = recent
        return len(recent) >= MAX_FAILURES


def _note_failure(name: str) -> None:
    with _failures_lock:
        _failures.setdefault(name, []).append(time.monotonic())


def verify_login(name: str, password: str) -> str:
    key = name.strip().lower()
    if _throttled(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait 5 minutes.")
    with read_session() as s:
        user = s.scalar(select(User).where(func.lower(User.name) == key))
    if user is None or not _password_matches(password, user.password_hash):
        _note_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong name or password")
    return user.name


def change_password(name: str, current: str, new: str, keep_token: str) -> None:
    """Verifying the current password means a stolen session cannot take over the account."""
    key = name.strip().lower()
    if _throttled(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait 5 minutes.")
    with read_session() as s:
        user = s.scalar(select(User).where(User.name == name))
    if user is None or not _password_matches(current, user.password_hash):
        _note_failure(key)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your current password is not correct")
    password_hash = hash_password(new)
    with write_tx() as s:
        s.get(User, user.id).password_hash = password_hash
        s.execute(
            delete(LoginSession).where(
                LoginSession.user_name == name,
                LoginSession.token_hash != _token_hash(keep_token),
            )
        )
        audit.record(
            s, actor_type="human", actor=name, action="auth.password_changed",
            subject_type="user", subject_id=name,
        )


def remove_user(name: str, removed_by: str) -> None:
    if name == removed_by:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove your own account")
    with write_tx() as s:
        user = s.scalar(select(User).where(User.name == name))
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such approver")
        s.delete(user)
        s.execute(delete(LoginSession).where(LoginSession.user_name == name))
        audit.record(
            s, actor_type="human", actor=removed_by, action="user.removed",
            subject_type="user", subject_id=name,
        )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(name: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
    with write_tx() as s:
        s.add(LoginSession(token_hash=_token_hash(token), user_name=name,
                           expires_at=expires.isoformat()))
    return token


def end_session(token: str) -> None:
    with write_tx() as s:
        row = s.get(LoginSession, _token_hash(token))
        if row:
            s.delete(row)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if creds:
        with read_session() as s:
            row = s.get(LoginSession, _token_hash(creds.credentials))
        if row and datetime.fromisoformat(row.expires_at) > datetime.now(UTC):
            return row.user_name
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in")
