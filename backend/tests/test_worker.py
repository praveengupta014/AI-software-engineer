"""Durability of the job queue: nothing is lost, duplicated or written by a stale worker."""

import anthropic
import httpx2
import pytest
from sqlalchemy import select

from app import pipeline, worker
from app.db import read_session, write_tx
from app.github_client import GitHubError
from app.models import AgentRun, Proposal, WorkerPresence, iso_in
from tests.fakes import DEMO_REPO, ScriptedLLM

REQ = {"title": "Rate limit login", "body": "Stop password guessing on login.", "repo": DEMO_REPO}


@pytest.fixture
def queued(client, monkeypatch):
    """A queued run that nothing has picked up yet."""
    monkeypatch.setattr(pipeline.Backends, "notify", lambda self, run_id: None)
    client.post("/api/requirements", json=REQ)
    with read_session() as s:
        return s.scalar(select(AgentRun.id))


def run_row(run_id):
    with read_session() as s:
        return s.get(AgentRun, run_id)


def proposals():
    with read_session() as s:
        return s.scalars(select(Proposal)).all()


def expire_lease(run_id):
    with write_tx() as s:
        s.get(AgentRun, run_id).heartbeat_at = iso_in(-1000)


def test_runs_wait_in_the_queue_until_a_worker_claims_them(client, queued):
    assert run_row(queued).status == "queued"
    assert worker.claim_next("w1") == (queued, 1)
    row = run_row(queued)
    assert (row.status, row.locked_by, row.attempts) == ("running", "w1", 1)
    assert worker.claim_next("w2") is None


def test_dead_worker_loses_its_lease_and_another_finishes_the_run(client, queued):
    worker.claim_next("dead")
    expire_lease(queued)
    worker.reap_expired()
    assert run_row(queued).status == "queued"

    run_id, attempt = worker.claim_next("alive")
    assert attempt == 2
    pipeline.execute_run(run_id, attempt)
    assert run_row(queued).status == "done" and len(proposals()) == 1
    actions = [e["action"] for e in client.get("/api/audit?limit=200").json()["events"]]
    assert "run.recovered" in actions
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_a_healthy_lease_is_left_alone(client, queued):
    worker.claim_next("w1")
    worker.heartbeat("w1", [queued])
    worker.reap_expired()
    assert run_row(queued).status == "running"


def test_stale_worker_cannot_write_after_losing_its_lease(client, queued):
    """The dangerous case: paused, not dead. It wakes after another worker took over."""
    run_id, stale_attempt = worker.claim_next("paused")
    expire_lease(queued)
    worker.reap_expired()
    fresh = worker.claim_next("alive")
    pipeline.execute_run(*fresh)
    assert len(proposals()) == 1

    pipeline.execute_run(run_id, stale_attempt)  # the old worker finally wakes up
    assert len(proposals()) == 1
    assert run_row(queued).attempts == 2 and run_row(queued).status == "done"


def test_run_that_keeps_dying_fails_visibly_instead_of_looping(client, queued):
    for _ in range(3):
        worker.claim_next("w")
        expire_lease(queued)
        worker.reap_expired()
    assert run_row(queued).status == "failed"
    assert "stopped responding" in run_row(queued).error
    assert worker.claim_next("w") is None


def transient():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=request)


class _Flaky(ScriptedLLM):
    def __init__(self, failures, error):
        super().__init__()
        self.failures, self.error = failures, error

    def turn(self, **kwargs):
        if self.failures:
            self.failures -= 1
            raise self.error()
        return super().turn(**kwargs)


def test_transient_failure_retries_then_succeeds(client, queued, monkeypatch):
    monkeypatch.setattr(pipeline.backends, "llm", _Flaky(1, transient))
    pipeline.execute_run(*worker.claim_next("w"))
    row = run_row(queued)
    assert row.status == "queued" and row.locked_by is None

    pipeline.execute_run(*worker.claim_next("w"))
    assert run_row(queued).status == "done" and run_row(queued).attempts == 2


def test_transient_failure_gives_up_after_max_attempts(client, queued, monkeypatch):
    monkeypatch.setattr(pipeline.backends, "llm", _Flaky(99, transient))
    worker.drain("w")
    row = run_row(queued)
    assert (row.status, row.attempts) == ("failed", 3)


def test_retry_waits_for_its_backoff(client, queued, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "retry_base_seconds", 60.0)
    monkeypatch.setattr(pipeline.backends, "llm", _Flaky(1, transient))
    pipeline.execute_run(*worker.claim_next("w"))
    assert worker.claim_next("w") is None


def test_permanent_failure_is_not_retried(client, queued, monkeypatch):
    monkeypatch.setattr(pipeline.backends, "llm", _Flaky(99, lambda: GitHubError(404, "gone")))
    pipeline.execute_run(*worker.claim_next("w"))
    assert run_row(queued).status == "failed" and run_row(queued).attempts == 1


def test_stopping_a_queued_run_takes_effect_immediately(client, queued):
    assert client.post(f"/api/runs/{queued}/stop").status_code == 202
    assert run_row(queued).status == "failed"
    assert worker.claim_next("w") is None


def test_clean_shutdown_returns_work_without_using_an_attempt(client, queued):
    worker.heartbeat("w1", [])
    worker.claim_next("w1")
    worker.release("w1")
    row = run_row(queued)
    assert (row.status, row.attempts, row.locked_by) == ("queued", 0, None)
    with read_session() as s:
        assert s.scalar(select(WorkerPresence)) is None


def test_stranded_external_proposal_becomes_retryable(client, monkeypatch):
    with write_tx() as s:
        s.add(Proposal(id="stuck", kind="pull_request", title="t", repo=DEMO_REPO,
                       status="approved", payload={}, payload_hash="h", decided_at=iso_in(-1000),
                       risk_flags=[]))
    worker.reap_expired()
    with read_session() as s:
        assert s.get(Proposal, "stuck").status == "failed"


def test_recently_approved_proposal_is_left_alone(client):
    with write_tx() as s:
        s.add(Proposal(id="active", kind="pull_request", title="t", repo=DEMO_REPO,
                       status="approved", payload={}, payload_hash="h", decided_at=iso_in(-5),
                       risk_flags=[]))
    worker.reap_expired()
    with read_session() as s:
        assert s.get(Proposal, "active").status == "approved"


def test_settings_lists_live_workers(client):
    worker.heartbeat("worker-a", [])
    assert [w["id"] for w in client.get("/api/settings").json()["workers"]] == ["worker-a"]
