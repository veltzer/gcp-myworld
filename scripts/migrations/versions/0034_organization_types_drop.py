"""
An organization has any number of types, the second step (after the
deploy): what 0033 copied to organization_type_links goes from
organizations.type_id.
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "type_id" not in {column["name"] for column in inspector.get_columns("organizations")}:
        # gone already
        return
    keys = [key["name"] for key in inspector.get_foreign_keys("organizations") if key["name"] and key["constrained_columns"] == ["type_id"]]
    with op.batch_alter_table("organizations") as batch:
        for key in keys:
            batch.drop_constraint(key, type_="foreignkey")
        batch.drop_column("type_id")


def downgrade() -> None:
    raise NotImplementedError("0034 drops the one type each organization had: they are in organization_type_links")
