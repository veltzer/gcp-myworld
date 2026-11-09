# The Schema page

The Schema page (top bar, admins only; see `accounts.md`) shows the
structure of the database as the database itself reports it, not as the
code describes it: SQLAlchemy's inspector reads the catalog (PostgreSQL's
`information_schema` and `pg_catalog` in production, sqlite's `PRAGMA`s
locally) through `GET /api/schema`.

- **The diagram:** every table with its keys, and a line for each
  foreign key ("many of this table to one of that"; a key that may be
  empty is "zero or one"), drawn by Mermaid, loaded from cdnjs with its
  integrity hash the first time the page is opened.
- **The tables:** each with its row count and every column (type,
  whether it may be empty, default, key), then its foreign keys (and what
  happens on delete), unique constraints, indexes and check constraints.
- **Drift:** where the database and the code's models differ, in red at
  the top: a column the code has and the database lacks (a
  `scripts/migrate.sh` step still to run), one the database has and the
  code does not (left behind), and whole tables either way.

Other tools read the same catalog for documentation outside the app:
SchemaSpy and SchemaCrawler make HTML pages and diagrams of a whole
database, and `eralchemy` draws an ER diagram from a database URL.
