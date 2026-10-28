"""Encrypted, owner-bound GitHub App authorization."""
from alembic import op
import sqlalchemy as sa

revision = "0005_github"
down_revision = "0004_usage"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("portfolio_sources", sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("github_connections",
        sa.Column("user_uid", sa.String(128), sa.ForeignKey("users.uid", ondelete="CASCADE"), primary_key=True),
        sa.Column("login", sa.String(100), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("github_authorizations",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("user_uid", sa.String(128), sa.ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("github_authorizations")
    op.drop_table("github_connections")
    op.drop_column("portfolio_sources", "is_private")
