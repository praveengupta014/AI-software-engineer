"""GitHub webhooks: new pull requests get a draft review, and an issue labelled `countersign`
becomes a requirement. Both only start agents, whose output still waits for a person, and
nothing is posted back to GitHub from here: that would be a write nobody approved.
"""

import hashlib
import hmac
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import audit, pipeline, vault
from .db import write_tx
from .models import AgentRun, Proposal, Requirement, WebhookDelivery
from .pipeline import backends

ISSUE_LABEL = "countersign"
# A public repo lets anyone open a PR. Reviewing theirs would spend your tokens on demand.
TRUSTED_AUTHORS = {"OWNER", "MEMBER", "COLLABORATOR"}
_REVIEW_ACTIONS = {"opened", "reopened", "ready_for_review"}
MAX_TITLE, MAX_BODY = 200, 20000


def verify_signature(body: bytes, signature: str | None) -> None:
    secret = vault.github_webhook_secret()
    if not secret:
        raise HTTPException(503, "Webhooks are not configured")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid signature")


def handle(event: str, delivery_id: str, body: bytes) -> dict[str, str]:
    payload = json.loads(body)
    try:
        with write_tx() as s:
            s.add(WebhookDelivery(delivery_id=delivery_id, event=event))
            s.flush()
            run_id, result = _dispatch(s, event, payload)
    except IntegrityError:
        return {"result": "duplicate delivery"}
    if run_id:
        backends.notify(run_id)
    return {"result": result}


def _dispatch(s, event: str, payload: dict[str, Any]) -> tuple[str | None, str]:
    if event == "pull_request":
        return _on_pull_request(s, payload)
    if event == "issues":
        return _on_issue(s, payload)
    return None, "ignored"


def _on_pull_request(s, payload: dict[str, Any]) -> tuple[str | None, str]:
    pr = payload["pull_request"]
    if payload["action"] not in _REVIEW_ACTIONS or pr.get("draft"):
        return None, "ignored"
    if pr["head"]["ref"].startswith("countersign/"):
        return None, "ignored: reviewed by its own pipeline"
    if pr.get("author_association") not in TRUSTED_AUTHORS:
        return None, "ignored: author is outside the repository"

    repo, number = payload["repository"]["full_name"], pr["number"]
    active = s.scalar(
        select(AgentRun.id).where(
            AgentRun.repo == repo, AgentRun.pr_number == number,
            AgentRun.status.in_(("queued", "running")),
        )
    )
    awaiting = s.scalar(
        select(Proposal.id).where(
            Proposal.repo == repo, Proposal.kind == "review", Proposal.status == "pending",
            Proposal.title.startswith(f"Review: #{number} "),
        )
    )
    if active or awaiting:
        return None, "ignored: already in review"

    sender = payload["sender"]["login"]
    run = pipeline.create_run(
        s, "reviewer", repo=repo, user=f"github:{sender}", pr_number=number, actor_type="system",
    )
    return run.id, "review queued"


def _on_issue(s, payload: dict[str, Any]) -> tuple[str | None, str]:
    if payload["action"] != "labeled" or payload["label"]["name"] != ISSUE_LABEL:
        return None, "ignored"
    issue = payload["issue"]
    if s.scalar(select(Requirement.id).where(Requirement.source_url == issue["html_url"])):
        return None, "ignored: already a requirement"

    repository, sender = payload["repository"], f"github:{payload['sender']['login']}"
    title = issue["title"][:MAX_TITLE]
    req = Requirement(
        title=title,
        body=(issue.get("body") or title)[:MAX_BODY],
        repo=repository["full_name"],
        base_branch=repository["default_branch"],
        created_by=sender,
        source_url=issue["html_url"],
    )
    s.add(req)
    s.flush()
    audit.record(
        s, actor_type="system", actor=sender, action="requirement.created",
        subject_type="requirement", subject_id=req.id, requirement_id=req.id,
        data={"title": req.title, "repo": req.repo, "source_url": issue["html_url"],
              "body_sha256": audit.sha256_hex(req.body)},
    )
    run = pipeline.create_run(
        s, "planner", repo=req.repo, user=sender, requirement_id=req.id, actor_type="system",
    )
    return run.id, "planning queued"
