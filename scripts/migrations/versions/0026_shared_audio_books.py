"""
Audio books are shared, the first step (before the deploy): audio_books
becomes everyone's, each book in versions of its own (audio_book_versions:
the Audible one, MP3 files), and what was the user's own goes to two
tables of their own. audio_books_heard: a book a user heard, with their
rating and review; audio_book_listens: a version they heard, whether they
finished it and when, how far they got, where, on what device, and of an
Audible one when it came into their library and when they bought it.

Every account's book becomes a version (an Audible one when it came from
Audible, else MP3 files), an audio_books_heard row and an
audio_book_listens row of it; then the books of the same title, subtitle
and authors become one (the first; what it lacks, its series and cover,
from another), their versions and what was heard of them pointing at it. The
columns the code after it no longer writes may be empty, so that it can
add rows; 0027 drops them, after the deploy.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

RATING = "rating IS NULL OR (rating >= 1 AND rating <= 10)"
# the columns of the user's own that 0027 drops which have no default, which the code after the deploy no longer writes
NOT_WRITTEN = (("owner_id", sa.Integer()), ("genres", sa.JSON()))


def _create_tables() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "audio_book_versions" not in tables:
        op.create_table(
            "audio_book_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("audio_books.id", ondelete="CASCADE", name="fk_audio_book_versions_book_id"), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("narrators", sa.String(length=1000), nullable=False, server_default=""),
            sa.Column("minutes", sa.Integer(), nullable=True),
            sa.Column("asin", sa.String(length=40), nullable=True),
            sa.Column("genres", sa.JSON(), nullable=False),
            sa.Column("source_rating", sa.Double(), nullable=True),
            sa.Column("source_ratings", sa.Integer(), nullable=True),
            sa.Column("released", sa.Date(), nullable=True),
            sa.Column("cover_url", sa.String(length=1000), nullable=False, server_default=""),
            sa.Column("parts", sa.Integer(), nullable=True),
            sa.UniqueConstraint("asin", name="uq_audio_book_version_asin"),
        )
        op.create_index("ix_audio_book_versions_book_id", "audio_book_versions", ["book_id"])
    if "audio_books_heard" not in tables:
        op.create_table(
            "audio_books_heard",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("book_id", sa.Integer(), sa.ForeignKey("audio_books.id", ondelete="RESTRICT", name="fk_audio_books_heard_book_id"), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("review", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("owner_id", "book_id", name="uq_audio_book_heard"),
            sa.CheckConstraint(RATING, name="ck_audio_book_heard_rating_range"),
        )
        op.create_index("ix_audio_books_heard_owner_id", "audio_books_heard", ["owner_id"])
        op.create_index("ix_audio_books_heard_book_id", "audio_books_heard", ["book_id"])
    if "audio_book_listens" not in tables:
        op.create_table(
            "audio_book_listens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "version_id", sa.Integer(),
                sa.ForeignKey("audio_book_versions.id", ondelete="RESTRICT", name="fk_audio_book_listens_version_id"), nullable=False,
            ),
            sa.Column("finished", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("percent_heard", sa.Double(), nullable=True),
            sa.Column("started_utcz", sa.DateTime(), nullable=True),
            sa.Column("progress", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("listened_at", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL", name="fk_audio_book_listens_device_id"), nullable=True),
            sa.Column("added_utcz", sa.DateTime(), nullable=True),
            sa.Column("purchased_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
            sa.UniqueConstraint("owner_id", "version_id", name="uq_audio_book_listen"),
        )
        op.create_index("ix_audio_book_listens_owner_id", "audio_book_listens", ["owner_id"])
        op.create_index("ix_audio_book_listens_version_id", "audio_book_listens", ["version_id"])


def _genres(value: object) -> list[str]:
    """ A JSON column read by plain SQL: text on SQLite, the list itself on PostgreSQL. """
    if isinstance(value, str):
        value = json.loads(value)
    return list(value) if isinstance(value, list) else []


def _copy() -> None:
    """
    Each account's book: a version of it (an Audible one another account
    has, by its ASIN, is that version), the account's audio_books_heard
    row of the version's book and its audio_book_listens row of the
    version.
    """
    bind = op.get_bind()
    done = {row[0] for row in bind.execute(sa.text("SELECT book_id FROM audio_book_versions")).all()}
    books = bind.execute(sa.text(
        "SELECT id, owner_id, source, source_id, narrators, minutes, genres, source_rating, source_ratings, released, cover_url,"
        " rating, review, finished, percent_heard, started_utcz, progress, listened_at, device_id, added_utcz, purchased_utcz,"
        " date_utcz, date_ymd, date_my, date_y, date_timezone FROM audio_books WHERE owner_id IS NOT NULL ORDER BY id"
    )).mappings().all()
    versions = sa.table(
        "audio_book_versions", sa.column("id", sa.Integer()), sa.column("book_id", sa.Integer()), sa.column("kind", sa.String()),
        sa.column("narrators", sa.String()), sa.column("minutes", sa.Integer()), sa.column("asin", sa.String()), sa.column("genres", sa.JSON()),
        sa.column("source_rating", sa.Double()), sa.column("source_ratings", sa.Integer()), sa.column("released", sa.Date()),
        sa.column("cover_url", sa.String()),
    )
    by_asin = {asin: (version, book) for version, book, asin in bind.execute(sa.text(
        "SELECT id, book_id, asin FROM audio_book_versions WHERE asin IS NOT NULL",
    )).all()}
    for book in books:
        if book["id"] in done:
            continue
        audible = book["source"] == "audible"
        if audible and book["source_id"] in by_asin:
            version, of = by_asin[book["source_id"]]
            print(f"0026: audio_books row {book['id']} is the Audible book {book['source_id']} of row {of}: its version")
            _heard_and_listen(bind, book, version, of)
            continue
        version = bind.execute(versions.insert().returning(versions.c.id).values(
            book_id=book["id"], kind="audible" if audible else "mp3", narrators=book["narrators"] or "", minutes=book["minutes"],
            asin=book["source_id"] if audible else None, genres=_genres(book["genres"]),
            source_rating=book["source_rating"], source_ratings=book["source_ratings"], released=book["released"], cover_url=book["cover_url"] or "",
        )).scalar_one()
        if audible and book["source_id"]:
            by_asin[book["source_id"]] = (version, book["id"])
        _heard_and_listen(bind, book, version, book["id"])


def _heard_and_listen(bind: sa.Connection, book: sa.RowMapping, version: int, of: int) -> None:
    """ The account's audio_books_heard row of the book of (once) and its audio_book_listens row of version, from its old row book. """
    had = bind.execute(sa.text("SELECT id FROM audio_books_heard WHERE owner_id = :owner AND book_id = :book"), {"owner": book["owner_id"], "book": of}).first()
    if had is None:
        bind.execute(sa.text(
            "INSERT INTO audio_books_heard (owner_id, book_id, rating, review) VALUES (:owner, :book, :rating, :review)"
        ), {"owner": book["owner_id"], "book": of, "rating": book["rating"], "review": book["review"] or ""})
    bind.execute(sa.text(
        "INSERT INTO audio_book_listens (owner_id, version_id, finished, percent_heard, started_utcz, progress, listened_at, device_id,"
        " added_utcz, purchased_utcz, date_utcz, date_ymd, date_my, date_y, date_timezone) VALUES (:owner, :version, :finished, :percent,"
        " :started, :progress, :where, :device, :added, :purchased, :date_utcz, :date_ymd, :date_my, :date_y, :date_timezone)"
    ), {
        "owner": book["owner_id"], "version": version, "finished": bool(book["finished"]), "percent": book["percent_heard"],
        "started": book["started_utcz"], "progress": book["progress"] or "", "where": book["listened_at"] or "", "device": book["device_id"],
        "added": book["added_utcz"], "purchased": book["purchased_utcz"], "date_utcz": book["date_utcz"], "date_ymd": book["date_ymd"],
        "date_my": book["date_my"] or "", "date_y": book["date_y"], "date_timezone": book["date_timezone"] or "",
    })


