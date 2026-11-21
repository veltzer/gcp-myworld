"""
Each account's username (users.username): the name it is known by, one
account's alone, chosen by its user; empty until chosen.
Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "username" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("username", sa.String(length=30), nullable=True))
            batch.create_unique_constraint("uq_user_username", ["username"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_user_username", type_="unique")
        batch.drop_column("username")
