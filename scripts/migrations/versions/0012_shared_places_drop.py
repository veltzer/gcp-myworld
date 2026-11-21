"""
Shared data, the second step (after the deploy): what the code before it
needed and 0011 copied goes. museum_sites, museum_visits and
museum_companions (now places of the kind Museum, visits and
visit_companions); owner_id of countries, regions, cities and places
(everyone's now); and the remarks of countries, cities and places (a
shared row has nothing personal on it: 0011 moved the places' to their
concerts).
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SHARED = ("countries", "regions", "cities", "places")
NO_REMARK = ("countries", "cities", "places")


def upgrade() -> None:
    bind = op.get_bind()
    have = set(sa.inspect(bind).get_table_names())
    for table in ("museum_companions", "museum_visits", "museum_sites"):
        if table in have:
            op.drop_table(table)
    for table in SHARED:
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        keys = [key["name"] for key in sa.inspect(bind).get_foreign_keys(table) if key["constrained_columns"] == ["owner_id"] and key["name"]]
        with op.batch_alter_table(table) as batch:
            if f"ix_{table}_owner_id" in indexes:
                batch.drop_index(f"ix_{table}_owner_id")
            for key in keys:
                batch.drop_constraint(key, type_="foreignkey")
            if "owner_id" in columns:
                batch.drop_column("owner_id")
            if table in NO_REMARK and "remark" in columns:
                batch.drop_column("remark")


def downgrade() -> None:
    raise NotImplementedError("0012 drops the museums' old tables and whose each shared row was: they cannot come back")
