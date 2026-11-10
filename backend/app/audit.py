"""Append-only, tamper-evident audit log.

Each event stores an HMAC over its own content and the previous event's hash, so editing,
removing or reordering any past row breaks every link after it. Database triggers reject
UPDATE and DELETE outright. The HMAC key is kept outside the database, so someone holding only
the database file cannot recompute the chain.

The chain cannot detect removal of the newest rows on its own: compare /api/audit/verify's
head hash with a copy kept elsewhere if that threat matters.
"""

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import vault
from .db import read_session
from .models import AuditEvent, now_iso

GENESIS = "0" * 64


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(payload))


def _event_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hmac.new(vault.audit_key(), (prev_hash + canonical_json(fields)).encode(), hashlib.sha256).hexdigest()


def _hashed_fields(e: AuditEvent) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "ts": e.ts,
        "actor_type": e.actor_type,
        "actor": e.actor,
        "action": e.action,
        "subject_type": e.subject_type,
        "subject_id": e.subject_id,
        "requirement_id": e.requirement_id,
        "data": e.data,
    }


def record(
    session: Session,
    *,
    actor_type: str,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    requirement_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an event in the caller's transaction, so state and audit commit together."""
    if not session.info.get("write_tx"):
        raise RuntimeError("audit.record must run inside write_tx()")
    session.flush()
    tail = session.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
    event = AuditEvent(
        seq=(tail.seq + 1) if tail else 1,
        ts=now_iso(),
        actor_type=actor_type,
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        requirement_id=requirement_id,
        data=data or {},
        prev_hash=tail.hash if tail else GENESIS,
        hash="",
    )
    event.hash = _event_hash(event.prev_hash, _hashed_fields(event))
    session.add(event)
    session.flush()
    return event


def verify_chain() -> dict[str, Any]:
    expected_prev = GENESIS
    expected_seq = 1
    checked = 0
    with read_session() as session:
        rows = session.scalars(select(AuditEvent).order_by(AuditEvent.seq)).yield_per(500)
        for e in rows:
            problem = None
            if e.seq != expected_seq:
                problem = f"expected event {expected_seq}, found {e.seq}: events are missing"
            elif e.prev_hash != expected_prev:
                problem = "link to the previous event does not match"
            elif not hmac.compare_digest(e.hash, _event_hash(e.prev_hash, _hashed_fields(e))):
                problem = "event content does not match its hash"
            if problem:
                return {
                    "ok": False,
                    "checked": checked,
                    "first_bad_seq": e.seq,
                    "reason": problem,
                    "head": None,
                }
            expected_prev = e.hash
            expected_seq += 1
            checked += 1
    return {"ok": True, "checked": checked, "first_bad_seq": None, "reason": None,
            "head": expected_prev if checked else None}


def event_dict(e: AuditEvent) -> dict[str, Any]:
    return {**_hashed_fields(e), "prev_hash": e.prev_hash, "hash": e.hash}
