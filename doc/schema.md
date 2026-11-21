# The Schema page

The Schema page (sidebar, Overview, admins only; see `accounts.md`) shows the
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
- **Download a dump of the database:** the whole database, every table
  and every account's rows, images too, as SQL, gzipped
  (`myworld-<when>.sql.gz`, `GET /api/admin/dump`, admins only, 403 for
  anyone else). In production it is `pg_dump --no-owner --no-privileges`
  (the image installs Debian's `postgresql-client`, the server's major
  version), connected through the app's own Cloud SQL socket and
  credentials, which go to it in its environment, never on its command
  line; locally, sqlite's own dump. It is made as it downloads and kept
  nowhere. To load it: `gunzip -c myworld-<when>.sql.gz | psql <empty
  database>`. A dump that cannot start says why; one that fails midway is
  cut short, which `gunzip` reports (and the app logs).

Other tools read the same catalog for documentation outside the app:
SchemaSpy and SchemaCrawler make HTML pages and diagrams of a whole
database, and `eralchemy` draws an ER diagram from a database URL.
