"""
Make src/ importable and give every test a fresh app on an in-memory
sqlite database, with Google token verification stubbed out.
"""

import os
import sys
from collections.abc import Iterator
from typing import Any

import pytest
import webtest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

# pylint: disable=wrong-import-position
from myworld import auth, create_app
from myworld.models import Base

FAKE_CLAIMS: dict[str, Any] = {
    "sub": "1234567890",
    "email": "alice@example.com",
    "name": "Alice",
    "picture": "https://example.com/alice.png",
}


@pytest.fixture(name="app")
def fixture_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[webtest.TestApp]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(auth, "verify_google_token", lambda token: dict(FAKE_CLAIMS, sub=token))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield webtest.TestApp(create_app(engine))
    engine.dispose()


def sign_in(app: webtest.TestApp, sub: str = "1234567890") -> None:
    """ Go through /auth/login the way the Google button would. """
    app.set_cookie("g_csrf_token", "csrf")
    response = app.post("/auth/login", {"credential": sub, "g_csrf_token": "csrf"})
    assert response.status_int == 302
