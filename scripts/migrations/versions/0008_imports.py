"""
The importers run from the Imports page: youtube_connections, the YouTube
account each user connected (an encrypted refresh token), and import_runs,
a row for each run of an importer. Adding tables: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "youtube_connections" not in have:
        op.create_table(
            "youtube_connections",
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("refresh_token", sa.Text(), nullable=False),
            sa.Column("channel", sa.String(length=200), nullable=False),
            sa.Column("connected_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("owner_id"),
        )
    if "import_runs" not in have:
        op.create_table(
            "import_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("importer", sa.String(length=100), nullable=False),
            sa.Column("params", sa.JSON(), nullable=False),
            sa.Column("dry_run", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("counts", sa.JSON(), nullable=False),
            sa.Column("log", sa.Text(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("status IN ('done', 'failed')", name="ck_import_run_status"),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("import_runs") as batch:
            batch.create_index(batch.f("ix_import_runs_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("import_runs") as batch:
        batch.drop_index(batch.f("ix_import_runs_owner_id"))
    op.drop_table("import_runs")
    op.drop_table("youtube_connections")
