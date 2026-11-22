"""
An audio book's ids in catalogs (adds, before the deploy): its Open
Library work, a Goodreads book of it and its Wikidata item, each empty
while not known.
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

IDS = ("openlibrary_id", "goodreads_id", "wikidata_id")


def upgrade() -> None:
    have = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audio_books")}
    with op.batch_alter_table("audio_books") as batch:
        for name in IDS:
            if name not in have:
                batch.add_column(sa.Column(name, sa.String(length=20), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("audio_books") as batch:
        for name in IDS:
            batch.drop_column(name)
