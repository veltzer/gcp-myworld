"""
Trips, lectures and rallies (adds, before the deploy): each account's own.
A trip: where to, the countries it was in, when, how many days, who came
along (or alone) and a remark. A lecture: its name and description, who gave
it, where (free text and a country), when, a rating, a review, who came
along (or alone) and a remark. A rally: what it was, where, when, a rating,
a review, who came along (or alone) and a remark.
"""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def _dated() -> list[sa.Column]:
    return [
        sa.Column("date_utcz", sa.DateTime(), nullable=True),
        sa.Column("date_ymd", sa.Date(), nullable=True),
        sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
        sa.Column("date_y", sa.Integer(), nullable=True),
        sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
    ]


def _owner() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
    ]


def _people(table: str, column: str, row: str) -> None:
    op.create_table(
        table,
        sa.Column(column, sa.Integer(), sa.ForeignKey(f"{row}.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    )


def _rated(name: str) -> list[sa.Column | sa.CheckConstraint]:
    return [
        sa.Column("location", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id", ondelete="SET NULL", name=f"fk_{name}_country_id"), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("review", sa.Text(), nullable=False, server_default=""),
        sa.Column("remark", sa.Text(), nullable=False, server_default=""),
        sa.Column("alone", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "trips" not in tables:
        op.create_table(
            "trips",
            *_owner(),
            sa.Column("days", sa.Integer(), nullable=True),
            sa.Column("remark", sa.Text(), nullable=False, server_default=""),
            sa.Column("alone", sa.Boolean(), nullable=False, server_default=sa.false()),
            *_dated(),
            sa.CheckConstraint("days IS NULL OR days >= 1", name="ck_trip_days"),
        )
        op.create_index("ix_trips_owner_id", "trips", ["owner_id"])
        _people("trip_companions", "trip_id", "trips")
        op.create_table(
            "trip_countries",
            sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id", ondelete="CASCADE"), primary_key=True),
        )
    if "lectures" not in tables:
        op.create_table(
            "lectures",
            *_owner(),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            *_rated("lectures"),
            *_dated(),
            sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_lecture_rating_range"),
        )
        op.create_index("ix_lectures_owner_id", "lectures", ["owner_id"])
        op.create_index("ix_lectures_country_id", "lectures", ["country_id"])
        _people("lecture_companions", "lecture_id", "lectures")
        _people("lecture_lecturers", "lecture_id", "lectures")
    if "rallies" not in tables:
        op.create_table(
            "rallies",
            *_owner(),
            *_rated("rallies"),
            *_dated(),
            sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_rally_rating_range"),
        )
        op.create_index("ix_rallies_owner_id", "rallies", ["owner_id"])
        op.create_index("ix_rallies_country_id", "rallies", ["country_id"])
        _people("rally_companions", "rally_id", "rallies")


def downgrade() -> None:
    for table in ("rally_companions", "rallies", "lecture_lecturers", "lecture_companions", "lectures", "trip_countries", "trip_companions", "trips"):
        op.drop_table(table)