def _merge() -> None:
    """ The books of the same title, subtitle and authors become the first of them. """
    bind = op.get_bind()
    first: dict[tuple[str, str, str], dict[str, object]] = {}
    for book in bind.execute(sa.text("SELECT id, name, authors, subtitle, series, series_sequence, image_id FROM audio_books ORDER BY id")).mappings().all():
        key = (book["name"], book["subtitle"] or "", book["authors"] or "")
        if key not in first:
            first[key] = dict(book)
            continue
        kept = first[key]
        print(f"0026: audio_books {key!r} kept once (row {kept['id']}; row {book['id']} merged into it)")
        ids = {"kept": kept["id"], "gone": book["id"]}
        bind.execute(sa.text("UPDATE audio_book_versions SET book_id = :kept WHERE book_id = :gone"), ids)
        # an account that heard both keeps one row of the book: the first's, with the other's rating and review where it has none
        for owner, rating, review in bind.execute(sa.text("SELECT owner_id, rating, review FROM audio_books_heard WHERE book_id = :gone"), ids).all():
            mine = bind.execute(sa.text("SELECT id, rating, review FROM audio_books_heard WHERE book_id = :kept AND owner_id = :owner"),
                                {**ids, "owner": owner}).first()
            if mine is None:
                bind.execute(sa.text("UPDATE audio_books_heard SET book_id = :kept WHERE book_id = :gone AND owner_id = :owner"), {**ids, "owner": owner})
                continue
            bind.execute(sa.text("UPDATE audio_books_heard SET rating = :rating, review = :review WHERE id = :id"), {
                "id": mine[0], "rating": mine[1] if mine[1] is not None else rating, "review": mine[2] or review or "",
            })
            bind.execute(sa.text("DELETE FROM audio_books_heard WHERE book_id = :gone AND owner_id = :owner"), {**ids, "owner": owner})
        filled = {column: book[column] for column in ("series", "series_sequence", "image_id") if not kept[column] and book[column]}
        if filled:
            bind.execute(sa.text(f"UPDATE audio_books SET {', '.join(f'{c} = :{c}' for c in filled)} WHERE id = :kept"), {**filled, "kept": kept["id"]})
            kept.update(filled)
        bind.execute(sa.text("DELETE FROM audio_books WHERE id = :gone"), ids)


def upgrade() -> None:
    _create_tables()
    bind = op.get_bind()
    if "owner_id" not in {column["name"] for column in sa.inspect(bind).get_columns("audio_books")}:
        # shared already
        return
    _copy()
    _merge()
    with op.batch_alter_table("audio_books") as batch:
        for column, kind in NOT_WRITTEN:
            batch.alter_column(column, existing_type=kind, nullable=True)


def downgrade() -> None:
    raise NotImplementedError("0026 makes shared audio books out of every account's: there is no telling them apart again")
