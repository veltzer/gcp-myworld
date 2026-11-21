"""
Runs that ended can be cleared off the Imports page (import_runs.cleared_at):
no longer listed, still counted against the month's runs.
Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("import_runs")}
    if "cleared_at" not in have:
        with op.batch_alter_table("import_runs") as batch:
            batch.add_column(sa.Column("cleared_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("import_runs") as batch:
        batch.drop_column("cleared_at")
