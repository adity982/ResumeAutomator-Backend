"""Add evidence, follow-up, score provenance, and interview preparation data."""

from alembic import op
import sqlalchemy as sa


revision = "0002_market_features"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    analysis_columns = {column["name"] for column in inspector.get_columns("analysis_records")}
    if "input_fingerprint" not in analysis_columns:
        op.add_column("analysis_records", sa.Column("input_fingerprint", sa.String(length=64), server_default="", nullable=False))
    if "methodology" not in analysis_columns:
        op.add_column("analysis_records", sa.Column("methodology", sa.JSON(), server_default=sa.text("'{}'"), nullable=False))
    inspector = sa.inspect(op.get_bind())
    analysis_indexes = {index["name"] for index in inspector.get_indexes("analysis_records")}
    if "ix_analysis_records_input_fingerprint" not in analysis_indexes:
        op.create_index("ix_analysis_records_input_fingerprint", "analysis_records", ["input_fingerprint"])
    interview_columns = {column["name"] for column in inspector.get_columns("interview_sessions")}
    if "prep_brief" not in interview_columns:
        op.add_column("interview_sessions", sa.Column("prep_brief", sa.JSON(), server_default=sa.text("'{}'"), nullable=False))

    inspector = sa.inspect(op.get_bind())
    if "career_evidence" not in inspector.get_table_names():
        op.create_table(
        "career_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_uid", sa.String(length=128), sa.ForeignKey("users.uid", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=500), server_default="", nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_career_evidence_user_uid", "career_evidence", ["user_uid"])
        op.create_index("ix_evidence_user_updated", "career_evidence", ["user_uid", "updated_at"])

    inspector = sa.inspect(op.get_bind())
    if "follow_up_tasks" not in inspector.get_table_names():
        op.create_table(
        "follow_up_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_uid", sa.String(length=128), sa.ForeignKey("users.uid", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(length=32), server_default="follow_up", nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_follow_up_tasks_user_uid", "follow_up_tasks", ["user_uid"])
        op.create_index("ix_follow_up_application", "follow_up_tasks", ["application_id"])
        op.create_index("ix_follow_up_user_due", "follow_up_tasks", ["user_uid", "due_at"])


def downgrade() -> None:
    op.drop_table("follow_up_tasks")
    op.drop_table("career_evidence")
    op.drop_index("ix_analysis_records_input_fingerprint", table_name="analysis_records")
    op.drop_column("interview_sessions", "prep_brief")
    op.drop_column("analysis_records", "methodology")
    op.drop_column("analysis_records", "input_fingerprint")
