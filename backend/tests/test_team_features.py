"""Password change, removing approvers, repo memory, notifications, trackers, insights, evidence."""

import csv
import hashlib
import hmac
import io
import json
import time
import zipfile
from datetime import UTC, datetime

import pytest
import respx

from app import memory, notifications, vault
from app.db import read_session
from app.models import NotificationOutbox, RepoMemory
from tests.conftest import PASSWORD, USER
from tests.fakes import DEMO_REPO

REQ = {"title": "Rate limit login", "body": "Stop password guessing on login.", "repo": DEMO_REPO}
SLACK = "https://hooks.slack.com/services/T0/B0/secret-token"
TEAMS = "https://prod-1.westus.logic.azure.com/workflows/abc/triggers/manual?sig=secret"
TODAY = datetime.now(UTC).date().isoformat()


def pending(client):
    return client.get("/api/overview").json()["pending"]


def approve(client, p):
    return client.post(f"/api/proposals/{p['id']}/approve",
                       json={"expected_hash": p["payload_hash"]})


def login(client, name, password):
    return client.post("/api/auth/login", json={"name": name, "password": password})


# Accounts -----------------------------------------------------------------------------------


def test_change_password_needs_the_current_one_and_ends_other_sessions(client):
    other = login(client, USER, PASSWORD).json()["token"]
    wrong = client.post("/api/auth/change-password",
                        json={"current_password": "nope", "new_password": "a new password"})
    assert wrong.status_code == 403
    ok = client.post("/api/auth/change-password",
                     json={"current_password": PASSWORD, "new_password": "a new password"})
    assert ok.status_code == 200

    assert client.get("/api/me").status_code == 200  # this session survives
    stale = client.get("/api/me", headers={"Authorization": f"Bearer {other}"})
    assert stale.status_code == 401
    assert login(client, USER, PASSWORD).status_code == 401
    assert login(client, USER, "a new password").status_code == 200
    assert "a new password" not in client.get("/api/audit?action=auth.").text


def test_change_password_enforces_minimum_length(client):
    resp = client.post("/api/auth/change-password",
                       json={"current_password": PASSWORD, "new_password": "short"})
    assert resp.status_code == 422


def test_removed_approver_loses_access_immediately_but_keeps_their_history(client):
    client.post("/api/users", json={"name": "Ravi", "password": "another-pass"})
    token = login(client, "Ravi", "another-pass").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/requirements", json=REQ)
    p = pending(client)[0]
    client.post(f"/api/proposals/{p['id']}/approve", headers=headers,
                json={"expected_hash": p["payload_hash"]})

    assert client.delete("/api/users/Ravi").status_code == 200
    assert client.get("/api/me", headers=headers).status_code == 401
    assert login(client, "Ravi", "another-pass").status_code == 401
    assert client.get(f"/api/proposals/{p['id']}").json()["decided_by"] == "Ravi"
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_cannot_remove_yourself_or_a_missing_user(client):
    assert client.delete(f"/api/users/{USER}").status_code == 409
    assert client.delete("/api/users/Nobody").status_code == 404


# Repo memory --------------------------------------------------------------------------------


