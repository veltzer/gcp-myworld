"""
Goodreads connections (adds, before the deploy): each account's own, made
on the Imports page from a shelf's RSS address: the account's Goodreads
number, its feeds' key (sealed with a key derived from SECRET_KEY), and when
it was connected.
"""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "goodreads_connections" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "goodreads_connections",
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.String(length=20), nullable=False),
            sa.Column("feed_key", sa.Text(), nullable=False),
            sa.Column("connected_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("goodreads_connections")
