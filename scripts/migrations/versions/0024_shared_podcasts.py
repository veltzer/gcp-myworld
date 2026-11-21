"""
Podcasts are shared, the first step (before the deploy): podcasts and
podcast_episodes become everyone's, and what was the user's own on them
goes to two tables of their own. podcasts_heard: a podcast a user listens
to, with their rating and review; episodes_heard: an episode they heard,
when, where, on what device, with their rating and review.

Every account's podcast becomes a podcasts_heard row of it, and every
episode an episodes_heard row; then the podcasts of the same name become
one (the first; the cover of another when it had none), and so do the
episodes of a podcast with the same guid, what pointed at the others
pointing at it. The columns the code after it no longer writes may be
empty, so that it can add rows; 0025 drops them, after the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

RATING = "rating IS NULL OR (rating >= 1 AND rating <= 10)"
# the columns of the user's own that 0025 drops, which the code after the deploy no longer writes: (table, column, type)
NOT_WRITTEN = (
    ("podcasts", "owner_id", sa.Integer()),
    ("podcasts", "review", sa.Text()),
    ("podcast_episodes", "owner_id", sa.Integer()),
    ("podcast_episodes", "review", sa.Text()),
    ("podcast_episodes", "listened_at", sa.String(length=100)),
    ("podcast_episodes", "date_my", sa.String(length=7)),
    ("podcast_episodes", "date_timezone", sa.String(length=64)),
)


def _create_tables() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "podcasts_heard" not in tables:
        op.create_table(
            "podcasts_heard",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("podcast_id", sa.Integer(), sa.ForeignKey("podcasts.id", ondelete="RESTRICT", name="fk_podcasts_heard_podcast_id"), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("review", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("owner_id", "podcast_id", name="uq_podcast_heard"),
            sa.CheckConstraint(RATING, name="ck_podcast_heard_rating_range"),
        )
        op.create_index("ix_podcasts_heard_owner_id", "podcasts_heard", ["owner_id"])
        op.create_index("ix_podcasts_heard_podcast_id", "podcasts_heard", ["podcast_id"])
    if "episodes_heard" not in tables:
        op.create_table(
            "episodes_heard",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("episode_id", sa.Integer(), sa.ForeignKey("podcast_episodes.id", ondelete="RESTRICT", name="fk_episodes_heard_episode_id"), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("review", sa.Text(), nullable=False, server_default=""),
            sa.Column("listened_at", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL", name="fk_episodes_heard_device_id"), nullable=True),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
            sa.UniqueConstraint("owner_id", "episode_id", name="uq_episode_heard"),
            sa.CheckConstraint(RATING, name="ck_episode_heard_rating_range"),
        )
        op.create_index("ix_episodes_heard_owner_id", "episodes_heard", ["owner_id"])
        op.create_index("ix_episodes_heard_episode_id", "episodes_heard", ["episode_id"])


def _copy() -> None:
    """ What was each account's own on its podcasts and episodes, into podcasts_heard and episodes_heard. """
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO podcasts_heard (owner_id, podcast_id, rating, review)"
        " SELECT owner_id, id, rating, review FROM podcasts WHERE owner_id IS NOT NULL"
        " AND id NOT IN (SELECT podcast_id FROM podcasts_heard)"
    ))
    bind.execute(sa.text(
        "INSERT INTO episodes_heard (owner_id, episode_id, rating, review, listened_at, device_id, date_utcz, date_ymd, date_my, date_y, date_timezone)"
        " SELECT owner_id, id, rating, review, listened_at, device_id, date_utcz, date_ymd, date_my, date_y, date_timezone"
        " FROM podcast_episodes WHERE owner_id IS NOT NULL AND id NOT IN (SELECT episode_id FROM episodes_heard)"
    ))


def _merge_podcasts() -> None:
    """ The podcasts of the same name become the first of them. """
    bind = op.get_bind()
    first: dict[str, tuple[int, int | None]] = {}
    for podcast, name, image in bind.execute(sa.text("SELECT id, name, image_id FROM podcasts ORDER BY id")).all():
        if name not in first:
            first[name] = (podcast, image)
            continue
        kept, kept_image = first[name]
        print(f"0024: podcasts ({name!r},) kept once (row {kept}; row {podcast} merged into it)")
        bind.execute(sa.text("UPDATE podcast_episodes SET podcast_id = :kept WHERE podcast_id = :gone"), {"kept": kept, "gone": podcast})
        bind.execute(sa.text("UPDATE podcasts_heard SET podcast_id = :kept WHERE podcast_id = :gone"), {"kept": kept, "gone": podcast})
        if kept_image is None and image is not None:
            bind.execute(sa.text("UPDATE podcasts SET image_id = :image WHERE id = :kept"), {"image": image, "kept": kept})
            first[name] = (kept, image)
        bind.execute(sa.text("DELETE FROM podcasts WHERE id = :gone"), {"gone": podcast})


def _merge_episodes() -> None:
    """ The episodes of a podcast with the same guid become the first of them. """
    bind = op.get_bind()
    first: dict[tuple[int, str], int] = {}
    rows = bind.execute(sa.text("SELECT id, podcast_id, guid FROM podcast_episodes WHERE guid IS NOT NULL ORDER BY id")).all()
    for episode, podcast, guid in rows:
        if (podcast, guid) not in first:
            first[podcast, guid] = episode
            continue
        kept = first[podcast, guid]
        print(f"0024: podcast_episodes ({podcast}, {guid!r}) kept once (row {kept}; row {episode} merged into it)")
        # an account that heard both keeps the first it heard
        bind.execute(sa.text(
            "DELETE FROM episodes_heard WHERE episode_id = :gone AND owner_id IN (SELECT owner_id FROM episodes_heard WHERE episode_id = :kept)"
        ), {"kept": kept, "gone": episode})
        bind.execute(sa.text("UPDATE episodes_heard SET episode_id = :kept WHERE episode_id = :gone"), {"kept": kept, "gone": episode})
        bind.execute(sa.text("DELETE FROM podcast_episodes WHERE id = :gone"), {"gone": episode})


def upgrade() -> None:
    _create_tables()
    bind = op.get_bind()
    if "owner_id" not in {column["name"] for column in sa.inspect(bind).get_columns("podcasts")}:
        # shared already
        return
    _copy()
    # (merging episodes first would miss the ones of two podcasts that become one)
    constraints = {c["name"] for c in sa.inspect(bind).get_unique_constraints("podcast_episodes")}
    with op.batch_alter_table("podcast_episodes") as batch:
        # two accounts' episodes of one podcast clash on it until they are merged
        if "uq_podcast_episode_guid" in constraints:
            batch.drop_constraint("uq_podcast_episode_guid", type_="unique")
    _merge_podcasts()
    _merge_episodes()
    with op.batch_alter_table("podcast_episodes") as batch:
        batch.create_unique_constraint("uq_podcast_episode_guid", ["podcast_id", "guid"])
    for table in ("podcasts", "podcast_episodes"):
        with op.batch_alter_table(table) as batch:
            for name, column, kind in NOT_WRITTEN:
                if name == table:
                    batch.alter_column(column, existing_type=kind, nullable=True)


def downgrade() -> None:
    raise NotImplementedError("0024 makes shared podcasts out of every account's: there is no telling them apart again")
