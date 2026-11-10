import hashlib
import hmac
import json

import pytest

from app import vault
from tests.fakes import DEMO_REPO

SECRET = "webhook-secret"
PATH = "/api/webhooks/github"


def pr_payload(action="opened", number=42, association="MEMBER", ref="feature", draft=False):
    return {
        "action": action,
        "repository": {"full_name": DEMO_REPO, "default_branch": "main"},
        "sender": {"login": "grace"},
        "pull_request": {"number": number, "draft": draft, "author_association": association,
                         "head": {"ref": ref}},
    }


def issue_payload(label="countersign", action="labeled", url="https://github.test/i/1"):
    return {
        "action": action,
        "label": {"name": label},
        "repository": {"full_name": DEMO_REPO, "default_branch": "main"},
        "sender": {"login": "grace"},
        "issue": {"title": "Limit login attempts", "body": None, "html_url": url},
    }


@pytest.fixture
def secured(client):
    vault.update(github_webhook_secret=SECRET)
    return client


counter = iter(range(10_000))


def send(client, event, payload, secret=SECRET, delivery=None):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(PATH, content=body, headers={
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery or f"d{next(counter)}",
        "X-Hub-Signature-256": signature,
        "Authorization": "",
    })


def pending(client):
    return client.get("/api/overview").json()["pending"]


def test_rejects_bad_or_missing_signatures(secured):
    assert send(secured, "pull_request", pr_payload(), secret="wrong").status_code == 401
    missing = secured.post(PATH, content=b"{}", headers={"X-GitHub-Delivery": "x"})
    assert missing.status_code == 401
    assert pending(secured) == []


def test_refuses_everything_when_no_secret_is_configured(client):
    assert send(client, "pull_request", pr_payload()).status_code == 503


def test_new_pr_gets_a_draft_review_awaiting_approval(secured):
    from app.pipeline import backends

    resp = send(secured, "pull_request", pr_payload())
    assert resp.status_code == 202 and resp.json()["result"] == "review queued"
    assert pending(secured)[0]["kind"] == "review"
    assert backends.github.reviews == []  # nothing posted without a person


def test_redelivery_is_ignored(secured):
    assert send(secured, "pull_request", pr_payload(), delivery="same").json()["result"] == "review queued"
    assert send(secured, "pull_request", pr_payload(), delivery="same").json()["result"] == "duplicate delivery"
    assert len(pending(secured)) == 1


def test_second_event_for_a_pr_in_review_is_ignored(secured):
    send(secured, "pull_request", pr_payload())
    resp = send(secured, "pull_request", pr_payload(action="reopened"))
    assert resp.json()["result"] == "ignored: already in review"
    assert len(pending(secured)) == 1


@pytest.mark.parametrize("payload, reason", [
    (pr_payload(association="NONE"), "outside the repository"),
    (pr_payload(association="FIRST_TIME_CONTRIBUTOR"), "outside the repository"),
    (pr_payload(draft=True), "ignored"),
    (pr_payload(action="closed"), "ignored"),
    (pr_payload(action="synchronize"), "ignored"),
    (pr_payload(ref="countersign/abc-task"), "own pipeline"),
])
def test_prs_that_should_not_trigger_a_review(secured, payload, reason):
    assert reason in send(secured, "pull_request", payload).json()["result"]
    assert pending(secured) == []


def test_labelled_issue_becomes_a_requirement(secured):
    assert send(secured, "issues", issue_payload()).json()["result"] == "planning queued"
    req = secured.get("/api/requirements").json()[0]
    assert req["title"] == "Limit login attempts" and req["created_by"] == "github:grace"
    assert req["source_url"] == "https://github.test/i/1"
    assert pending(secured)[0]["kind"] == "plan"
    assert send(secured, "issues", issue_payload()).json()["result"] == "ignored: already a requirement"


@pytest.mark.parametrize("payload", [issue_payload(label="bug"), issue_payload(action="opened")])
def test_other_issue_events_are_ignored(secured, payload):
    assert send(secured, "issues", payload).json()["result"] == "ignored"
    assert secured.get("/api/requirements").json() == []


def test_unknown_events_are_accepted_and_ignored(secured):
    assert send(secured, "ping", {"zen": "ok"}).json()["result"] == "ignored"


def test_webhook_activity_is_audited_as_system_not_a_person(secured):
    send(secured, "pull_request", pr_payload())
    event = secured.get("/api/audit?action=run.requested").json()["events"][0]
    assert event["actor_type"] == "system" and event["actor"] == "github:grace"
