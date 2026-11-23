"""
Certifications (adds, before the deploy): each account's own, a
certification it holds once by its name, with the organization that issued
it (one of the account's organizations; a deleted one leaves it issued by no
one known), its kind (instructor, professional), when it was given and a
remark.
"""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "certifications" not in tables:
        op.create_table(
            "certifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=300), nullable=False),
            sa.Column(
                "organization_id", sa.Integer(),
                sa.ForeignKey("organizations.id", ondelete="SET NULL", name="fk_certifications_organization_id"), nullable=True,
            ),
            sa.Column("kind", sa.String(length=50), nullable=False, server_default=""),
            sa.Column("remark", sa.Text(), nullable=False, server_default=""),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
            sa.UniqueConstraint("owner_id", "name", name="uq_certification_name"),
        )
        op.create_index("ix_certifications_owner_id", "certifications", ["owner_id"])
        op.create_index("ix_certifications_organization_id", "certifications", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_certifications_organization_id", table_name="certifications")
    op.drop_index("ix_certifications_owner_id", table_name="certifications")
    op.drop_table("certifications")
