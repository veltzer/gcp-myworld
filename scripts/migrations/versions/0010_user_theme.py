"""
Each user's theme (Settings): "system" (the device's), "light" or "dark".
Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "theme" not in have:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("theme", sa.String(length=10), nullable=False, server_default="system"))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("theme")
