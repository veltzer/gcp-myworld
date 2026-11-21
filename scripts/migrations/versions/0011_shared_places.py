"""
Shared data, the first step (before the deploy): countries, regions,
cities and places become everyone's, kept by admins, and museums become
places of the kind "Museum"; a museum visit becomes a visit, of the type
"Museum visit", the user's own, to such a place.

- place_kinds ("Museum", "Concert venue") and place_kind_links: what a
  place is, any number of kinds. visit_types ("Museum visit") and visits,
  with visit_companions: a user's visit to a place, of a type.
- Every museum (museum_sites) is copied into places, of the kind Museum
  (its url as the place's website), and every museum visit into visits,
  with whoever went along. A place a concert was at is of the kind Concert
  venue.
- Shared rows have nothing personal on them: the remark of a place is
  added to the remarks of the concerts that were there (no place without
  concerts has one). Countries and cities have none to move.
- Rows of the same name (in the same country, region or city) that two
  accounts had become one, and whatever pointed at the others points at it;
  the unique constraints say a name once, whoever's. owner_id is made
  nullable: the code after the deploy writes none.

What the code before the deploy needs is all still there (museum_sites,
museum_visits, owner_id, the remarks); 0012 drops it, after the deploy.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

MUSEUM_KIND = "Museum"
CONCERT_VENUE_KIND = "Concert venue"
MUSEUM_VISIT = "Museum visit"

# a shared table, what tells its rows apart (one name once in it), and what points at it
SHARED: tuple[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    ("countries", ("name",), (("cities", "country_id"), ("regions", "country_id"))),
    ("regions", ("name", "country_id"), (("cities", "region_id"),)),
    ("cities", ("name", "region_id", "country_id"), (
        ("places", "city_id"), ("museum_sites", "city_id"), ("organizations", "city_id"), ("organizations", "headquarters_id"), ("city_photos", "city_id"),
    )),
    ("places", ("name", "city_id"), (("concert_visits", "place_id"), ("visits", "place_id"))),
)
OLD_UNIQUE = {
    "countries": ("uq_country_name", ["owner_id", "name"]),
    "regions": ("uq_region_name", ["owner_id", "name", "country_id"]),
    "cities": ("uq_city_name", ["owner_id", "name", "region_id", "country_id"]),
    "places": ("uq_place_name", ["owner_id", "name", "city_id"]),
}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _create_tables() -> None:
    have = _tables()
    if "place_kinds" not in have:
        op.create_table(
            "place_kinds",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
    if "place_kind_links" not in have:
        op.create_table(
            "place_kind_links",
            sa.Column("place_id", sa.Integer(), nullable=False),
            sa.Column("kind_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["kind_id"], ["place_kinds.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("place_id", "kind_id"),
        )
    if "visit_types" not in have:
        op.create_table(
            "visit_types",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
    if "visits" not in have:
        op.create_table(
            "visits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("place_id", sa.Integer(), nullable=True),
            sa.Column("type_id", sa.Integer(), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("review", sa.Text(), nullable=False),
            sa.Column("remark", sa.Text(), nullable=False),
            sa.Column("tickets", sa.Integer(), nullable=True),
            sa.Column("alone", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False),
            sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_visit_rating_range"),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["type_id"], ["visit_types.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("visits") as batch:
            batch.create_index(batch.f("ix_visits_owner_id"), ["owner_id"], unique=False)
            batch.create_index(batch.f("ix_visits_place_id"), ["place_id"], unique=False)
            batch.create_index(batch.f("ix_visits_type_id"), ["type_id"], unique=False)
    if "visit_companions" not in have:
        op.create_table(
            "visit_companions",
            sa.Column("visit_id", sa.Integer(), nullable=False),
            sa.Column("person_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("visit_id", "person_id"),
        )


def _id_of(table: str, name: str) -> int:
    """ The row of that name in place_kinds or visit_types, made when there is none. """
    bind = op.get_bind()
    found = bind.execute(sa.text(f"SELECT id FROM {table} WHERE name = :name"), {"name": name}).scalar()
    if found is None:
        bind.execute(sa.text(f"INSERT INTO {table} (name) VALUES (:name)"), {"name": name})
        found = bind.execute(sa.text(f"SELECT id FROM {table} WHERE name = :name"), {"name": name}).scalar()
    assert found is not None
    return int(found)


def _kind(place: int, kind: int) -> None:
    bind = op.get_bind()
    there = bind.execute(sa.text("SELECT 1 FROM place_kind_links WHERE place_id = :p AND kind_id = :k"), {"p": place, "k": kind}).first()
    if there is None:
        bind.execute(sa.text("INSERT INTO place_kind_links (place_id, kind_id) VALUES (:p, :k)"), {"p": place, "k": kind})


def _museums_to_places(museum_kind: int, museum_visit: int) -> None:
    """ Every museum becomes a place of the kind Museum, and its visits visits of the type Museum visit. """
    bind = op.get_bind()
    if "museum_sites" not in _tables():
        return
    if bind.execute(sa.text("SELECT 1 FROM visits LIMIT 1")).first() is not None:
        # done already (a run stopped after this, and started again)
        return
    museums = bind.execute(sa.text(
        "SELECT id, owner_id, name, city_id, url, image_id, street, neighbourhood, postcode, latitude, longitude FROM museum_sites ORDER BY id"
    )).mappings().all()
    # (a database made from the models of today has places with neither)
    extra = [column for column in ("owner_id", "remark") if column in _columns("places")]
    values = {"owner_id": ":owner_id", "remark": "''"}
    for museum in museums:
        result = bind.execute(
            sa.text(
                f"INSERT INTO places ({''.join(f'{c}, ' for c in extra)}name, city_id, website, image_id, image_source, image_license, image_author,"
                " street, neighbourhood, postcode, latitude, longitude)"
                f" VALUES ({''.join(f'{values[c]}, ' for c in extra)}:name, :city_id, :url, :image_id, '', '', '', :street, :neighbourhood, :postcode, :latitude, :longitude)"
                " RETURNING id"
            ),
            {str(key): museum[key] for key in museum},
        )
        place = int(result.scalar_one())
        _kind(place, museum_kind)
        visits = bind.execute(sa.text(
            "SELECT id, rating, review, remark, tickets, alone, date_utcz, date_ymd, date_my, date_y, date_timezone FROM museum_visits WHERE museum_id = :m ORDER BY id"
        ), {"m": museum["id"]}).mappings().all()
        for visit in visits:
            new = bind.execute(
                sa.text(
                    "INSERT INTO visits (owner_id, place_id, type_id, rating, review, remark, tickets, alone, date_utcz, date_ymd, date_my, date_y, date_timezone)"
                    " VALUES (:owner, :place, :type, :rating, :review, :remark, :tickets, :alone, :date_utcz, :date_ymd, :date_my, :date_y, :date_timezone)"
                    " RETURNING id"
                ),
                {**{str(key): visit[key] for key in visit}, "owner": museum["owner_id"], "place": place, "type": museum_visit},
            ).scalar_one()
            bind.execute(
                sa.text("INSERT INTO visit_companions (visit_id, person_id) SELECT :new, person_id FROM museum_companions WHERE museum_id = :old"),
                {"new": new, "old": visit["id"]},
            )


def _remarks_to_concerts() -> None:
    """ A place's remark is added to the remark of every concert there; the place keeps none. """
    bind = op.get_bind()
    if "remark" not in _columns("places"):
        return
    places = bind.execute(sa.text("SELECT id, name, remark FROM places WHERE remark <> ''")).all()
    for place, name, remark in places:
        said = f"About the place: {remark}"
        concerts = bind.execute(sa.text("SELECT id, remark FROM concert_visits WHERE place_id = :p"), {"p": place}).all()
        if not concerts:
            print(f"0011: the remark of {name} ({remark!r}) has no concert to go to: kept on the place until 0012")
            continue
        for concert, had in concerts:
            if said not in had:
                bind.execute(sa.text("UPDATE concert_visits SET remark = :r WHERE id = :c"), {"r": f"{had}\n{said}" if had else said, "c": concert})
        bind.execute(sa.text("UPDATE places SET remark = '' WHERE id = :p"), {"p": place})