class _Capture:
    def __init__(self, inner):
        self.inner, self.prompts = inner, []

    def turn(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return self.inner.turn(**kwargs)


@pytest.fixture
def captured(client, monkeypatch):
    from app import pipeline

    llm = _Capture(pipeline.backends.llm)
    monkeypatch.setattr(pipeline.backends, "llm", llm)
    return llm


def test_rejection_note_reaches_the_same_agent_on_the_next_run(client, captured):
    client.post("/api/requirements", json=REQ)
    p = pending(client)[0]
    client.post(f"/api/proposals/{p['id']}/reject", json={"note": "Plans must mention rollback"})
    req_id = client.get("/api/requirements").json()[0]["id"]
    client.post(f"/api/requirements/{req_id}/replan")

    assert "<team_guidance>" in captured.prompts[-1]
    assert "Plans must mention rollback" in captured.prompts[-1]
    assert "memory.applied" in str(client.get("/api/audit?action=memory.").json())


def test_lessons_stay_with_their_agent_and_repo(client):
    from app.db import write_tx

    with write_tx() as s:
        s.add(RepoMemory(repo="a/b", kind="lesson", applies_to="coder", text="coder only",
                         created_by="x"))
        s.add(RepoMemory(repo="a/b", kind="convention", text="for everyone", created_by="x"))
        s.add(RepoMemory(repo="other/repo", kind="convention", text="elsewhere", created_by="x"))
    assert [m.text for m in memory.for_agent("a/b", "coder")] == ["for everyone", "coder only"]
    assert [m.text for m in memory.for_agent("a/b", "tester")] == ["for everyone"]


def test_memory_can_be_added_edited_and_turned_off(client, captured):
    created = client.post("/api/memory", json={"repo": DEMO_REPO, "text": "Use tabs in Makefiles"})
    memory_id = created.json()["id"]
    client.post("/api/requirements", json=REQ)
    assert "Use tabs in Makefiles" in captured.prompts[-1]

    assert client.put(f"/api/memory/{memory_id}", json={"active": False}).status_code == 200
    client.post("/api/requirements", json=REQ)
    assert "Use tabs in Makefiles" not in captured.prompts[-1]


def test_same_note_is_only_learned_once(client):
    for _ in range(2):
        client.post("/api/requirements", json=REQ)
        p = next(x for x in pending(client) if x["kind"] == "plan")
        client.post(f"/api/proposals/{p['id']}/reject", json={"note": "Same note"})
    assert len(client.get("/api/memory").json()["items"]) == 1


def test_memory_budget_is_bounded():
    assert memory.MAX_ENTRIES * 1000 > memory.MAX_CHARS  # the character cap does real work


# Notifications ------------------------------------------------------------------------------


def configure(client, **values):
    return client.put("/api/settings/notifications", json=values)


@pytest.mark.parametrize("channel, url", [
    ("slack_url", "http://hooks.slack.com/services/x"),
    ("slack_url", "https://hooks.slack.com.evil.test/services/x"),
    ("slack_url", "https://169.254.169.254/latest"),
    ("teams_url", "https://example.com/hook"),
])
def test_only_real_service_urls_are_accepted(client, channel, url):
    assert configure(client, **{channel: url}).status_code == 422


@respx.mock
def test_proposal_reaches_slack_with_a_review_link_and_escaped_text(client):
    assert configure(client, slack_url=SLACK, public_url="https://cs.example.com/").status_code == 200
    client.post("/api/requirements", json={**REQ, "title": "Fix <script> & stuff"})
    route = respx.post(SLACK).respond(200, text="ok")
    notifications.deliver_pending()

    message = json.loads(route.calls[0].request.content)
    proposal = pending(client)[0]
    assert f"<https://cs.example.com/proposals/{proposal['id']}|Review in Countersign>" in message["text"]
    assert "Fix &lt;script&gt; &amp; stuff" in message["text"]
    assert message["unfurl_links"] is False
    notifications.deliver_pending()
    assert route.call_count == 1  # delivered once


@respx.mock
def test_teams_gets_an_adaptive_card(client):
    configure(client, teams_url=TEAMS, public_url="https://cs.example.com")
    client.post("/api/requirements", json=REQ)
    route = respx.post(TEAMS).respond(202)
    notifications.deliver_pending()
    message = json.loads(route.calls[0].request.content)
    assert message["type"] == "message"
    attachment = message["attachments"][0]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert attachment["content"]["actions"][0]["type"] == "Action.OpenUrl"


def outbox():
    with read_session() as s:
        return s.query(NotificationOutbox).one()


@respx.mock
def test_outage_retries_later_and_never_blocks_the_proposal(client):
    configure(client, slack_url=SLACK)
    client.post("/api/requirements", json=REQ)
    respx.post(SLACK).respond(503)
    notifications.deliver_pending()
    row = outbox()
    assert (row.status, row.attempts, row.error) == ("pending", 1, "HTTP 503")
    assert pending(client)  # the approval queue is unaffected
    notifications.deliver_pending()
    assert outbox().attempts == 1  # backing off, not hammering a struggling service


@respx.mock
def test_a_rejected_webhook_is_not_retried_and_never_logs_the_url(client):
    configure(client, slack_url=SLACK)
    client.post("/api/requirements", json=REQ)
    respx.post(SLACK).respond(404, text="no_service")
    notifications.deliver_pending()
    row = outbox()
    assert row.status == "failed" and "secret-token" not in (row.error or "")
    assert client.get("/api/settings").json()["notifications"]["failed"] == 1


def test_no_channel_means_nothing_is_queued(client):
    client.post("/api/requirements", json=REQ)
    with read_session() as s:
        assert s.query(NotificationOutbox).count() == 0


def test_settings_and_audit_never_expose_webhook_urls(client):
    configure(client, slack_url=SLACK, teams_url=TEAMS)
    for path in ("/api/settings", "/api/audit?action=settings.", "/api/data/audit_events"):
        text = client.get(path).text
        assert "secret-token" not in text and "sig=secret" not in text


@respx.mock
def test_send_test_message(client):
    configure(client, slack_url=SLACK)
    route = respx.post(SLACK).respond(200, text="ok")
    resp = client.post("/api/settings/notifications/test", json={"channel": "slack"})
    assert resp.status_code == 200 and route.called
    respx.post(SLACK).respond(403)
    assert client.post("/api/settings/notifications/test",
                       json={"channel": "slack"}).status_code == 502
    assert client.post("/api/settings/notifications/test",
                       json={"channel": "teams"}).status_code == 409


def test_worker_recovers_a_send_interrupted_by_a_crash(client):
    from app.db import write_tx
    from app.models import iso_in

    with write_tx() as s:
        s.add(NotificationOutbox(id="n1", channel="slack", proposal_id="p", status="sending",
                                 available_at=iso_in(-1000)))
    notifications.recover_stuck(iso_in(-90))
    assert outbox().status == "pending"


# Trackers -----------------------------------------------------------------------------------


JIRA_SECRET, LINEAR_SECRET = "jira-secret", "linear-secret"


def jira_payload(labels=("countersign",), project="SHOP", key="SHOP-12", description="Limit it."):
    return {
        "webhookEvent": "jira:issue_updated",
        "user": {"displayName": "Grace"},
        "issue": {"key": key, "self": "https://acme.atlassian.net/rest/api/2/issue/1",
                  "fields": {"summary": "Rate limit login", "description": description,
                             "labels": list(labels), "project": {"key": project}}},
    }


def linear_payload(labels=("Countersign",), team="ENG", action="create", age=0):
    return {
        "action": action, "type": "Issue", "url": "https://linear.app/acme/issue/ENG-7",
        "actor": {"name": "Grace"}, "webhookTimestamp": int((time.time() - age) * 1000),
        "data": {"identifier": "ENG-7", "title": "Rate limit login", "description": "Limit it.",
                 "url": "https://linear.app/acme/issue/ENG-7", "team": {"key": team},
                 "labels": [{"name": x} for x in labels]},
    }


def send_jira(client, payload, secret=JIRA_SECRET, delivery="j1"):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks/jira", content=body, headers={
        "X-Hub-Signature": sig, "X-Atlassian-Webhook-Identifier": delivery})


