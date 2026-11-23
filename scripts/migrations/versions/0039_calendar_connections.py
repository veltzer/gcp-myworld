"""
Google Calendar connections (adds, before the deploy): each account's own,
made on the Imports page: Google's refresh token for the calendar.readonly
scope (sealed with a key derived from SECRET_KEY), the account's name, and
when it was connected.
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "calendar_connections" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "calendar_connections",
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("refresh_token", sa.Text(), nullable=False),
            sa.Column("account", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("connected_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("calendar_connections")
