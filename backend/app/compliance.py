"""Evidence pack for audits such as SOC 2: a signed ZIP drawn from the audit trail.

This gathers evidence and runs a few objective checks. It does not certify anything: whether a
control is met is for your auditor to decide.
"""

import csv
import hashlib
import hmac
import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from . import audit, vault
from .db import read_session
from .models import AuditEvent, Proposal, Requirement, Task, now_iso

ACCESS_PREFIXES = ("auth.", "user.", "setup.", "settings.")
HIGH_RISK = "high"
WRITE_ACTIONS = ("github.pr_opened", "github.review_posted")

CONTROL_MAP = {
    "CC6.1 Logical access": ["access_log.csv"],
    "CC6.2-6.3 Access provisioning and removal": ["access_log.csv"],
    "CC7.2 Monitoring of activity": ["audit_events.jsonl"],
    "CC8.1 Change management": ["decisions.csv", "github_writes.csv", "control_checks.json"],
}

README = """Countersign evidence pack

Files
  summary.json        Period, counts, and audit chain verification
  control_checks.json Objective checks, with any exceptions listed
  decisions.csv       Every human decision on an agent proposal
  github_writes.csv   Every write to GitHub, and who approved it
  access_log.csv      Sign-ins, account changes and credential changes
  audit_events.jsonl  The raw tamper-evident events for the period
  manifest.json       SHA-256 of each file, signed by this deployment

Verifying
  Compare each file's SHA-256 with manifest.json. The signature is an HMAC made with this
  deployment's audit key, so only someone holding that key can check it.

Limits
  This pack is evidence to support an audit. It is not a certification. The control mapping in
  summary.json is a suggested starting point: confirm it with your auditor.
  Records cover what happened inside Countersign, not merges or changes made directly on GitHub.
"""


def _safe_cell(value: Any) -> Any:
    """Agent text and ticket titles reach these files. A spreadsheet must not run them."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _csv(headers: list[str], rows: list[list[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows([[_safe_cell(v) for v in row] for row in rows])
    return buffer.getvalue().encode()


def _bounds(start: str, end: str) -> tuple[str, str]:
    first = datetime.fromisoformat(start).replace(tzinfo=UTC)
    last = datetime.fromisoformat(end).replace(
        tzinfo=UTC, hour=23, minute=59, second=59, microsecond=999000
    )
    return (first.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            last.isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def _control_checks(
    events: list[AuditEvent], proposals: list[Proposal], written: dict[str, Proposal],
    filed_by: dict[str, str],
) -> list[dict[str, Any]]:
    by_id = written  # a write can fall in the period when its approval fell just before it
    writes = [e for e in events if e.action in WRITE_ACTIONS]
    unapproved = [
        e.subject_id for e in writes
        if (p := by_id.get(e.subject_id)) is None or not p.decided_by
        or e.data.get("payload_hash") != p.payload_hash
    ]
    self_approved = [
        p.id for p in proposals
        if p.decided_by and p.requirement_id
        and p.decided_by == filed_by.get(p.requirement_id)
        and p.status in ("approved", "executed", "failed")
    ]
    risky = [
        p.id for p in proposals
        if p.decided_by and any(f["level"] == HIGH_RISK for f in p.risk_flags)
        and not p.decision_note
    ]
    return [
        {
            "check": "Every GitHub write matches a human approval of the same content",
            "severity": "exception",
            "passed": not unapproved,
            "tested": len(writes),
            "exceptions": unapproved,
        },
        {
            "check": "Work is approved by someone other than the person who requested it",
            "severity": "review",
            "passed": not self_approved,
            "tested": sum(1 for p in proposals if p.decided_by and p.requirement_id),
            "exceptions": self_approved,
        },
        {
            "check": "High-risk approvals carry a note explaining the decision",
            "severity": "review",
            "passed": not risky,
            "tested": sum(
                1 for p in proposals
                if p.decided_by and any(f["level"] == HIGH_RISK for f in p.risk_flags)
            ),
            "exceptions": risky,
        },
    ]


def build_pack(start: str, end: str, generated_by: str) -> tuple[bytes, dict[str, Any]]:
    first, last = _bounds(start, end)
    chain = audit.verify_chain()
    with read_session() as s:
        events = s.scalars(
            select(AuditEvent).where(AuditEvent.ts >= first, AuditEvent.ts <= last)
            .order_by(AuditEvent.seq)
        ).all()
        proposals = s.scalars(
            select(Proposal).where(Proposal.created_at <= last)
            .where((Proposal.decided_at >= first) & (Proposal.decided_at <= last))
            .order_by(Proposal.decided_at)
        ).all()
        filed_by = dict(s.execute(select(Requirement.id, Requirement.created_by)).all())
        written_ids = {e.subject_id for e in events if e.action in WRITE_ACTIONS}
        written = {
            p.id: p for p in s.scalars(select(Proposal).where(Proposal.id.in_(written_ids)))
        }
        prs = {t.id: t.pr_url for t in s.scalars(select(Task))}

    decisions = _csv(
        ["proposal_id", "kind", "title", "repository", "proposed_at", "outcome", "decided_by",
         "decided_at", "note", "edited_by", "content_sha256", "risk_flags", "external_url"],
        [[p.id, p.kind, p.title, p.repo, p.created_at, p.status, p.decided_by, p.decided_at,
          p.decision_note, p.edited_by, p.payload_hash,
          ";".join(f["code"] for f in p.risk_flags), p.external_url or prs.get(p.task_id)]
         for p in proposals],
    )
    writes = _csv(
        ["seq", "time", "action", "proposal_id", "approved_by", "content_sha256", "url"],
        [[e.seq, e.ts, e.action, e.subject_id, e.data.get("approved_by"),
          e.data.get("payload_hash"), e.data.get("url")]
         for e in events if e.action.startswith("github.")],
    )
    access = _csv(
        ["seq", "time", "actor", "action", "subject"],
        [[e.seq, e.ts, e.actor, e.action, e.subject_id]
         for e in events if e.action.startswith(ACCESS_PREFIXES)],
    )
    raw = "".join(
        json.dumps(audit.event_dict(e), ensure_ascii=False) + "\n" for e in events
    ).encode()
    checks = _control_checks(events, proposals, written, filed_by)
    summary = {
        "period": {"start": start, "end": end},
        "generated_at": now_iso(),
        "generated_by": generated_by,
        "audit_chain": {
            "verified": chain["ok"], "events_checked": chain["checked"],
            "head": chain["head"], "first_bad_seq": chain["first_bad_seq"],
        },
        "counts": {
            "events": len(events), "decisions": len(proposals),
            "github_writes": sum(e.action.startswith("github.") for e in events),
        },
        "suggested_control_mapping": CONTROL_MAP,
        "note": "Evidence to support an audit. Not a certification.",
    }
    files = {
        "README.txt": README.encode(),
        "summary.json": json.dumps(summary, indent=2).encode(),
        "control_checks.json": json.dumps(checks, indent=2).encode(),
        "decisions.csv": decisions,
        "github_writes.csv": writes,
        "access_log.csv": access,
        "audit_events.jsonl": raw,
    }
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    signed = json.dumps(hashes, sort_keys=True).encode()
    manifest = {
        "files": hashes,
        "algorithm": "HMAC-SHA256 over the sorted JSON of files",
        "signature": hmac.new(vault.audit_key(), signed, hashlib.sha256).hexdigest(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    result = {
        "chain_verified": chain["ok"],
        "failed_checks": sum(1 for c in checks if not c["passed"]),
        "sha256": hashlib.sha256(buffer.getvalue()).hexdigest(),
    }
    return buffer.getvalue(), result