def send_linear(client, payload, secret=LINEAR_SECRET, delivery="l1"):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks/linear", content=body, headers={
        "Linear-Signature": sig, "Linear-Delivery": delivery})


@pytest.fixture
def linked(client):
    client.put("/api/settings/trackers", json={"jira_secret": JIRA_SECRET,
                                               "linear_secret": LINEAR_SECRET})
    for provider, key in (("jira", "shop"), ("linear", "ENG")):
        resp = client.post("/api/settings/tracker-links", json={
            "provider": provider, "project_key": key, "repo": DEMO_REPO})
        assert resp.status_code == 201
    return client


def test_jira_ticket_becomes_a_requirement_in_the_linked_repo(linked):
    assert send_jira(linked, jira_payload()).json()["result"] == "planning queued"
    req = linked.get("/api/requirements").json()[0]
    assert (req["repo"], req["created_by"]) == (DEMO_REPO, "jira:Grace")
    assert req["source_url"] == "https://acme.atlassian.net/browse/SHOP-12"
    assert pending(linked)[0]["kind"] == "plan"


def test_linear_ticket_becomes_a_requirement(linked):
    assert send_linear(linked, linear_payload()).json()["result"] == "planning queued"
    assert linked.get("/api/requirements").json()[0]["created_by"] == "linear:Grace"


