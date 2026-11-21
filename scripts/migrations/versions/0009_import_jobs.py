"""
Importers run as jobs of their own (Cloud Run Jobs), not inside the request
that asks for them: a run is queued, then running, then done or failed, and
its job says it is alive (heartbeat_at) as it goes; execution names the
Cloud Run Jobs execution. Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("import_runs")}
    with op.batch_alter_table("import_runs") as batch:
        if "heartbeat_at" not in have:
            batch.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        if "execution" not in have:
            batch.add_column(sa.Column("execution", sa.String(length=300), nullable=False, server_default=""))
        batch.drop_constraint("ck_import_run_status", type_="check")
        batch.create_check_constraint("ck_import_run_status", "status IN ('queued', 'running', 'done', 'failed')")


def downgrade() -> None:
    op.execute("UPDATE import_runs SET status = 'failed' WHERE status IN ('queued', 'running')")
    with op.batch_alter_table("import_runs") as batch:
        batch.drop_constraint("ck_import_run_status", type_="check")
        batch.create_check_constraint("ck_import_run_status", "status IN ('done', 'failed')")
        batch.drop_column("execution")
        batch.drop_column("heartbeat_at")
