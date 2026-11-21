"""
A copy of the whole database, for an admin (the Schema page's Download a
dump): every table, every account's rows, the images too, as SQL to load
into an empty database.

On Postgres it is pg_dump's (plain SQL, gzipped, without owners or grants,
so `gunzip -c dump.sql.gz | psql <database>` loads it anywhere), read
through the same socket and credentials the app uses, which never leave
the process; anywhere else (sqlite, development) it is sqlite's own dump.
It is sent as it is made, never kept on disk.
"""

import logging
import os
import subprocess
import zlib
from collections.abc import Iterator

import flask
from sqlalchemy.engine import URL, Engine

from myworld import auth
from myworld.api import ApiError
from myworld.models import ROLE_ADMIN, utcnow

logger = logging.getLogger(__name__)

bp = flask.Blueprint("dump", __name__)

# how much of the dump is read and sent at a time
CHUNK = 1 << 20


def pg_dump_command(url: URL) -> tuple[list[str], dict[str, str]]:
    """
    The pg_dump that dumps the database url names, and its environment: the
    connection goes in libpq's variables (a Cloud SQL socket, unix_sock, as
    its directory), the password too, never on the command line.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    socket = url.query.get("unix_sock")
    if isinstance(socket, tuple):
        socket = socket[0]
    if socket:
        env["PGHOST"] = os.path.dirname(socket)
        env["PGPORT"] = socket.rsplit(".", 1)[-1]
    else:
        env["PGHOST"] = url.host or "localhost"
        env["PGPORT"] = str(url.port or 5432)
    env["PGUSER"] = url.username or ""
    env["PGPASSWORD"] = url.password or ""
    env["PGDATABASE"] = url.database or ""
    return ["pg_dump", "--no-owner", "--no-privileges", "--compress=6"], env


def _pg_dump(url: URL) -> Iterator[bytes]:
    command, env = pg_dump_command(url)
    try:
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        raise ApiError(500, "pg_dump is not installed here") from e
    assert process.stdout is not None and process.stderr is not None
    # the first of it is read before answering, so a dump that cannot start says why (an error, not an empty file)
    first = process.stdout.read(CHUNK)
    if not first:
        process.wait()
        raise ApiError(500, f"pg_dump failed: {process.stderr.read().decode(errors='replace').strip()}")

    def rest() -> Iterator[bytes]:
        assert process.stdout is not None and process.stderr is not None
        yield first
        while chunk := process.stdout.read(CHUNK):
            yield chunk
        if process.wait() != 0:
            # too late to say so in the answer: the file is cut short, which gunzip reports
            logger.error("pg_dump failed midway: %s", process.stderr.read().decode(errors="replace").strip())

    return rest()


def _sqlite_dump(engine: Engine) -> Iterator[bytes]:
    """ sqlite's own dump (development), gzipped as it goes. """
    connection = engine.raw_connection()
    compressor = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    try:
        sqlite = connection.driver_connection
        assert sqlite is not None
        lines: list[str] = []
        for line in sqlite.iterdump():  # type: ignore[attr-defined]
            lines.append(line + "\n")
            if len(lines) >= 1000:
                yield compressor.compress("".join(lines).encode())
                lines = []
        yield compressor.compress("".join(lines).encode()) + compressor.flush()
    finally:
        connection.close()


@bp.route("/api/admin/dump", methods=["GET"])
@auth.login_required
def api_dump() -> flask.Response:
    """ The whole database as SQL, gzipped, downloaded as myworld-<when>.sql.gz: an admin's only. """
    if flask.g.user.role != ROLE_ADMIN:
        raise ApiError(403, "only an admin may download the database")
    engine: Engine = flask.current_app.config["engine"]
    when = utcnow().strftime("%Y-%m-%d-%H%M%S")
    logger.info("user %s (%s) downloads a dump of the database", flask.g.user.id, flask.g.user.email)
    stream = _pg_dump(engine.url) if engine.url.get_backend_name() == "postgresql" else _sqlite_dump(engine)
    response = flask.Response(flask.stream_with_context(stream), mimetype="application/gzip")
    response.headers["Content-Disposition"] = f'attachment; filename="myworld-{when}.sql.gz"'
    response.headers["Cache-Control"] = "no-store"
    return response

