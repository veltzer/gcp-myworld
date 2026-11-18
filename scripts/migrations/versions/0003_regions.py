"""
Regions are rows: a regions table, and cities.region_id pointing at it. Every
region a city names (cities.region, a text) becomes one row for its account
and country, and the city points at it. cities.region stays, with a default,
for the code still running; 0004 drops it. Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "regions" not in inspector.get_table_names():
        op.create_table(
            "regions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("country_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("owner_id", "name", "country_id", name="uq_region_name"),
        )
        op.create_index("ix_regions_country_id", "regions", ["country_id"])
        op.create_index("ix_regions_owner_id", "regions", ["owner_id"])
    columns = {column["name"] for column in inspector.get_columns("cities")}
    if "region_id" in columns:
        # a database marked as being at the baseline may already have the cities of today
        return
    uniques = {unique["name"] for unique in inspector.get_unique_constraints("cities")}
    with op.batch_alter_table("cities") as batch:
        batch.add_column(sa.Column("region_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_cities_region_id", "regions", ["region_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_cities_region_id", ["region_id"])
        # the old code, until the deploy, adds cities without saying the text
        batch.alter_column("region", existing_type=sa.String(length=100), existing_nullable=False, server_default="")
        if "uq_city_name" in uniques:
            batch.drop_constraint("uq_city_name", type_="unique")
        batch.create_unique_constraint("uq_city_name", ["owner_id", "name", "region_id", "country_id"])
    bind.execute(sa.text(
        "INSERT INTO regions (owner_id, name, country_id) "
        "SELECT DISTINCT owner_id, TRIM(region), country_id FROM cities WHERE TRIM(region) <> ''"
    ))
    bind.execute(sa.text(
        "UPDATE cities SET region_id = (SELECT regions.id FROM regions WHERE regions.owner_id = cities.owner_id AND regions.name = TRIM(cities.region) "
        "AND (regions.country_id = cities.country_id OR (regions.country_id IS NULL AND cities.country_id IS NULL))) WHERE TRIM(region) <> ''"
    ))


def downgrade() -> None:
    with op.batch_alter_table("cities") as batch:
        batch.drop_constraint("uq_city_name", type_="unique")
        batch.create_unique_constraint("uq_city_name", ["owner_id", "name", "region", "country_id"])
        batch.drop_index("ix_cities_region_id")
        batch.drop_constraint("fk_cities_region_id", type_="foreignkey")
        batch.drop_column("region_id")
    op.drop_table("regions")
