"""Jira and Linear webhooks: a ticket labelled `countersign` becomes a requirement.

The ticket's project is mapped to a repository in Settings, so a ticket can never choose which
repository agents work on. Like GitHub webhooks, this only starts a planner whose plan then
waits for a person.
"""

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from . import audit, pipeline, vault
from .db import write_tx
from .models import Requirement, TrackerLink, WebhookDelivery
from .pipeline import backends

LABEL = "countersign"
LINEAR_MAX_AGE_SECONDS = 60
MAX_TITLE, MAX_BODY = 200, 20000


def _hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_jira(body: bytes, signature: str | None) -> None:
    secret = vault.jira_webhook_secret()
    if not secret:
        raise HTTPException(503, "Jira webhooks are not configured")
    if not signature or not hmac.compare_digest(f"sha256={_hmac_hex(secret, body)}", signature):
        raise HTTPException(401, "Invalid signature")


def verify_linear(body: bytes, signature: str | None) -> None:
    secret = vault.linear_webhook_secret()
    if not secret:
        raise HTTPException(503, "Linear webhooks are not configured")
    if not signature or not hmac.compare_digest(_hmac_hex(secret, body), signature):
        raise HTTPException(401, "Invalid signature")
    sent_ms = json.loads(body).get("webhookTimestamp", 0)
    if abs(time.time() - sent_ms / 1000) > LINEAR_MAX_AGE_SECONDS:
        raise HTTPException(401, "Webhook is too old")


def _adf_text(node: Any) -> str:
    """Jira Cloud may send descriptions as Atlassian Document Format rather than text."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        parts = [_adf_text(child) for child in node.get("content", [])]
        separator = "\n" if node.get("type") in ("doc", "bulletList", "orderedList") else ""
        return separator.join(parts)
    return ""


def parse_jira(payload: dict[str, Any]) -> dict[str, str] | None:
    if payload.get("webhookEvent") not in ("jira:issue_created", "jira:issue_updated"):
        return None
    issue = payload.get("issue") or {}
    fields = issue.get("fields") or {}
    if LABEL not in [str(x).lower() for x in fields.get("labels") or []]:
        return None
    parts = urlsplit(issue.get("self", ""))
    title = fields.get("summary") or issue.get("key", "")
    return {
        "project": (fields.get("project") or {}).get("key", ""),
        "title": title,
        "body": _adf_text(fields.get("description")).strip() or title,
        "url": f"{parts.scheme}://{parts.netloc}/browse/{issue.get('key')}",
        "actor": (payload.get("user") or {}).get("displayName", "unknown"),
    }


def parse_linear(payload: dict[str, Any]) -> dict[str, str] | None:
    if payload.get("type") != "Issue" or payload.get("action") not in ("create", "update"):
        return None
    data = payload.get("data") or {}
    names = [str(label.get("name", "")).lower() for label in data.get("labels") or []]
    if LABEL not in names:
        return None
    identifier = data.get("identifier", "")
    team = (data.get("team") or {}).get("key") or identifier.split("-")[0]
    title = data.get("title") or identifier
    return {
        "project": team,
        "title": title,
        "body": (data.get("description") or "").strip() or title,
        "url": data.get("url") or payload.get("url", ""),
        "actor": (payload.get("actor") or {}).get("name", "unknown"),
    }


def handle(provider: str, delivery_id: str, ticket: dict[str, str] | None) -> dict[str, str]:
    try:
        with write_tx() as s:
            s.add(WebhookDelivery(delivery_id=f"{provider}:{delivery_id}", event=provider))
            s.flush()
            run_id, result = _create(s, provider, ticket)
    except IntegrityError:
        return {"result": "duplicate delivery"}
    if run_id:
        backends.notify(run_id)
    return {"result": result}


def _create(s, provider: str, ticket: dict[str, str] | None) -> tuple[str | None, str]:
    if ticket is None:
        return None, "ignored"
    link = s.scalar(
        select(TrackerLink).where(
            TrackerLink.provider == provider,
            func.upper(TrackerLink.project_key) == ticket["project"].upper(),
        )
    )
    if link is None:
        return None, "ignored: this project is not linked to a repository"
    if s.scalar(select(Requirement.id).where(Requirement.source_url == ticket["url"])):
        return None, "ignored: already a requirement"

    actor = f"{provider}:{ticket['actor']}"
    req = Requirement(
        title=ticket["title"][:MAX_TITLE],
        body=ticket["body"][:MAX_BODY],
        repo=link.repo,
        base_branch=link.base_branch,
        created_by=actor,
        source_url=ticket["url"],
    )
    s.add(req)
    s.flush()
    audit.record(
        s, actor_type="system", actor=actor, action="requirement.created",
        subject_type="requirement", subject_id=req.id, requirement_id=req.id,
        data={"title": req.title, "repo": req.repo, "source_url": ticket["url"],
              "body_sha256": audit.sha256_hex(req.body)},
    )
    run = pipeline.create_run(
        s, "planner", repo=req.repo, user=actor, requirement_id=req.id, actor_type="system",
    )
    return run.id, "planning queued"