def _merge(table: str, keys: tuple[str, ...], pointers: tuple[tuple[str, str], ...]) -> None:
    """ Rows of table alike in keys become the first of them: what pointed at the others points at it. """
    bind = op.get_bind()
    have = _tables()
    columns = ", ".join(keys)
    rows = list(bind.execute(sa.text(f"SELECT id, {columns} FROM {table} ORDER BY id")).all())
    first: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = tuple(row[1:])
        if key not in first:
            first[key] = row[0]
            continue
        kept, gone = first[key], row[0]
        print(f"0011: {table} {key} kept once (row {kept}; row {gone} merged into it)")
        for other, column in pointers:
            if other in have:
                bind.execute(sa.text(f"UPDATE {other} SET {column} = :kept WHERE {column} = :gone"), {"kept": kept, "gone": gone})
        if table == "places":
            for (kind,) in bind.execute(sa.text("SELECT kind_id FROM place_kind_links WHERE place_id = :g"), {"g": gone}).all():
                _kind(kept, kind)
            bind.execute(sa.text("DELETE FROM place_kind_links WHERE place_id = :g"), {"g": gone})
        bind.execute(sa.text(f"DELETE FROM {table} WHERE id = :g"), {"g": gone})


def upgrade() -> None:
    _create_tables()
    museum_kind = _id_of("place_kinds", MUSEUM_KIND)
    venue_kind = _id_of("place_kinds", CONCERT_VENUE_KIND)
    museum_visit = _id_of("visit_types", MUSEUM_VISIT)
    _museums_to_places(museum_kind, museum_visit)
    bind = op.get_bind()
    for (place,) in bind.execute(sa.text("SELECT DISTINCT place_id FROM concert_visits WHERE place_id IS NOT NULL")).all():
        _kind(place, venue_kind)
    _remarks_to_concerts()
    for table, keys, pointers in SHARED:
        _merge(table, keys, pointers)
        if "owner_id" not in _columns(table):
            # a database made from the models of today: shared already
            continue
        name, old = OLD_UNIQUE[table]
        constraints = {c["name"]: c["column_names"] for c in sa.inspect(bind).get_unique_constraints(table)}
        with op.batch_alter_table(table) as batch:
            if constraints.get(name) == old:
                batch.drop_constraint(name, type_="unique")
                batch.create_unique_constraint(name, [column for column in old if column != "owner_id"])
            batch.alter_column("owner_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    raise NotImplementedError("0011 makes shared rows out of every account's: there is no telling them apart again")
