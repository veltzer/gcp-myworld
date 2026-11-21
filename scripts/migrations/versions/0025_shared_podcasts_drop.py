"""
Podcasts are shared, the second step (after the deploy): what 0024 copied
to podcasts_heard and episodes_heard goes from podcasts and
podcast_episodes, which are everyone's now: whose each was (owner_id), the
rating and review, and of an episode where, when and on what device it was
heard. A podcast's name is now once in all of My World.
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

GONE = {
    "podcasts": ("owner_id", "rating", "review"),
    "podcast_episodes": (
        "owner_id", "rating", "review", "listened_at", "device_id", "date_utcz", "date_ymd", "date_my", "date_y", "date_timezone",
    ),
}
CHECKS = {"podcasts": "ck_podcast_rating_range", "podcast_episodes": "ck_podcast_episode_rating_range"}


def upgrade() -> None:
    bind = op.get_bind()
    for table, gone in GONE.items():
        inspector = sa.inspect(bind)
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "owner_id" not in columns:
            # shared already
            continue
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        keys = [key["name"] for key in inspector.get_foreign_keys(table) if key["name"] and set(key["constrained_columns"]) & set(gone)]
        checks = {check["name"] for check in inspector.get_check_constraints(table)}
        uniques = {unique["name"]: unique["column_names"] for unique in inspector.get_unique_constraints(table)}
        with op.batch_alter_table(table) as batch:
            if f"ix_{table}_owner_id" in indexes:
                batch.drop_index(f"ix_{table}_owner_id")
            for key in keys:
                batch.drop_constraint(key, type_="foreignkey")
            if CHECKS[table] in checks:
                batch.drop_constraint(CHECKS[table], type_="check")
            if table == "podcasts" and uniques.get("uq_podcast_name") == ["owner_id", "name"]:
                batch.drop_constraint("uq_podcast_name", type_="unique")
            for column in gone:
                if column in columns:
                    batch.drop_column(column)
            if table == "podcasts":
                batch.create_unique_constraint("uq_podcast_name", ["name"])


def downgrade() -> None:
    raise NotImplementedError("0025 drops whose each podcast was: it cannot come back")
