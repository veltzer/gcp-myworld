"""
Views (shared_views): named selections of a user's own data sets that
anyone may open at /view/<username>/<name>, read only (doc/views.md).
Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "shared_views" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "shared_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("datasets", sa.JSON(), nullable=False),
        sa.Column("access", sa.String(length=20), nullable=False, server_default="public"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_shared_view_owner_name"),
    )
    op.create_index("ix_shared_views_owner_id", "shared_views", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_shared_views_owner_id", table_name="shared_views")
    op.drop_table("shared_views")
