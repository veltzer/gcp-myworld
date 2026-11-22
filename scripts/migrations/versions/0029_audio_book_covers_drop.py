"""
A cover is a version's, the second step (after the deploy): what 0028
copied to audio_book_versions.image_id goes from audio_books.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "image_id" not in {column["name"] for column in inspector.get_columns("audio_books")}:
        # gone already
        return
    keys = [key["name"] for key in inspector.get_foreign_keys("audio_books") if key["name"] and key["constrained_columns"] == ["image_id"]]
    with op.batch_alter_table("audio_books") as batch:
        for key in keys:
            batch.drop_constraint(key, type_="foreignkey")
        batch.drop_column("image_id")


def downgrade() -> None:
    raise NotImplementedError("0029 drops the books' covers, which are their versions' now")
