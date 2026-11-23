"""
Goodreads connections go (drops, after the deploy): Goodreads dropped its
shelves' RSS feeds, whose key a connection kept, and shows a shelf to no one
signed out; the Goodreads importer reads a library export the user uploads
with the run instead, and needs no connection.
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "goodreads_connections" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("goodreads_connections")


def downgrade() -> None:
    op.create_table(
        "goodreads_connections",
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(length=20), nullable=False),
        sa.Column("feed_key", sa.Text(), nullable=False),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
    )
