"""
cities.region, the text, goes: a city's region is the row cities.region_id
points at (0003). Dropping a column the new code no longer uses: deploy
first, then run this.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "region" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("cities")}:
        return
    with op.batch_alter_table("cities") as batch:
        batch.drop_column("region")


def downgrade() -> None:
    with op.batch_alter_table("cities") as batch:
        batch.add_column(sa.Column("region", sa.String(length=100), server_default="", nullable=False))
    op.get_bind().execute(sa.text("UPDATE cities SET region = COALESCE((SELECT name FROM regions WHERE regions.id = cities.region_id), '')"))
