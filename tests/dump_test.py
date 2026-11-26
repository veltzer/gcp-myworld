"""
An admin's copy of the whole database: SQL, gzipped, every account's rows;
pg_dump's on Postgres, connected as the app is.
"""

import contextlib
import gzip
import sqlite3
from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine, make_url

from myworld import dump
from tests.conftest import sign_in, sign_in_admin

if TYPE_CHECKING:
    import webtest


def test_only_an_admin_downloads_the_database(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app)
    assert app.get("/api/admin/dump", status=403).json == {"error": "only an admin may download the database"}
    app.post_json("/api/concert-visits", {"name": "Jarrett"}, status=201)
    sign_in_admin(app, engine, sub="the-admin")
    response = app.get("/api/admin/dump")
    assert response.content_type == "application/gzip"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="myworld-')
    sql = gzip.decompress(response.body).decode()
    # every table, and another account's rows too
    assert "CREATE TABLE concert_visits" in sql or 'CREATE TABLE "concert_visits"' in sql
    assert "Jarrett" in sql
    # and it loads into an empty database
    with contextlib.closing(sqlite3.connect(":memory:")) as copy:
        copy.executescript(sql)
        assert copy.execute("SELECT name FROM concert_visits").fetchall() == [("Jarrett",)]


def test_pg_dump_connects_as_the_app_does() -> None:
    # Cloud Run: the Cloud SQL socket, and the password in the environment, never on the command line
    command, env = dump.pg_dump_command(make_url("postgresql+pg8000://me:secret@/myworld?unix_sock=/cloudsql/p:r:i/.s.PGSQL.5432"))
    assert command == ["pg_dump", "--no-owner", "--no-privileges", "--compress=6"]
    assert "secret" not in " ".join(command)
    assert (env["PGHOST"], env["PGPORT"], env["PGUSER"], env["PGPASSWORD"], env["PGDATABASE"]) == ("/cloudsql/p:r:i", "5432", "me", "secret", "myworld")
    # elsewhere: a host and a port
    _command, env = dump.pg_dump_command(make_url("postgresql+pg8000://postgres@127.0.0.1:54329/myworld"))
    assert (env["PGHOST"], env["PGPORT"], env["PGUSER"], env["PGDATABASE"]) == ("127.0.0.1", "54329", "postgres", "myworld")
