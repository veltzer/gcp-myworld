"""
What the Locale importer brings: currencies (and the currencies a country
uses, country_currencies), the official languages of a country
(country_languages), and the codes it knows a row again by, whatever the row
is called here: a country's ISO 3166 codes (countries.code, code3), a
region's GeoNames code (regions.code), a city's GeoNames id and population
(cities.geonames_id, population). And an admin's lock on the shared data
(users.edit_shared), off to start with.
Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "currencies" not in tables:
        op.create_table(
            "currencies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=3), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("symbol", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("digits", sa.Integer(), nullable=True),
            sa.UniqueConstraint("code", name="uq_currency_code"),
        )
    if "country_currencies" not in tables:
        op.create_table(
            "country_currencies",
            sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="CASCADE"), primary_key=True),
        )
    if "country_languages" not in tables:
        op.create_table(
            "country_languages",
            sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("locale_code", sa.String(length=10), sa.ForeignKey("locales.code", ondelete="CASCADE"), primary_key=True),
        )
    have = _columns("countries")
    with op.batch_alter_table("countries") as batch:
        if "code" not in have:
            batch.add_column(sa.Column("code", sa.String(length=2), nullable=True))
            batch.create_unique_constraint("uq_country_code", ["code"])
        if "code3" not in have:
            batch.add_column(sa.Column("code3", sa.String(length=3), nullable=False, server_default=""))
    if "code" not in _columns("regions"):
        with op.batch_alter_table("regions") as batch:
            batch.add_column(sa.Column("code", sa.String(length=20), nullable=True))
            batch.create_unique_constraint("uq_region_code", ["code"])
    have = _columns("cities")
    with op.batch_alter_table("cities") as batch:
        if "population" not in have:
            batch.add_column(sa.Column("population", sa.BigInteger(), nullable=True))
        if "geonames_id" not in have:
            batch.add_column(sa.Column("geonames_id", sa.Integer(), nullable=True))
            batch.create_unique_constraint("uq_city_geonames_id", ["geonames_id"])
    if "edit_shared" not in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("edit_shared", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("edit_shared")
    with op.batch_alter_table("cities") as batch:
        batch.drop_constraint("uq_city_geonames_id", type_="unique")
        batch.drop_column("geonames_id")
        batch.drop_column("population")
    with op.batch_alter_table("regions") as batch:
        batch.drop_constraint("uq_region_code", type_="unique")
        batch.drop_column("code")
    with op.batch_alter_table("countries") as batch:
        batch.drop_constraint("uq_country_code", type_="unique")
        batch.drop_column("code3")
        batch.drop_column("code")
    op.drop_table("country_languages")
    op.drop_table("country_currencies")
    op.drop_table("currencies")
