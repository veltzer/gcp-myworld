"""
Audio books are shared, the second step (after the deploy): what 0026
copied to audio_book_versions, audio_books_heard and audio_book_listens
goes from audio_books, which is everyone's now: whose each was (owner_id),
where it came from and what the source says of it, the rating and review,
and how and when it was heard. A book is now once in all of My World by
its title, subtitle and authors.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

GONE = (
    "owner_id", "source", "source_id", "narrators", "genres", "minutes", "finished", "percent_heard", "source_rating", "source_ratings",
    "added_utcz", "purchased_utcz", "cover_url", "released", "rating", "review", "started_utcz", "progress", "listened_at", "device_id",
    "date_utcz", "date_ymd", "date_my", "date_y", "date_timezone",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("audio_books")}
    # (a database made shared from the start may have some of them: 0020 and 0021 add theirs to any audio_books)
    if not columns & set(GONE):
        # shared already
        return
    indexes = {index["name"] for index in inspector.get_indexes("audio_books")}
    keys = [key["name"] for key in inspector.get_foreign_keys("audio_books") if key["name"] and set(key["constrained_columns"]) & set(GONE)]
    checks = {check["name"] for check in inspector.get_check_constraints("audio_books")}
    uniques = {unique["name"] for unique in inspector.get_unique_constraints("audio_books")}
    with op.batch_alter_table("audio_books") as batch:
        if "ix_audio_books_owner_id" in indexes:
            batch.drop_index("ix_audio_books_owner_id")
        for key in keys:
            batch.drop_constraint(key, type_="foreignkey")
        if "ck_audio_book_rating_range" in checks:
            batch.drop_constraint("ck_audio_book_rating_range", type_="check")
        if "uq_audio_book_source_id" in uniques:
            batch.drop_constraint("uq_audio_book_source_id", type_="unique")
        for column in GONE:
            if column in columns:
                batch.drop_column(column)
        if "uq_audio_book_identity" not in uniques:
            batch.create_unique_constraint("uq_audio_book_identity", ["name", "subtitle", "authors"])


def downgrade() -> None:
    raise NotImplementedError("0027 drops whose each audio book was: it cannot come back")
