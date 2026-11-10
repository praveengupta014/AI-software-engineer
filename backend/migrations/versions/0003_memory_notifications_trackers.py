"""Repository memory, outbound notification outbox, issue-tracker links."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "repo_memories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("applies_to", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_proposal_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_repo_memories_repo", "repo_memories", ["repo"])
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("proposal_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_notification_queue", "notification_outbox", ["status", "available_at"])
    op.create_table(
        "tracker_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("project_key", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("base_branch", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("provider", "project_key", name="uq_tracker_links_project"),
    )
