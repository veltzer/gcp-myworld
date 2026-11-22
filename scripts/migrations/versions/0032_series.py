"""
Series are films of another kind (adds, before the deploy): films.kind
says which (every film there is stays a film), and a watch of a series
says the seasons seen and those known not to have been
(film_watches.seasons_seen, seasons_not_seen), each empty to start with.
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    films = {column["name"] for column in inspector.get_columns("films")}
    watches = {column["name"] for column in inspector.get_columns("film_watches")}
    if "kind" not in films:
        with op.batch_alter_table("films") as batch:
            batch.add_column(sa.Column("kind", sa.String(length=20), nullable=False, server_default="film"))
    with op.batch_alter_table("film_watches") as batch:
        for name in ("seasons_seen", "seasons_not_seen"):
            if name not in watches:
                batch.add_column(sa.Column(name, sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("film_watches") as batch:
        batch.drop_column("seasons_not_seen")
        batch.drop_column("seasons_seen")
    with op.batch_alter_table("films") as batch:
        batch.drop_column("kind")
