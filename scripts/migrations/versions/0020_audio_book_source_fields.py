"""
What an audio book's source says that audio_books did not keep yet: the
address of its cover there (cover_url) and when it was bought there
(purchased_utcz). Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audio_books")}
    with op.batch_alter_table("audio_books") as batch:
        if "cover_url" not in columns:
            batch.add_column(sa.Column("cover_url", sa.String(length=1000), nullable=False, server_default=""))
        if "purchased_utcz" not in columns:
            batch.add_column(sa.Column("purchased_utcz", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audio_books") as batch:
        batch.drop_column("purchased_utcz")
        batch.drop_column("cover_url")
