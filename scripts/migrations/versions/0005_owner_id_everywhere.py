"""
Whose a row is, is owner_id on every table, and a work is its account's own.
The columns that said it as user_id (logins, disabled_checks, the library's
entries and what hangs on them) are renamed, with the index and, where the
database names them after the column, the foreign keys. library_works gets
an owner_id: a work is the row of the account that has it, so one that two
accounts have becomes two, each with its titles, and each account's entry
(its readings, covers, ownings and authors with it) points at its own. A
work no account has goes to the oldest account.

A rename serves neither the code before it nor the code after it in both
orders: deploy, then run this at once. The site fails in between.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# the tables whose user_id becomes owner_id
RENAMED = ("logins", "disabled_checks", "library_entries", "library_reads", "library_covers", "library_ownings", "library_entry_authors")
# what hangs on a library entry, by its owner and its work
OF_AN_ENTRY = ("library_reads", "library_covers", "library_ownings", "library_entry_authors")
IDENTITY = ["kind", "title", "creator", "year"]


def _columns(table: str) -> list[str]:
    return [column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)]


def _rename(old: str, new: str) -> None:
    """ The column old of every table in RENAMED that has one becomes new, and what is named after it follows. """
    bind = op.get_bind()
    for table in RENAMED:
        if old not in _columns(table):
            # a database marked as being at the baseline may already have the tables of today
            continue
        bind.execute(sa.text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"))
        if bind.dialect.name == "postgresql":
            for key in sa.inspect(bind).get_foreign_keys(table):
                if key["name"] == f"{table}_{old}_fkey":
                    bind.execute(sa.text(f"ALTER TABLE {table} RENAME CONSTRAINT {table}_{old}_fkey TO {table}_{new}_fkey"))
    if f"ix_logins_{old}" in {index["name"] for index in sa.inspect(bind).get_indexes("logins")}:
        op.drop_index(f"ix_logins_{old}", table_name="logins")
        op.create_index(f"ix_logins_{new}", "logins", [new])


def _own_works() -> None:
    """ Every work gets the account that has it; one that several have becomes one for each. """
    bind = op.get_bind()
    copied = ", ".join(column for column in _columns("library_works") if column not in ("id", "owner_id"))
    kept = ", ".join(column for column in _columns("library_entries") if column != "work_id")
    owner_of: dict[int, int] = {}
    for work, owner in bind.execute(sa.text("SELECT work_id, owner_id FROM library_entries ORDER BY work_id, owner_id")).all():
        if work not in owner_of:
            owner_of[work] = owner
            bind.execute(sa.text("UPDATE library_works SET owner_id = :owner WHERE id = :work"), {"owner": owner, "work": work})
            continue
        # another account has it too: a work of its own, as the first's is, and its entry moved to it
        ids = {"owner": owner, "work": work}
        ids["own"] = bind.execute(
            sa.text(f"INSERT INTO library_works (owner_id, {copied}) SELECT :owner, {copied} FROM library_works WHERE id = :work RETURNING id"), ids,
        ).scalar_one()
        bind.execute(sa.text("INSERT INTO library_work_titles (work_id, locale, title) SELECT :own, locale, title FROM library_work_titles WHERE work_id = :work ORDER BY id"), ids)
        bind.execute(sa.text(f"INSERT INTO library_entries (work_id, {kept}) SELECT :own, {kept} FROM library_entries WHERE owner_id = :owner AND work_id = :work"), ids)
        for table in OF_AN_ENTRY:
            bind.execute(sa.text(f"UPDATE {table} SET work_id = :own WHERE owner_id = :owner AND work_id = :work"), ids)
        bind.execute(sa.text("DELETE FROM library_entries WHERE owner_id = :owner AND work_id = :work"), ids)
    # a work no account has (its entry was deleted while works were shared) is kept: the oldest account's
    bind.execute(sa.text("UPDATE library_works SET owner_id = (SELECT MIN(id) FROM users) WHERE owner_id IS NULL"))
    # (with no account at all there is nobody whose it could be)
    bind.execute(sa.text("DELETE FROM library_works WHERE owner_id IS NULL"))


def upgrade() -> None:
    _rename("user_id", "owner_id")
    if "owner_id" in _columns("library_works"):
        return
    uniques = {unique["name"] for unique in sa.inspect(op.get_bind()).get_unique_constraints("library_works")}
    with op.batch_alter_table("library_works") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        # two accounts may have a work of the same title, author and year: each its own
        if "uq_work_identity" in uniques:
            batch.drop_constraint("uq_work_identity", type_="unique")
    _own_works()
    with op.batch_alter_table("library_works") as batch:
        batch.alter_column("owner_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("library_works_owner_id_fkey", "users", ["owner_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_library_works_owner_id", ["owner_id"])
        batch.create_unique_constraint("uq_work_identity", ["owner_id", *IDENTITY])


def downgrade() -> None:
    """ The works stay one for each account: where two accounts have the same one, the constraint of before refuses, and they are merged by hand first. """
    with op.batch_alter_table("library_works") as batch:
        batch.drop_constraint("uq_work_identity", type_="unique")
        batch.drop_index("ix_library_works_owner_id")
        batch.drop_constraint("library_works_owner_id_fkey", type_="foreignkey")
        batch.drop_column("owner_id")
        batch.create_unique_constraint("uq_work_identity", IDENTITY)
    _rename("owner_id", "user_id")
