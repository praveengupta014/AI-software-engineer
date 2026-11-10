"""End-to-end behaviour of the approval gate and audit trail through the HTTP API, on the
scripted model and the in-memory GitHub."""

import pytest
from sqlalchemy import text

from app import pipeline
from app.db import get_engine
from app.github_client import GitHubError
from app.llm import ToolCall, Turn
from tests.fakes import DEMO_REPO

REQ = {"title": "Rate limit login", "body": "Stop password guessing on login.", "repo": DEMO_REPO}


def pending(client):
    return client.get("/api/overview").json()["pending"]


def detail(client, proposal_id):
    return client.get(f"/api/proposals/{proposal_id}").json()


def approve(client, proposal, **extra):
    return client.post(
        f"/api/proposals/{proposal['id']}/approve",
        json={"expected_hash": proposal["payload_hash"], **extra},
    )


def actions(client):
    return [e["action"] for e in client.get("/api/audit?limit=200").json()["events"]]


def start_requirement(client):
    return client.post("/api/requirements", json=REQ).json()["id"]


def first_task(client, req_id):
    return client.get(f"/api/requirements/{req_id}").json()["tasks"][0]


def fake_github():
    return pipeline.backends.github


def to_code_proposal(client):
    req_id = start_requirement(client)
    assert approve(client, pending(client)[0]).status_code == 200
    task = first_task(client, req_id)
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 202
    return req_id, task, pending(client)[0]


