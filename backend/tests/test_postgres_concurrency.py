"""Guarantees that only matter with several processes, so they need real PostgreSQL.
Run with TEST_DATABASE_URL set; skipped otherwise."""

import multiprocessing
import os

import pytest
from sqlalchemy import func, select

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="needs TEST_DATABASE_URL")


def _append_events(data_dir: str, process: int, count: int) -> None:
    os.environ.update(COUNTERSIGN_DATA_DIR=data_dir, COUNTERSIGN_DATABASE_URL=TEST_DATABASE_URL)
    from app import audit
    from app.config import get_settings
    from app.db import init_db, write_tx

    get_settings.cache_clear()
    init_db(TEST_DATABASE_URL, migrate=False)
    for i in range(count):
        with write_tx() as s:
            audit.record(s, actor_type="system", actor=f"p{process}", action="load.test",
                         subject_type="test", subject_id=str(i))


def _claim_all(data_dir: str, worker_id: str, results) -> None:
    os.environ.update(COUNTERSIGN_DATA_DIR=data_dir, COUNTERSIGN_DATABASE_URL=TEST_DATABASE_URL)
    from app.config import get_settings
    from app.db import init_db
    from app.worker import claim_next

    get_settings.cache_clear()
    init_db(TEST_DATABASE_URL, migrate=False)
    while claimed := claim_next(worker_id):
        results.append(claimed[0])


def _spawn(target, *arg_sets):
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=target, args=args) for args in arg_sets]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=120)
        assert p.exitcode == 0
    return context


def test_audit_chain_stays_linear_with_many_writing_processes(client):
    from app.audit import verify_chain
    from app.config import get_settings
    from app.db import read_session
    from app.models import AuditEvent

    data_dir = str(get_settings().data_dir)
    with read_session() as s:
        before = s.scalar(select(func.count()).select_from(AuditEvent))
    _spawn(_append_events, *[(data_dir, p, 60) for p in range(6)])

    result = verify_chain()
    assert result["ok"] is True, result
    assert result["checked"] == before + 360


def test_concurrent_workers_never_claim_the_same_run(client):
    from app.config import get_settings
    from app.db import write_tx
    from app.models import AgentRun

    with write_tx() as s:
        s.add_all([
            AgentRun(agent="reviewer", repo="o/r", pr_number=i, started_by="t") for i in range(120)
        ])
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        results = manager.list()
        data_dir = str(get_settings().data_dir)
        processes = [
            context.Process(target=_claim_all, args=(data_dir, f"w{n}", results)) for n in range(6)
        ]
        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=120)
            assert p.exitcode == 0
        claimed = list(results)
    assert len(claimed) == 120 and len(set(claimed)) == 120
