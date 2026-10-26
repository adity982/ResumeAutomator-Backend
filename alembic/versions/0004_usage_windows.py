"""Shared authenticated-user usage windows."""
from alembic import op
import sqlalchemy as sa

revision = "0004_usage"
down_revision = "0003_portfolio"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("usage_windows", sa.Column("key", sa.String(64), primary_key=True), sa.Column("count", sa.Integer(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_usage_windows_expires_at", "usage_windows", ["expires_at"])


def downgrade():
    op.drop_table("usage_windows")
