"""
library_entries.not_owned goes: a book owned in no language is one the user
owns no copy of, so nothing more needs to say so. Dropping a column the new
code no longer uses: deploy first, then run this.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # a database marked as being at the baseline may never have had the column
    if "not_owned" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("library_entries")}:
        return
    with op.batch_alter_table("library_entries") as batch:
        batch.drop_column("not_owned")


def downgrade() -> None:
    with op.batch_alter_table("library_entries") as batch:
        batch.add_column(sa.Column("not_owned", sa.Boolean(), server_default=sa.false(), nullable=False))
