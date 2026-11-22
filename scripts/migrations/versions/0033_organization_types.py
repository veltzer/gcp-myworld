"""
An organization has any number of types, the first step (before the
deploy): organization_type_links (BBC Radio is a Public body and a
Publisher) gets the one type each organization had (organizations.type_id).
0034 drops organizations.type_id, after the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organization_type_links" not in inspector.get_table_names():
        op.create_table(
            "organization_type_links",
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("organization_type_id", sa.Integer(), sa.ForeignKey("organization_types.id", ondelete="CASCADE"), primary_key=True),
        )
    if "type_id" not in {column["name"] for column in inspector.get_columns("organizations")}:
        # moved already
        return
    bind.execute(sa.text(
        "INSERT INTO organization_type_links (organization_id, organization_type_id)"
        " SELECT o.id, o.type_id FROM organizations o WHERE o.type_id IS NOT NULL AND NOT EXISTS"
        " (SELECT 1 FROM organization_type_links l WHERE l.organization_id = o.id AND l.organization_type_id = o.type_id)"
    ))


def downgrade() -> None:
    op.drop_table("organization_type_links")
