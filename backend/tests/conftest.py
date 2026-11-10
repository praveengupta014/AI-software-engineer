import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import auth, main, pipeline, worker
from app.config import get_settings
from app.main import app
from tests.fakes import FakeGitHub, ScriptedLLM

USER = "Asha"
PASSWORD = "correct horse battery"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def reset_postgres(url: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture
def anonymous(tmp_path, monkeypatch):
    """A fresh install: nothing set up, and external credential checks stubbed out.

    Set TEST_DATABASE_URL to run the whole suite against PostgreSQL.
    """
    for name in ("ANTHROPIC_API_KEY", "COUNTERSIGN_GITHUB_TOKEN", "COUNTERSIGN_AUDIT_KEY",
                 "COUNTERSIGN_SLACK_WEBHOOK_URL", "COUNTERSIGN_PUBLIC_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COUNTERSIGN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COUNTERSIGN_EMBEDDED_WORKER", "false")
    monkeypatch.setenv("COUNTERSIGN_RETRY_BASE_SECONDS", "0")
    if TEST_DATABASE_URL:
        reset_postgres(TEST_DATABASE_URL)
        monkeypatch.setenv("COUNTERSIGN_DATABASE_URL", TEST_DATABASE_URL)
        from app.db import run_migrations

        run_migrations(TEST_DATABASE_URL)
    get_settings.cache_clear()
    auth._failures.clear()
    # Run queued work inline so tests see results without a background worker.
    monkeypatch.setattr(pipeline.Backends, "notify", lambda self, run_id: worker.drain())
    monkeypatch.setattr(main, "check_key", lambda key, model: None)
    monkeypatch.setattr(main, "check_token", lambda token, url: ("asha", None))
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def client(anonymous, monkeypatch):
    resp = anonymous.post("/api/setup", json={
        "name": USER, "password": PASSWORD, "anthropic_key": "sk-x", "github_token": "ghp-x",
    })
    assert resp.status_code == 201
    anonymous.headers["Authorization"] = f"Bearer {resp.json()['token']}"
    pipeline.backends.github = FakeGitHub()
    pipeline.backends.llm = ScriptedLLM()
    monkeypatch.setattr(pipeline.Backends, "refresh", lambda self: None)
    return anonymous