def test_jira_rich_text_description_is_flattened(linked):
    adf = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "Limit "}, {"type": "text", "text": "attempts"}]}]}
    send_jira(linked, jira_payload(description=adf))
    assert linked.get("/api/requirements").json()[0]["body"] == "Limit attempts"


@pytest.mark.parametrize("sender", [send_jira, send_linear])
def test_tracker_signatures_are_enforced(linked, sender):
    payload = jira_payload() if sender is send_jira else linear_payload()
    assert sender(linked, payload, secret="wrong").status_code == 401
    assert linked.get("/api/requirements").json() == []


def test_unconfigured_tracker_refuses_everything(client):
    assert send_jira(client, jira_payload()).status_code == 503
    assert send_linear(client, linear_payload()).status_code == 503


def test_old_linear_webhook_is_rejected_as_a_replay(linked):
    assert send_linear(linked, linear_payload(age=120)).status_code == 401


def test_unlabelled_and_unlinked_tickets_do_nothing(linked):
    assert send_jira(linked, jira_payload(labels=["bug"])).json()["result"] == "ignored"
    result = send_jira(linked, jira_payload(project="OTHER"), delivery="j2").json()["result"]
    assert "not linked" in result
    assert send_linear(linked, linear_payload(labels=[])).json()["result"] == "ignored"
    assert linked.get("/api/requirements").json() == []


def test_repeat_updates_create_one_requirement(linked):
    send_jira(linked, jira_payload(), delivery="a")
    assert send_jira(linked, jira_payload(), delivery="a").json()["result"] == "duplicate delivery"
    assert "already" in send_jira(linked, jira_payload(), delivery="b").json()["result"]
    assert len(linked.get("/api/requirements").json()) == 1


def test_tracker_links_can_be_removed_and_are_unique(linked):
    links = linked.get("/api/settings").json()["trackers"]["links"]
    assert [link["project_key"] for link in links] == ["SHOP", "ENG"]
    dup = linked.post("/api/settings/tracker-links", json={
        "provider": "jira", "project_key": "SHOP", "repo": DEMO_REPO})
    assert dup.status_code == 409
    assert linked.delete(f"/api/settings/tracker-links/{links[0]['id']}").status_code == 200
    assert "not linked" in send_jira(linked, jira_payload()).json()["result"]


# Insights -----------------------------------------------------------------------------------


def run_to_pr(client):
    client.post("/api/requirements", json=REQ)
    approve(client, pending(client)[0])
    req_id = client.get("/api/requirements").json()[0]["id"]
    task = client.get(f"/api/requirements/{req_id}").json()["tasks"][0]
    client.post(f"/api/tasks/{task['id']}/start")
    approve(client, pending(client)[0])
    approve(client, pending(client)[0])
    approve(client, pending(client)[0])
    return req_id


def set_usage(input_tokens=1_000_000, output_tokens=1_000_000, cache=1_000_000):
    from sqlalchemy import update

    from app.db import write_tx
    from app.models import AgentRun

    with write_tx() as s:
        s.execute(update(AgentRun).values(
            input_tokens=input_tokens, output_tokens=output_tokens, cache_read_tokens=cache))


def test_insights_measure_approval_and_cost(client):
    run_to_pr(client)
    review = pending(client)[0]
    client.post(f"/api/proposals/{review['id']}/request-changes", json={"note": "Too vague"})
    set_usage()

    data = client.get("/api/insights?days=30").json()
    overview = data["overview"]
    assert overview["decided"] == 4  # plan, code, tests, review; the PR proposal is excluded
    assert overview["approved_as_is"] == 3 and overview["sent_back"] == 1
    assert overview["approval_rate"] == 0.75
    assert overview["median_decision_seconds"] is not None

    # Coder, tester, reviewer and its revision, at $24.20 each. The plan is shared by tasks.
    pr = data["pull_requests"][0]
    assert pr["pr_number"] == 101 and pr["cost"] == pytest.approx(24.2 * 4)
    assert {a["agent"] for a in data["by_agent"]} == {"coder", "tester", "reviewer", "planner"}


def test_insights_with_no_data(client):
    overview = client.get("/api/insights").json()["overview"]
    assert overview["approval_rate"] is None and overview["average_pr_cost"] is None


