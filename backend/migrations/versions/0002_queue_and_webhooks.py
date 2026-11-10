"""Durable agent queue, worker presence, webhook de-duplication, issue links."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("available_at", sa.String(), nullable=False, server_default=""))
        batch.add_column(sa.Column("locked_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.String(), nullable=True))
    op.create_index("ix_agent_runs_queue", "agent_runs", ["status", "available_at"])

    with op.batch_alter_table("requirements") as batch:
        batch.add_column(sa.Column("source_url", sa.String(), nullable=True))

    op.create_index("uq_proposals_run_id", "proposals", ["run_id"], unique=True)

    op.create_table(
        "webhook_deliveries",
        sa.Column("delivery_id", sa.String(), primary_key=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("received_at", sa.String(), nullable=False),
    )
    op.create_table(
        "workers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("last_seen", sa.String(), nullable=False),
    )
