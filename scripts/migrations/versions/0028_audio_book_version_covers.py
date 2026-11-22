"""
A cover is a version's, the first step (before the deploy): an Audible
version's cover is Audible's, MP3 files' a print edition's, so
audio_book_versions gets image_id. A book's cover goes to its Audible
version when it has one (its cover came from Audible), else to every
version it has. 0029 drops audio_books.image_id, after the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "image_id" not in {column["name"] for column in sa.inspect(bind).get_columns("audio_book_versions")}:
        with op.batch_alter_table("audio_book_versions") as batch:
            batch.add_column(sa.Column("image_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_audio_book_versions_image_id", "images", ["image_id"], ["id"], ondelete="SET NULL")
    if "image_id" not in {column["name"] for column in sa.inspect(bind).get_columns("audio_books")}:
        # moved already
        return
    books = bind.execute(sa.text("SELECT id, image_id FROM audio_books WHERE image_id IS NOT NULL")).all()
    for book, image in books:
        kinds = {kind for (kind,) in bind.execute(sa.text("SELECT kind FROM audio_book_versions WHERE book_id = :book"), {"book": book}).all()}
        only = " AND kind = 'audible'" if "audible" in kinds else ""
        bind.execute(sa.text(f"UPDATE audio_book_versions SET image_id = :image WHERE book_id = :book AND image_id IS NULL{only}"), {"image": image, "book": book})


def downgrade() -> None:
    with op.batch_alter_table("audio_book_versions") as batch:
        batch.drop_constraint("fk_audio_book_versions_image_id", type_="foreignkey")
        batch.drop_column("image_id")