def test_auth_required(client):
    resp = client.get("/api/overview", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_full_flow_opens_pr_only_after_every_approval(client):
    req_id, _task, code = to_code_proposal(client)
    assert code["kind"] == "code"
    assert fake_github().pulls.keys() == {42}

    assert approve(client, code).status_code == 200  # tester starts automatically
    tests = pending(client)[0]
    assert tests["kind"] == "tests"
    assert fake_github().pulls.keys() == {42}

    assert approve(client, tests).status_code == 200  # PR proposal is built, not opened
    pr = detail(client, pending(client)[0]["id"])
    assert pr["kind"] == "pull_request"
    assert {f["path"] for f in pr["payload"]["files"]} == {
        "app/rate_limit.py", "tests/test_rate_limit.py",
    }
    assert fake_github().pulls.keys() == {42}

    assert approve(client, pr).status_code == 200
    assert 101 in fake_github().pulls
    assert first_task(client, req_id)["pr_number"] == 101

    review = pending(client)[0]  # reviewer ran automatically on the new PR
    assert review["kind"] == "review"
    assert fake_github().reviews == []

    assert approve(client, review).status_code == 200
    assert len(fake_github().reviews) == 1
    assert first_task(client, req_id)["stage"] == "done"

    seen = actions(client)
    for action in ("proposal.approved", "llm.turn", "tool.called", "github.pr_opened",
                   "github.review_posted"):
        assert action in seen
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_approval_is_bound_to_the_exact_content(client):
    _, _, code = to_code_proposal(client)
    full = detail(client, code["id"])
    edit = client.put(
        f"/api/proposals/{code['id']}",
        json={
            "expected_hash": code["payload_hash"],
            "payload": {"files": [{"path": "app/rate_limit.py", "content": "# edited\n"}]},
        },
    )
    assert edit.status_code == 200
    stale = approve(client, full)
    assert stale.status_code == 409
    fresh = detail(client, code["id"])
    assert fresh["revision"] == 2 and fresh["edited_by"] == "Asha"
    assert approve(client, fresh).status_code == 200
    assert "proposal.edited" in actions(client)


def test_a_proposal_can_only_be_decided_once(client):
    _, _, code = to_code_proposal(client)
    assert client.post(f"/api/proposals/{code['id']}/reject", json={"note": "no thanks"}).is_success
    assert approve(client, code).status_code == 409


def test_high_risk_needs_explicit_acknowledgement(client):
    _, _, code = to_code_proposal(client)
    client.put(
        f"/api/proposals/{code['id']}",
        json={
            "expected_hash": code["payload_hash"],
            "payload": {"files": [{"path": "app/rate_limit.py",
                                   "content": "KEY = 'AKIAABCDEFGHIJKLMNOP'\n"}]},
        },
    )
    risky = detail(client, code["id"])
    assert [f["code"] for f in risky["risk_flags"]] == ["possible_secret"]
    assert approve(client, risky).status_code == 422
    assert approve(client, risky, acknowledged_risks=True).status_code == 200


def test_request_changes_reruns_agent_with_feedback(client):
    _req_id, _task, code = to_code_proposal(client)
    resp = client.post(
        f"/api/proposals/{code['id']}/request-changes", json={"note": "Use a monotonic clock"}
    )
    assert resp.status_code == 200
    revised = pending(client)[0]
    assert revised["id"] != code["id"]
    assert "Revised after reviewer feedback" in revised["summary"]
    assert detail(client, code["id"])["status"] == "changes_requested"


def test_rejected_task_can_be_restarted(client):
    req_id, task, code = to_code_proposal(client)
    client.post(f"/api/proposals/{code['id']}/reject", json={"note": "wrong approach"})
    assert first_task(client, req_id)["state"] == "blocked"
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 202
    assert pending(client)[0]["kind"] == "code"


def test_failed_github_write_is_recorded_and_retryable(client, monkeypatch):
    _, _, code = to_code_proposal(client)
    approve(client, code)
    approve(client, pending(client)[0])
    pr = pending(client)[0]

    def boom(repo, payload):
        raise GitHubError(403, "Resource not accessible")

    with monkeypatch.context() as m:
        m.setattr(fake_github(), "open_pull_request", boom)
        assert approve(client, pr).status_code == 502
    failed = detail(client, pr["id"])
    assert failed["status"] == "failed" and "403" in failed["error"]
    assert "github.write_failed" in actions(client)

    assert client.post(f"/api/proposals/{pr['id']}/retry").status_code == 200
    assert detail(client, pr["id"])["status"] == "executed"


def test_external_execution_refuses_unapproved_proposals(client):
    _, _, code = to_code_proposal(client)
    approve(client, code)
    approve(client, pending(client)[0])
    pr = pending(client)[0]
    with pytest.raises(pipeline.PipelineError):
        pipeline._execute_external(pr["id"], "attacker")
    assert fake_github().pulls.keys() == {42}


def test_inline_comment_off_the_diff_folds_into_body(client):
    client.post("/api/reviews", json={"repo": DEMO_REPO, "pr_number": 42})
    review = pending(client)[0]
    assert approve(client, review).status_code == 200
    posted = fake_github().reviews[0]
    assert posted["comments"] == []  # line 1 is outside PR 42's diff hunk
    assert "app/auth.py:1" in posted["body"]


def test_audit_table_rejects_tampering_and_verify_detects_it(client):
    start_requirement(client)
    engine = get_engine()
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET actor = 'mallory' WHERE seq = 2"))
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events WHERE seq = 2"))

    on_table = " ON audit_events" if engine.dialect.name == "postgresql" else ""
    with engine.begin() as conn:  # an attacker with DDL access
        conn.execute(text(f"DROP TRIGGER audit_no_update{on_table}"))
        conn.execute(text("UPDATE audit_events SET actor = 'mallory' WHERE seq = 2"))
    result = client.get("/api/audit/verify").json()
    assert result == {
        "ok": False, "checked": 1, "first_bad_seq": 2,
        "reason": "event content does not match its hash", "head": None,
    }


def test_audit_detects_deleted_rows(client):
    start_requirement(client)
    engine = get_engine()
    on_table = " ON audit_events" if engine.dialect.name == "postgresql" else ""
    with engine.begin() as conn:
        conn.execute(text(f"DROP TRIGGER audit_no_delete{on_table}"))
        conn.execute(text("DELETE FROM audit_events WHERE seq = 3"))
    result = client.get("/api/audit/verify").json()
    assert result["ok"] is False and result["first_bad_seq"] == 4


class _HostileLLM:
    """Plays a prompt-injected model trying to escape its sandbox."""

    def __init__(self, calls):
        self.calls = iter(calls)

    def turn(self, **_):
        return Turn([], next(self.calls), "", "tool_use", "hostile", None)


def test_agent_cannot_call_write_tools_or_read_outside_repo(client, monkeypatch):
    llm = _HostileLLM([
        [ToolCall("1", "open_pull_request", {"title": "pwned"})],
        [ToolCall("2", "read_file", {"path": "../../etc/passwd"})],
        [ToolCall("3", "submit", {"summary": "s", "tasks": [{
            "title": "t", "description": "d", "acceptance_criteria": ["c"],
            "files_likely_touched": []}], "open_questions": []})],
    ])
    monkeypatch.setattr(pipeline.backends, "llm", llm)
    start_requirement(client)
    assert fake_github().pulls.keys() == {42}
    assert pending(client)[0]["kind"] == "plan"  # still only a proposal
    tool_events = client.get("/api/audit?action=tool.called").json()["events"]
    results = {e["data"]["tool"]: e["data"]["is_error"] for e in tool_events}
    assert results == {"open_pull_request": True, "read_file": True, "submit": False}


def test_agent_paths_outside_repo_are_refused(client, monkeypatch):
    bad = {"summary": "s", "rationale": "r", "commit_message": "m",
           "files": [{"path": ".git/hooks/pre-commit", "action": "create", "content": "x"}]}
    good = {**bad, "files": [{"path": "app/new.py", "action": "create", "content": "x"}]}
    req_id = start_requirement(client)
    approve(client, pending(client)[0])
    task = first_task(client, req_id)
    monkeypatch.setattr(pipeline.backends, "llm", _HostileLLM([
        [ToolCall("1", "submit", bad)], [ToolCall("2", "submit", good)],
    ]))
    client.post(f"/api/tasks/{task['id']}/start")
    files = detail(client, pending(client)[0]["id"])["payload"]["files"]
    assert [f["path"] for f in files] == ["app/new.py"]


def test_agent_failure_blocks_task_and_is_audited(client, monkeypatch):
    req_id = start_requirement(client)
    approve(client, pending(client)[0])
    task = first_task(client, req_id)
    refusal = Turn([], [], "", "refusal", "m", "req_1", refusal={"category": "cyber"})
    monkeypatch.setattr(pipeline.backends, "llm", _HostileLLM([]))
    monkeypatch.setattr(pipeline.backends.llm, "turn", lambda **_: refusal, raising=False)
    client.post(f"/api/tasks/{task['id']}/start")
    assert first_task(client, req_id)["state"] == "blocked"
    assert "run.failed" in actions(client)


def test_stopping_a_run_ends_it_at_the_next_turn(client, monkeypatch):
    from app.db import write_tx
    from app.models import AgentRun

    llm = pipeline.backends.llm
    original = llm.turn

    def stop_mid_run(**kwargs):
        with write_tx() as s:
            run = s.query(AgentRun).filter_by(agent="planner").one()
            run.stop_requested_by = "Asha"
        return original(**kwargs)

    monkeypatch.setattr(llm, "turn", stop_mid_run)
    req_id = start_requirement(client)
    runs = client.get(f"/api/requirements/{req_id}").json()["runs"]
    assert runs[0]["status"] == "failed" and runs[0]["error"] == "Stopped by Asha"
    assert pending(client) == []
    monkeypatch.setattr(llm, "turn", original)
    assert client.post(f"/api/requirements/{req_id}/replan").status_code == 202
    assert pending(client)[0]["kind"] == "plan"


def test_active_runs_expose_recent_steps(client):
    from app.db import read_session
    from app.main import _live_run_out
    from app.models import AgentRun

    start_requirement(client)
    with read_session() as s:
        out = _live_run_out(s, s.query(AgentRun).first())
    assert [x["tool"] for x in out["steps"]][:2] == ["list_files", "read_file"]


@pytest.mark.parametrize("exc_factory, expected", [
    (lambda: GitHubError(401, "Bad credentials"), "Update it in Settings"),
    (lambda: GitHubError(404, "Not Found"), "token can access it"),
    (lambda: GitHubError(409, "Git Repository is empty."), "no commits yet"),
])
def test_failures_explain_what_to_do(exc_factory, expected):
    assert expected in pipeline._explain(exc_factory())
