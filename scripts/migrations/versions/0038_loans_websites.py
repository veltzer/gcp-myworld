"""
Loans and websites (adds, before the deploy): each account's own. A loan:
what was lent, to whom (one of the account's people; one deleted leaves no
one known), when, whether it came back and a remark. A website: its name,
address (once in an account), topic and a remark.
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "loans" not in tables:
        op.create_table(
            "loans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=300), nullable=False),
            sa.Column("person_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="SET NULL", name="fk_loans_person_id"), nullable=True),
            sa.Column("returned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("remark", sa.Text(), nullable=False, server_default=""),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
        )
        op.create_index("ix_loans_owner_id", "loans", ["owner_id"])
        op.create_index("ix_loans_person_id", "loans", ["person_id"])
    if "websites" not in tables:
        op.create_table(
            "websites",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=300), nullable=False),
            sa.Column("url", sa.String(length=1000), nullable=False),
            sa.Column("topic", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("remark", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("owner_id", "url", name="uq_website_url"),
        )
        op.create_index("ix_websites_owner_id", "websites", ["owner_id"])


def downgrade() -> None:
    op.drop_table("websites")
    op.drop_table("loans")
