"""Runs queued agent work. Start as many as you like: python -m app.worker

A run is claimed under a lease that the worker renews with heartbeats. If a worker dies, its
lease expires and another worker picks the run up. Agents only read and propose, so running one
again is safe; the attempt number fences off a stalled worker that wakes up late, so it cannot
write results for a run that has moved on.
"""

import logging
import os
import signal
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, select

from . import audit, notifications, pipeline
from .config import get_settings
from .db import init_db, read_session, write_tx
from .models import AgentRun, Proposal, Task, WorkerPresence, iso_in, now_iso

log = logging.getLogger("countersign.worker")

STRANDED_PROPOSAL_SECONDS = 300


def claim_next(worker_id: str) -> tuple[str, int] | None:
    now = now_iso()
    with read_session() as s:  # cheap check, so idle workers do not take the write lock
        waiting = s.scalar(
            select(AgentRun.id)
            .where(AgentRun.status == "queued", AgentRun.available_at <= now)
            .limit(1)
        )
    if waiting is None:
        return None
    with write_tx() as s:
        run = s.scalar(
            select(AgentRun)
            .where(AgentRun.status == "queued", AgentRun.available_at <= now)
            .order_by(AgentRun.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None
        run.status = "running"
        run.attempts += 1
        run.locked_by = worker_id
        run.heartbeat_at = now_iso()
        return run.id, run.attempts


def heartbeat(worker_id: str, run_ids: list[str]) -> None:
    with write_tx() as s:
        s.merge(WorkerPresence(id=worker_id, last_seen=now_iso()))
        if run_ids:
            for run in s.scalars(
                select(AgentRun).where(AgentRun.id.in_(run_ids), AgentRun.locked_by == worker_id)
            ):
                run.heartbeat_at = now_iso()


def reap_expired() -> None:
    """Take back runs whose worker stopped renewing its lease."""
    settings = get_settings()
    cutoff = iso_in(-settings.lease_seconds)
    with read_session() as s:
        expired = s.scalars(
            select(AgentRun.id).where(
                AgentRun.status == "running", AgentRun.heartbeat_at < cutoff
            )
        ).all()
    for run_id in expired:
        with write_tx() as s:
            run = s.get(AgentRun, run_id)
            if run.status != "running" or run.heartbeat_at >= cutoff:
                continue  # another worker got here first, or the lease was renewed
            if run.attempts < settings.run_max_attempts:
                worker = run.locked_by
                run.status, run.locked_by, run.heartbeat_at = "queued", None, None
                run.available_at = now_iso()
                audit.record(
                    s, actor_type="system", actor="countersign", action="run.recovered",
                    subject_type="run", subject_id=run.id, requirement_id=run.requirement_id,
                    data={"lost_worker": worker, "attempts": run.attempts},
                )
                continue
        pipeline.fail_run(run_id, "The worker running this stopped responding repeatedly")
    _reap_stranded_proposals()
    with write_tx() as s:
        s.execute(delete(WorkerPresence).where(WorkerPresence.last_seen < cutoff))


def _reap_stranded_proposals() -> None:
    """Approved, but the API process died before GitHub answered. The write may have landed;
    opening a PR is retry-safe, so hand it back to a person to retry."""
    cutoff = iso_in(-STRANDED_PROPOSAL_SECONDS)
    with read_session() as s:
        ids = s.scalars(
            select(Proposal.id).where(Proposal.status == "approved", Proposal.decided_at < cutoff)
        ).all()
    for proposal_id in ids:
        with write_tx() as s:
            p = s.get(Proposal, proposal_id)
            if p.status != "approved":
                continue
            p.status, p.error = "failed", "Interrupted during the GitHub action"
            if p.task_id:
                s.get(Task, p.task_id).state = "blocked"
            audit.record(
                s, actor_type="system", actor="countersign", action="github.write_failed",
                subject_type="proposal", subject_id=p.id, requirement_id=p.requirement_id,
                data={"error": p.error},
            )


def release(worker_id: str) -> None:
    """Hand back work on a clean shutdown, without charging it an attempt."""
    with write_tx() as s:
        runs = s.scalars(
            select(AgentRun).where(AgentRun.locked_by == worker_id, AgentRun.status == "running")
        ).all()
        for run in runs:
            run.status, run.locked_by, run.heartbeat_at = "queued", None, None
            run.attempts = max(0, run.attempts - 1)
            run.available_at = now_iso()
            audit.record(
                s, actor_type="system", actor="countersign", action="run.released",
                subject_type="run", subject_id=run.id, requirement_id=run.requirement_id,
                data={"worker": worker_id},
            )
        s.execute(delete(WorkerPresence).where(WorkerPresence.id == worker_id))


def drain(worker_id: str = "inline") -> None:
    """Process everything queued on this thread."""
    while claimed := claim_next(worker_id):
        pipeline.execute_run(*claimed)


class Worker:
    def __init__(self) -> None:
        settings = get_settings()
        self.id = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self.stop = threading.Event()
        self._settings = settings
        self._pool = ThreadPoolExecutor(max_workers=settings.worker_concurrency)
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    def _run(self, run_id: str, attempt: int) -> None:
        try:
            pipeline.execute_run(run_id, attempt)
        except Exception:  # execute_run records failures; this is only a last resort
            log.exception("Run %s crashed", run_id)
        finally:
            with self._lock:
                self._active.pop(run_id, None)

    def _tick(self) -> None:
        pipeline.backends.refresh()
        while True:
            with self._lock:
                if len(self._active) >= self._settings.worker_concurrency:
                    return
            claimed = claim_next(self.id)
            if claimed is None:
                return
            with self._lock:
                self._active[claimed[0]] = claimed[1]
            self._pool.submit(self._run, *claimed)

    def _maintain(self) -> None:
        with self._lock:
            active = list(self._active)
        heartbeat(self.id, active)
        reap_expired()
        notifications.recover_stuck(iso_in(-self._settings.lease_seconds))

    def run(self) -> None:
        log.info("Worker %s started", self.id)
        next_maintenance = 0.0
        while not self.stop.is_set():
            try:
                if time.monotonic() >= next_maintenance:
                    self._maintain()
                    next_maintenance = time.monotonic() + self._settings.heartbeat_seconds
                self._tick()
                notifications.deliver_pending()
            except Exception:  # a database blip must not end the worker
                log.exception("Worker loop error; retrying")
            self.stop.wait(self._settings.worker_poll_seconds)
        release(self.id)
        self._pool.shutdown(wait=False, cancel_futures=True)
        log.info("Worker %s stopped", self.id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.database_url, migrate=settings.is_sqlite)
    pipeline.backends.configure()
    worker = Worker()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: worker.stop.set())
    worker.run()
    os._exit(0)  # in-flight runs were released; do not wait for their model calls


if __name__ == "__main__":
    main()