def test_edited_approvals_are_counted_separately(client):
    client.post("/api/requirements", json=REQ)
    p = pending(client)[0]
    client.put(f"/api/proposals/{p['id']}", json={
        "expected_hash": p["payload_hash"], "payload": {"summary": "Edited by a person"}})
    p = pending(client)[0]
    approve(client, p)
    overview = client.get("/api/insights").json()["overview"]
    assert overview["approved_as_is"] == 0 and overview["approved_after_edit"] == 1


# Compliance ---------------------------------------------------------------------------------


def export(client, start=TODAY, end=TODAY):
    resp = client.get("/api/compliance/export", params={"start": start, "end": end})
    assert resp.status_code == 200, resp.text
    return zipfile.ZipFile(io.BytesIO(resp.content))


def test_evidence_pack_is_complete_and_signed(client):
    run_to_pr(client)
    pack = export(client)
    assert set(pack.namelist()) == {
        "README.txt", "summary.json", "control_checks.json", "decisions.csv",
        "github_writes.csv", "access_log.csv", "audit_events.jsonl", "manifest.json",
    }
    manifest = json.loads(pack.read("manifest.json"))
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(pack.read(name)).hexdigest() == digest
    expected = hmac.new(vault.audit_key(), json.dumps(manifest["files"], sort_keys=True).encode(),
                        hashlib.sha256).hexdigest()
    assert manifest["signature"] == expected

    summary = json.loads(pack.read("summary.json"))
    assert summary["audit_chain"]["verified"] is True
    assert "Not a certification" in summary["note"]
    writes = list(csv.DictReader(io.StringIO(pack.read("github_writes.csv").decode())))
    assert writes[0]["approved_by"] == USER


def test_the_export_itself_is_audited(client):
    export(client)
    event = client.get("/api/audit?action=compliance.").json()["events"][0]
    assert event["actor"] == USER and event["data"]["chain_verified"] is True


def checks(pack):
    return {c["check"]: c for c in json.loads(pack.read("control_checks.json"))}


def test_check_passes_for_a_properly_approved_write(client):
    run_to_pr(client)
    check = checks(export(client))["Every GitHub write matches a human approval of the same content"]
    assert check["passed"] is True and check["tested"] == 1


def test_self_approval_is_reported_for_review(client):
    client.post("/api/requirements", json=REQ)
    approve(client, pending(client)[0])
    check = checks(export(client))[
        "Work is approved by someone other than the person who requested it"]
    assert check["passed"] is False and len(check["exceptions"]) == 1


def test_a_write_with_no_matching_approval_is_an_exception(client):
    """Simulates a forged audit event claiming a write nobody approved."""
    from app import audit
    from app.db import write_tx

    with write_tx() as s:
        audit.record(s, actor_type="system", actor="countersign", action="github.pr_opened",
                     subject_type="proposal", subject_id="forged", data={"payload_hash": "x"})
    check = checks(export(client))["Every GitHub write matches a human approval of the same content"]
    assert check["passed"] is False and check["exceptions"] == ["forged"]


def test_spreadsheet_formulas_are_neutralised(client):
    client.post("/api/requirements", json={**REQ, "title": "=HYPERLINK(1) ok"})
    p = pending(client)[0]
    client.put(f"/api/proposals/{p['id']}", json={
        "expected_hash": p["payload_hash"], "payload": {"summary": "x"}})
    p = pending(client)[0]
    client.post(f"/api/proposals/{p['id']}/approve", json={
        "expected_hash": p["payload_hash"], "note": "=cmd|'/c calc'!A1"})
    rows = list(csv.DictReader(io.StringIO(export(client).read("decisions.csv").decode())))
    assert rows[0]["note"].startswith("'=")


def test_invalid_dates_are_refused(client):
    assert client.get("/api/compliance/export",
                      params={"start": "2026-02-01", "end": "2026-01-01"}).status_code == 422
    assert client.get("/api/compliance/export",
                      params={"start": "nope", "end": "2026-01-01"}).status_code == 422


def test_period_filter_excludes_other_days(client):
    client.post("/api/requirements", json=REQ)
    pack = export(client, "2020-01-01", "2020-01-02")
    assert json.loads(pack.read("summary.json"))["counts"]["events"] == 0


