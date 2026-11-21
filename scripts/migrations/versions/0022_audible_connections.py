"""
Each user's Audible connection (audible_connections): My World as a device
of their Audible account, what it signs with and the refresh token kept to
deregister it, each sealed with a key derived from SECRET_KEY.
Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "audible_connections" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "audible_connections",
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("marketplace", sa.String(length=10), nullable=False, server_default="us"),
        sa.Column("adp_token", sa.Text(), nullable=False),
        sa.Column("private_key", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audible_connections")
