"""
My World: a per-user library of books, films and other works, behind a
Google sign-in. Runs on Cloud Run with Cloud SQL (PostgreSQL) in production
and on sqlite locally.
"""

import json
import os
import secrets
import urllib.parse
import warnings

import flask
import werkzeug
from flask.json.provider import DefaultJSONProvider
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import auth, views
from myworld.models import make_engine


def load_build_info() -> dict[str, str]:
    """ Load the deploy stamp written by gcloud_run_deploy.sh; absent in dev. """
    try:
        with open("build_info.json", encoding="UTF8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return {"deploy_date": "unknown", "git_describe": "dev"}


def secret_key() -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    if "K_SERVICE" in os.environ:
        raise RuntimeError("SECRET_KEY must be set on Cloud Run (see .gcp.conf)")
    warnings.warn("SECRET_KEY not set: sessions will not survive a restart", stacklevel=1)
    return secrets.token_hex(32)


def create_app(engine: Engine | None = None) -> flask.Flask:
    app = flask.Flask(__name__)
    app.config["SECRET_KEY"] = secret_key()
    if "K_SERVICE" in os.environ and not auth.client_id():
        raise RuntimeError("GOOGLE_CLIENT_ID must be set on Cloud Run (gcp_oauth_client_id in .gcp.conf)")
    # keep KINDS/STATUSES in declaration order in /api/config
    assert isinstance(app.json, DefaultJSONProvider)
    app.json.sort_keys = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = "K_SERVICE" in os.environ
    app.config["build_info"] = load_build_info()
    app.config["engine"] = engine or make_engine()
    # The hostname the service is meant to be reached on (gcp_domain in .gcp.conf); empty in dev.
    app.config["CANONICAL_HOST"] = os.environ.get("CANONICAL_HOST", "")

    @app.before_request
    def redirect_to_canonical_host() -> werkzeug.Response | None:
        # Cloud Run also answers on its run.app hostnames. Send those to the custom domain
        # before anything else happens, so there is one origin for cookies and links and the
        # sign-in providers only ever see the callback URL that is registered with them.
        # The health check is exempt so probes that address the service directly keep working.
        host = app.config["CANONICAL_HOST"]
        if not host or flask.request.host == host or flask.request.path == "/app/health":
            return None
        url = urllib.parse.urlsplit(flask.request.url)._replace(scheme="https", netloc=host).geturl()
        return flask.redirect(url, code=308)

    @app.before_request
    def open_session() -> None:
        flask.g.db = Session(app.config["engine"])

    @app.teardown_request
    def close_session(_exc: BaseException | None) -> None:
        db: Session | None = flask.g.pop("db", None)
        if db is not None:
            db.close()

    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    return app
