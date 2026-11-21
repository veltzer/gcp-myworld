"""
Clear deletes runs now (0015): the column that only hid them goes.
Dropping: run after the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "cleared_at" in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("import_runs")}:
        with op.batch_alter_table("import_runs") as batch:
            batch.drop_column("cleared_at")


def downgrade() -> None:
    with op.batch_alter_table("import_runs") as batch:
        batch.add_column(sa.Column("cleared_at", sa.DateTime(), nullable=True))
