"""The schema as it stood before migrations. Installs that already have these tables keep them
and are simply marked as up to this revision."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None

_SQLITE_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
       BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
       BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END""",
]
_POSTGRES_TRIGGERS = [
    """CREATE FUNCTION audit_append_only() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'audit_events is append-only'; END;
       $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
       FOR EACH ROW EXECUTE FUNCTION audit_append_only()""",
    """CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
       FOR EACH ROW EXECUTE FUNCTION audit_append_only()""",
    """CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events
       FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only()""",
]


def _id():
    return sa.Column("id", sa.String(), primary_key=True)


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("audit_events"):
        return

    op.create_table(
        "users", _id(),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("user_name", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
    )
    op.create_table(
        "requirements", _id(),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("base_branch", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "tasks", _id(),
        sa.Column("requirement_id", sa.String(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(), nullable=True),
    )
    op.create_index("ix_tasks_requirement_id", "tasks", ["requirement_id"])
    op.create_table(
        "agent_runs", _id(),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("requirement_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("stop_requested_by", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("turns", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
    )
    op.create_index("ix_agent_runs_requirement_id", "agent_runs", ["requirement_id"])
    op.create_index("ix_agent_runs_task_id", "agent_runs", ["task_id"])
    op.create_table(
        "proposals", _id(),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("requirement_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("edited_by", sa.String(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.String(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_proposals_requirement_id", "proposals", ["requirement_id"])
    op.create_index("ix_proposals_task_id", "proposals", ["task_id"])
    op.create_index("ix_proposals_status", "proposals", ["status"])
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("ts", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("requirement_id", sa.String(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(), nullable=False),
        sa.Column("hash", sa.String(), nullable=False),
    )
    op.create_index("ix_audit_events_actor_type", "audit_events", ["actor_type"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_subject_id", "audit_events", ["subject_id"])
    op.create_index("ix_audit_events_requirement_id", "audit_events", ["requirement_id"])

    for statement in _POSTGRES_TRIGGERS if bind.dialect.name == "postgresql" else _SQLITE_TRIGGERS:
        op.execute(statement)
