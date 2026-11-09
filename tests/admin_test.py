"""
Roles: every account is a user; an admin also sees every account and gives
or takes the admin role, but the last admin cannot be demoted.
"""

import webtest
from sqlalchemy import update
from sqlalchemy.engine import Engine

from myworld.models import ROLE_ADMIN, User
from tests.conftest import sign_in


def make_admin(engine: Engine, sub: str) -> None:
    """ What scripts/migrate.sh does for the first admin. """
    with engine.begin() as connection:
        connection.execute(update(User).where(User.google_sub == sub).values(role=ROLE_ADMIN))


def test_new_accounts_are_users(app: webtest.TestApp) -> None:
    sign_in(app)
    assert app.get("/api/config").json["user"]["role"] == "user"
    app.get("/api/users", status=403)
    app.put_json("/api/users/1", {"role": "admin"}, status=403)


def test_users_api_needs_sign_in(app: webtest.TestApp) -> None:
    app.get("/api/users", status=401)


def test_admin_delegates(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app, "bob")
    app.post("/auth/logout")
    sign_in(app, "alice")
    make_admin(engine, "alice")
    assert app.get("/api/config").json["user"]["role"] == "admin"
    users = app.get("/api/users").json
    assert [(u["id"], u["provider"], u["role"]) for u in users] == [(1, "google", "user"), (2, "google", "admin")]
    # the last admin stays one
    app.put_json("/api/users/2", {"role": "user"}, status=409)
    app.put_json("/api/users/1", {"role": "root"}, status=400)
    app.put_json("/api/users/99", {"role": "admin"}, status=404)
    # delegate to bob, then step down
    assert app.put_json("/api/users/1", {"role": "admin"}).json["role"] == "admin"
    assert app.put_json("/api/users/2", {"role": "user"}).json["role"] == "user"
    # a demotion takes effect at once, without signing out
    app.get("/api/users", status=403)
    app.post("/auth/logout")
    sign_in(app, "bob")
    assert [u["role"] for u in app.get("/api/users").json] == ["admin", "user"]


def test_schema_is_read_from_the_database(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app, "alice")
    app.get("/api/schema", status=403)
    make_admin(engine, "alice")
    schema = app.get("/api/schema").json
    assert schema["dialect"] == "sqlite"
    tables = {t["name"]: t for t in schema["tables"]}
    # every table of the code, and nothing more, nothing less: no drift
    assert schema["missing"] == []
    assert all(t["in_model"] and not t["only_in_model"] and not t["only_in_database"] for t in tables.values())
    users = tables["users"]
    assert users["rows"] == 1
    assert next(c for c in users["columns"] if c["name"] == "id")["primary_key"]
    videos = tables["youtube_videos"]
    assert {"youtube_id", "channel", "unavailable"} <= {c["name"] for c in videos["columns"]}
    assert {"table": "devices", "columns": ["device_id"], "referred": ["id"], "on_delete": "SET NULL"}.items() <= next(
        fk for fk in videos["foreign_keys"] if fk["table"] == "devices").items()
    assert ["owner_id", "youtube_id"] in [u["columns"] for u in videos["unique"]]
    # a column a migration left behind shows as drift
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE devices ADD COLUMN leftover INTEGER")
    devices = next(t for t in app.get("/api/schema").json["tables"] if t["name"] == "devices")
    assert devices["only_in_database"] == ["leftover"]
