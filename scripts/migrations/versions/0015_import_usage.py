"""
The runs a user started in a month are counted apart from the runs
(import_usage), so the Imports page's Clear can delete runs, records and
logs, without giving back any of the month's runs. The count is filled from
the runs there are; the runs an earlier Clear only hid (cleared_at) are
deleted, as Clear now does. Nothing the runs imported is touched.
Adding: run before the deploy (0016 drops cleared_at after it).
"""

import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "import_usage" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "import_usage",
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("month", sa.Date(), primary_key=True),
            sa.Column("runs", sa.Integer(), nullable=False),
        )
    usage = sa.table("import_usage", sa.column("owner_id", sa.Integer()), sa.column("month", sa.Date()), sa.column("runs", sa.Integer()))
    if bind.execute(sa.select(sa.func.count()).select_from(usage)).scalar():
        return
    counts: dict[tuple[int, datetime.date], int] = {}
    for owner_id, started_at in bind.execute(sa.text("SELECT owner_id, started_at FROM import_runs")):
        started: Any = started_at
        if isinstance(started, str):
            started = datetime.datetime.fromisoformat(started)
        month = started.date().replace(day=1)
        counts[(owner_id, month)] = counts.get((owner_id, month), 0) + 1
    if counts:
        op.bulk_insert(usage, [{"owner_id": owner_id, "month": month, "runs": runs} for (owner_id, month), runs in counts.items()])
    if "cleared_at" in {column["name"] for column in sa.inspect(bind).get_columns("import_runs")}:
        bind.execute(sa.text("DELETE FROM import_runs WHERE cleared_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("import_usage")
