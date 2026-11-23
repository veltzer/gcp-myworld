"""
Courses (adds, before the deploy): each account's own, the courses it took
other than audio courses, once by name: the organization taken through
(provider) and the one that gave it (school), both the account's
organizations (one deleted leaves no one known), who taught it, when it was
finished and a remark.
"""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "courses" not in tables:
        op.create_table(
            "courses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=300), nullable=False),
            sa.Column("provider_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL", name="fk_courses_provider_id"), nullable=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL", name="fk_courses_school_id"), nullable=True),
            sa.Column("remark", sa.Text(), nullable=False, server_default=""),
            sa.Column("date_utcz", sa.DateTime(), nullable=True),
            sa.Column("date_ymd", sa.Date(), nullable=True),
            sa.Column("date_my", sa.String(length=7), nullable=False, server_default=""),
            sa.Column("date_y", sa.Integer(), nullable=True),
            sa.Column("date_timezone", sa.String(length=64), nullable=False, server_default=""),
            sa.UniqueConstraint("owner_id", "name", name="uq_course_name"),
        )
        op.create_index("ix_courses_owner_id", "courses", ["owner_id"])
        op.create_index("ix_courses_provider_id", "courses", ["provider_id"])
        op.create_index("ix_courses_school_id", "courses", ["school_id"])
        op.create_table(
            "course_lecturers",
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("person_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
        )


def downgrade() -> None:
    op.drop_table("course_lecturers")
    op.drop_table("courses")
