"""
Podcasts (podcasts) and the episodes of them heard (podcast_episodes): a
podcast's name, page, feed, cover and the user's rating and review; an
episode's fields as its feed says them, when, where and on what device it
was heard. Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "podcasts" not in tables:
        op.create_table(
            "podcasts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=500), nullable=False),
            sa.Column("url", sa.String(length=1000), nullable=False, server_default=""),
            sa.Column("rss_feed", sa.String(length=1000), nullable=False, server_default=""),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("review", sa.Text(), nullable=False, server_default=""),
            sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="SET NULL"), nullable=True),
            sa.UniqueConstraint("owner_id", "name", name="uq_podcast_name"),
            sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_podcast_rating_range"),
        )
        op.create_index("ix_podcasts_owner_id", "podcasts", ["owner_id"])
    if "podcast_episodes" not in tables:
        op.create_table(
            "podcast_episodes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("podcast_id", sa.Integer(), sa.ForeignKey("podcasts.id", ondelete="CASCADE", name="fk_podcast_episodes_podcast_id"), nullable=False),
            sa.Column("name", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("published_utcz", sa.DateTime(), nullable=True),
            sa.Column("number", sa.Integer(), nullable=True),
            sa.Column("duration", sa.Integer(), nullable=True),
            sa.Column("episode_type", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("explicit", sa.String(length=10), nullable=False, server_default=""),
            sa.Column("enclosure_url", sa.String(length=2000), nullable=False, server_default=""),
            sa.Column("image_url", sa.String(length=2000), nullable=False, server_default=""),
            sa.Column("author", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("guid", sa.String(length=500), nullable=True),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("review", sa.Text(), nullable=False, server_default=""),
            sa.Column("listened_at", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL", name="fk_podcast_episodes_device_id"), nullable=True),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
            sa.UniqueConstraint("podcast_id", "guid", name="uq_podcast_episode_guid"),
            sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_podcast_episode_rating_range"),
        )
        op.create_index("ix_podcast_episodes_owner_id", "podcast_episodes", ["owner_id"])
        op.create_index("ix_podcast_episodes_podcast_id", "podcast_episodes", ["podcast_id"])


def downgrade() -> None:
    op.drop_index("ix_podcast_episodes_podcast_id", table_name="podcast_episodes")
    op.drop_index("ix_podcast_episodes_owner_id", table_name="podcast_episodes")
    op.drop_table("podcast_episodes")
    op.drop_index("ix_podcasts_owner_id", table_name="podcasts")
    op.drop_table("podcasts")
