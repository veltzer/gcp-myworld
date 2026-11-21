"""
Audio books (audio_books): the books of a user's library at a source
(Audible, for now), with what the source says of each and the user's own
rating and review. Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "audio_books" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "audio_books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("source_id", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("subtitle", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("authors", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("narrators", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("series", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("series_sequence", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=True),
        sa.Column("finished", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("percent_heard", sa.Double(), nullable=True),
        sa.Column("source_rating", sa.Double(), nullable=True),
        sa.Column("source_ratings", sa.Integer(), nullable=True),
        sa.Column("added_utcz", sa.DateTime(), nullable=True),
        sa.Column("released", sa.Date(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("review", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("owner_id", "source", "source_id", name="uq_audio_book_source_id"),
        sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_audio_book_rating_range"),
    )
    op.create_index("ix_audio_books_owner_id", "audio_books", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_audio_books_owner_id", table_name="audio_books")
    op.drop_table("audio_books")
