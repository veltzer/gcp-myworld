"""
When and how an audio book was heard, as an audio course says it: the day
it was finished (the date_* columns, at the precision known, and where),
when it was started, how far it got (progress), where it was heard
(listened_at) and on what (device_id). Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

COLUMNS = (
    ("date_utcz", lambda: sa.Column("date_utcz", sa.DateTime(), nullable=True)),
    ("date_ymd", lambda: sa.Column("date_ymd", sa.Date(), nullable=True)),
    ("date_my", lambda: sa.Column("date_my", sa.String(length=7), nullable=False, server_default="")),
    ("date_y", lambda: sa.Column("date_y", sa.Integer(), nullable=True)),
    ("date_timezone", lambda: sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default="")),
    ("started_utcz", lambda: sa.Column("started_utcz", sa.DateTime(), nullable=True)),
    ("progress", lambda: sa.Column("progress", sa.String(length=20), nullable=False, server_default="")),
    ("listened_at", lambda: sa.Column("listened_at", sa.String(length=100), nullable=False, server_default="")),
    ("device_id", lambda: sa.Column("device_id", sa.Integer(), nullable=True)),
)


def upgrade() -> None:
    have = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audio_books")}
    with op.batch_alter_table("audio_books") as batch:
        for name, column in COLUMNS:
            if name not in have:
                batch.add_column(column())
        if "device_id" not in have:
            batch.create_foreign_key("fk_audio_books_device_id", "devices", ["device_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("audio_books") as batch:
        batch.drop_constraint("fk_audio_books_device_id", type_="foreignkey")
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
