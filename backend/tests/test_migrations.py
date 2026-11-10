"""Schema migrations, including upgrading an install that predates them."""

import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401
from app.db import Base, run_migrations

OLD_SCHEMA = """
CREATE TABLE users (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL UNIQUE,
  password_hash VARCHAR NOT NULL, created_at VARCHAR NOT NULL);
CREATE TABLE sessions (token_hash VARCHAR PRIMARY KEY, user_name VARCHAR NOT NULL,
  expires_at VARCHAR NOT NULL);
CREATE TABLE requirements (id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL, body TEXT NOT NULL,
  repo VARCHAR NOT NULL, base_branch VARCHAR NOT NULL, status VARCHAR NOT NULL,
  created_by VARCHAR NOT NULL, created_at VARCHAR NOT NULL);
CREATE TABLE agent_runs (id VARCHAR PRIMARY KEY, agent VARCHAR NOT NULL, repo VARCHAR NOT NULL,
  requirement_id VARCHAR, task_id VARCHAR, pr_number INTEGER, feedback TEXT,
  stop_requested_by VARCHAR, status VARCHAR NOT NULL, model VARCHAR, turns INTEGER NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  cache_read_tokens INTEGER NOT NULL, error TEXT, started_by VARCHAR NOT NULL,
  created_at VARCHAR NOT NULL, finished_at VARCHAR);
CREATE TABLE proposals (id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, title VARCHAR NOT NULL,
  repo VARCHAR NOT NULL, run_id VARCHAR, requirement_id VARCHAR, task_id VARCHAR,
  status VARCHAR NOT NULL, payload JSON NOT NULL, payload_hash VARCHAR NOT NULL,
  revision INTEGER NOT NULL, edited_by VARCHAR, risk_flags JSON NOT NULL, decided_by VARCHAR,
  decided_at VARCHAR, decision_note TEXT, external_url VARCHAR, error TEXT,
  created_at VARCHAR NOT NULL);
CREATE TABLE audit_events (seq INTEGER PRIMARY KEY, ts VARCHAR NOT NULL,
  actor_type VARCHAR NOT NULL, actor VARCHAR NOT NULL, action VARCHAR NOT NULL,
  subject_type VARCHAR NOT NULL, subject_id VARCHAR NOT NULL, requirement_id VARCHAR,
  data JSON NOT NULL, prev_hash VARCHAR NOT NULL, hash VARCHAR NOT NULL);
"""


def diffs(url):
    with create_engine(url).connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)


def test_fresh_database_matches_the_models(tmp_path):
    url = f"sqlite:///{tmp_path}/fresh.db"
    run_migrations(url)
    assert diffs(url) == []


def test_upgrades_a_database_from_before_migrations_without_losing_rows(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO agent_runs (id, agent, repo, status, turns, input_tokens, output_tokens,"
        " cache_read_tokens, started_by, created_at)"
        " VALUES ('r1','planner','o/r','failed',1,2,3,0,'a','2026-01-01T00:00:00.000Z')"
    )
    conn.commit()
    conn.close()

    url = f"sqlite:///{path}"
    run_migrations(url)
    run_migrations(url)  # safe to repeat

    inspector = inspect(create_engine(url))
    assert "webhook_deliveries" in inspector.get_table_names()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT id, attempts, status FROM agent_runs").fetchall() == [
        ("r1", 0, "failed")
    ]
