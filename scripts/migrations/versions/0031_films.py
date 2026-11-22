"""
Films come back (adds, before the deploy): films is everyone's (shared,
kept by admins), a film once by its IMDb id, with its year, directors,
genres, poster and its ids on IMDb, The Movie Database, Wikidata and
Rotten Tomatoes; film_watches is each account's own: a time it watched a
film, or means to (status), when, where, on what device, with whom
(film_watch_companions), its rating and review, and who recommended it.

The films the library kept from before (library_works of the kind film)
become shared films, found again by their IMDb id; one no account had in
its library goes from library_works, as the film it was is in films now.
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

RATING = "rating IS NULL OR (rating >= 1 AND rating <= 10)"


def _create_tables() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "films" not in tables:
        op.create_table(
            "films",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=500), nullable=False),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("directors", sa.String(length=1000), nullable=False, server_default=""),
            sa.Column("genres", sa.JSON(), nullable=False),
            sa.Column("imdb_id", sa.String(length=20), nullable=True),
            sa.Column("tmdb_id", sa.Integer(), nullable=True),
            sa.Column("wikidata_id", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("rotten_tomatoes_id", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="SET NULL", name="fk_films_image_id"), nullable=True),
            sa.UniqueConstraint("imdb_id", name="uq_film_imdb_id"),
        )
    if "film_watches" not in tables:
        op.create_table(
            "film_watches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_film_watches_owner_id"), nullable=False),
            sa.Column("film_id", sa.Integer(), sa.ForeignKey("films.id", ondelete="RESTRICT", name="fk_film_watches_film_id"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="done"),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("review", sa.Text(), nullable=False, server_default=""),
            sa.Column("watched_at", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL", name="fk_film_watches_device_id"), nullable=True),
            sa.Column("recommended_by_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="SET NULL", name="fk_film_watches_recommended_by_id"), nullable=True),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
            sa.CheckConstraint(RATING, name="ck_film_watch_rating_range"),
        )
        op.create_index("ix_film_watches_owner_id", "film_watches", ["owner_id"])
        op.create_index("ix_film_watches_film_id", "film_watches", ["film_id"])
    if "film_watch_companions" not in tables:
        op.create_table(
            "film_watch_companions",
            sa.Column(
                "film_watch_id", sa.Integer(),
                sa.ForeignKey("film_watches.id", ondelete="CASCADE", name="fk_film_watch_companions_film_watch_id"), primary_key=True,
            ),
            sa.Column("person_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="CASCADE", name="fk_film_watch_companions_person_id"), primary_key=True),
        )


def _library_films() -> None:
    """ The films of library_works become shared films (once by IMDb id); one no library entry has goes from library_works. """
    bind = op.get_bind()
    works = sa.table(
        "library_works", sa.column("id"), sa.column("kind"), sa.column("title"), sa.column("creator"), sa.column("year"),
        sa.column("imdb_id"), sa.column("tmdb_id"), sa.column("rotten_tomatoes_id"),
    )
    entries = sa.table("library_entries", sa.column("work_id"))
    titles = sa.table("library_work_titles", sa.column("work_id"))
    films = sa.table(
        "films", sa.column("id"), sa.column("name"), sa.column("year"), sa.column("directors"), sa.column("genres", sa.JSON()),
        sa.column("imdb_id"), sa.column("tmdb_id"), sa.column("wikidata_id"), sa.column("rotten_tomatoes_id"),
    )
    have = {imdb for (imdb,) in bind.execute(sa.select(films.c.imdb_id)) if imdb}
    used = {work_id for (work_id,) in bind.execute(sa.select(entries.c.work_id))}
    for work in bind.execute(sa.select(works).where(works.c.kind == "film").order_by(works.c.id)).all():
        imdb = work.imdb_id or None
        if imdb is None or imdb not in have:
            bind.execute(sa.insert(films).values(
                name=work.title, year=work.year, directors=work.creator or "", genres=[], imdb_id=imdb,
                tmdb_id=work.tmdb_id, wikidata_id="", rotten_tomatoes_id=work.rotten_tomatoes_id or "",
            ))
            if imdb is not None:
                have.add(imdb)
        if work.id not in used:
            bind.execute(sa.delete(titles).where(titles.c.work_id == work.id))
            bind.execute(sa.delete(works).where(works.c.id == work.id))


def upgrade() -> None:
    _create_tables()
    _library_films()


def downgrade() -> None:
    op.drop_table("film_watch_companions")
    op.drop_index("ix_film_watches_film_id", table_name="film_watches")
    op.drop_index("ix_film_watches_owner_id", table_name="film_watches")
    op.drop_table("film_watches")
    op.drop_table("films")
