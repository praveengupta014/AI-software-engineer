"""Tells Slack and Teams when a proposal needs a person.

A message is queued in the same transaction as its proposal and delivered by the workers, so a
Slack outage can neither lose a notification nor hold up an agent. Decisions stay inside
Countersign: these messages only link to the review page.
"""

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import vault
from .db import read_session, write_tx
from .models import NotificationOutbox, Proposal, iso_in, now_iso

log = logging.getLogger("countersign.notifications")

MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 30
MAX_SUMMARY_CHARS = 300
_ALLOWED_HOSTS = {
    "slack": ("hooks.slack.com",),
    "teams": (".webhook.office.com", ".logic.azure.com", ".powerplatform.com"),
}


class PermanentFailure(Exception):
    pass


def url_problem(channel: str, url: str) -> str | None:
    """Webhook URLs are stored and called by the server, so only real services are accepted."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    allowed = _ALLOWED_HOSTS[channel]
    matches = any(host == h or (h.startswith(".") and host.endswith(h)) for h in allowed)
    if parts.scheme != "https" or not matches:
        return f"That does not look like a {channel.title()} webhook URL"
    return None


def channel_url(channel: str) -> str:
    return vault.slack_webhook_url() if channel == "slack" else vault.teams_webhook_url()


def enqueue(s: Session, proposal: Proposal) -> None:
    for channel in ("slack", "teams"):
        if channel_url(channel):
            s.add(NotificationOutbox(channel=channel, proposal_id=proposal.id))


def _review_url(proposal: Proposal) -> str | None:
    base = vault.public_url()
    return f"{base.rstrip('/')}/proposals/{proposal.id}" if base else None


def _short(text: str | None) -> str:
    text = (text or "").strip()
    return text if len(text) <= MAX_SUMMARY_CHARS else text[: MAX_SUMMARY_CHARS - 1] + "…"


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_message(proposal: Proposal, label: str, summary: str | None) -> dict[str, Any]:
    high = [f["message"] for f in proposal.risk_flags if f["level"] == "high"]
    url = _review_url(proposal)
    title = _slack_escape(proposal.title)
    lines = [f"*{label} waiting for approval:* {title}", f"Repository: `{proposal.repo}`"]
    if summary:
        lines.append(_slack_escape(_short(summary)))
    if high:
        lines.append(f":warning: {len(high)} high-risk item(s) flagged")
    if url:
        lines.append(f"<{url}|Review in Countersign>")
    # Agent text can quote repository content, so unfurling must stay off.
    return {"text": "\n".join(lines), "unfurl_links": False, "unfurl_media": False}


def teams_message(proposal: Proposal, label: str, summary: str | None) -> dict[str, Any]:
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": f"{label} waiting for approval", "weight": "Bolder",
         "size": "Medium", "wrap": True},
        {"type": "TextBlock", "text": proposal.title, "wrap": True},
        {"type": "TextBlock", "text": f"Repository: {proposal.repo}", "isSubtle": True,
         "wrap": True},
    ]
    if summary:
        body.append({"type": "TextBlock", "text": _short(summary), "wrap": True})
    high = sum(f["level"] == "high" for f in proposal.risk_flags)
    if high:
        body.append({"type": "TextBlock", "text": f"{high} high-risk item(s) flagged",
                     "color": "Attention", "wrap": True})
    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }
    url = _review_url(proposal)
    if url:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Review in Countersign", "url": url}]
    return {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
        ],
    }


def _post(url: str, message: dict[str, Any]) -> None:
    response = httpx.post(url, json=message, timeout=10)
    if response.status_code == 429 or response.status_code >= 500:
        raise httpx.HTTPStatusError(
            f"HTTP {response.status_code}", request=response.request, response=response
        )
    if response.status_code >= 300:
        # Deliberately not the body or the URL: a webhook URL is a credential.
        raise PermanentFailure(f"The service refused the message (HTTP {response.status_code})")


def send(channel: str, proposal: Proposal, label: str, summary: str | None) -> None:
    build = slack_message if channel == "slack" else teams_message
    _post(channel_url(channel), build(proposal, label, summary))


def send_test(channel: str, url: str) -> None:
    text = "Countersign is connected. Proposals that need a person will appear here."
    message = (
        {"text": text} if channel == "slack"
        else {"type": "message", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"type": "AdaptiveCard", "version": "1.4",
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "body": [{"type": "TextBlock", "text": text, "wrap": True}]},
        }]}
    )
    _post(url, message)


def deliver_pending(limit: int = 10) -> None:
    from .pipeline import KIND_LABEL

    now = now_iso()
    with read_session() as s:
        ids = s.scalars(
            select(NotificationOutbox.id)
            .where(NotificationOutbox.status == "pending", NotificationOutbox.available_at <= now)
            .order_by(NotificationOutbox.created_at)
            .limit(limit)
        ).all()
    for notification_id in ids:
        with write_tx() as s:  # claim it, so a second worker cannot send it twice
            row = s.scalar(
                select(NotificationOutbox)
                .where(NotificationOutbox.id == notification_id,
                       NotificationOutbox.status == "pending")
                .with_for_update(skip_locked=True)
            )
            if row is None:
                continue
            row.status = "sending"
            row.attempts += 1
            row.available_at = now_iso()  # recover_stuck measures from here
            channel, proposal_id, attempts = row.channel, row.proposal_id, row.attempts
        with read_session() as s:
            proposal = s.get(Proposal, proposal_id)
        outcome, error = "sent", None
        try:
            if not channel_url(channel):
                raise PermanentFailure("Channel was disconnected")
            send(channel, proposal, KIND_LABEL[proposal.kind],
                 proposal.payload.get("summary") or proposal.payload.get("body"))
        except PermanentFailure as exc:
            outcome, error = "failed", str(exc)
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            error = f"HTTP {status}" if status else "Could not reach the service"
            outcome = "failed" if attempts >= MAX_ATTEMPTS else "pending"
        with write_tx() as s:
            row = s.get(NotificationOutbox, notification_id)
            row.status, row.error = outcome, error
            if outcome == "pending":
                row.available_at = iso_in(BASE_DELAY_SECONDS * 2 ** (attempts - 1))
        if error:
            log.warning("%s notification %s: %s", channel, notification_id, error)


def recover_stuck(cutoff: str) -> None:
    """A worker died mid-send. Better a rare duplicate than a lost approval request."""
    with write_tx() as s:
        for row in s.scalars(
            select(NotificationOutbox).where(
                NotificationOutbox.status == "sending", NotificationOutbox.available_at < cutoff
            )
        ):
            row.status = "pending"
