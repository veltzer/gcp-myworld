"""
The Audible connection and its importer (myworld.audible,
myworld.importers.audible_library), against an Amazon and an Audible that
are faked: the sign-in address, registering the device, the signed library
requests, importing the library, and that a second run adds nothing.
"""

import base64
import datetime
import urllib.parse
from typing import Any

import pytest
import webtest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import audible
from myworld.importers import core, jobs
from myworld.models import AudibleConnection, AudioBook, AudioBookListen, Image
from tests.conftest import sign_in

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# as Amazon gives a device's key
PRIVATE_KEY = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode()
ADP_TOKEN = "{enc:adp-token-of-alice}"
REFRESH = "Atnr|refresh-of-alice"
COVER = b"\xff\xd8sense"


def book(asin: str, title: str, **more: Any) -> dict[str, Any]:
    """ A book as the library API says it. """
    return {
        "asin": asin, "title": title, "subtitle": None, "authors": [{"name": "Sam Harris"}], "narrators": [{"name": "Sam Harris"}, {"name": "David Chalmers"}],
        "series": None, "runtime_length_min": 1346, "is_finished": True, "percent_complete": 0.0,
        "rating": {"overall_distribution": {"display_average_rating": "4.7", "num_ratings": 592}},
        "category_ladders": [
            {"ladder": [{"id": "1", "name": "Science"}, {"id": "2", "name": "Physics"}], "root": "Genres"},
            {"ladder": [{"id": "1", "name": "Science"}, {"id": "3", "name": "Biology"}], "root": "Genres"},
        ],
        "library_status": {"date_added": "2021-08-10T08:55:06.867Z"}, "release_date": "2020-08-11",
        "product_images": {"500": f"https://m.media-amazon.com/images/I/{asin}.jpg"}, "purchase_date": "2021-08-11T00:00:00Z",
        **more,
    }


class FakeAudible:
    """ Amazon's device endpoints and Audible's library, for an account called Alice with two books. """

    def __init__(self) -> None:
        self.books = [
            book("0063005409", "Making Sense"),
            book("B07D23CFGR", "Political Order", series=[{"title": "Political Order", "sequence": "2"}], is_finished=False, percent_complete=12.5,
                 product_images={}, rating=None, runtime_length_min=None, release_date=None),
        ]
        self.deregistered: list[str] = []
        self.registered: list[dict[str, Any]] = []

    def amazon_post(self, url: str, *, json: dict[str, Any] | None = None, data: dict[str, str] | None = None,
                    headers: dict[str, str] | None = None) -> dict[str, Any]:
        if url == "https://api.amazon.com/auth/register":
            assert json is not None
            self.registered.append(json)
            if json["auth_data"]["authorization_code"] != "good-code":
                raise audible.AudibleError("Amazon answered 400: the code is not good")
            return {"response": {"success": {
                "tokens": {"mac_dms": {"adp_token": ADP_TOKEN, "device_private_key": PRIVATE_KEY}, "bearer": {"refresh_token": REFRESH, "access_token": "a", "expires_in": "3600"}},
                "extensions": {"customer_info": {"name": "Alice"}, "device_info": {"device_name": "Alice's My World"}},
            }}}
        if url == "https://api.amazon.com/auth/token":
            assert data is not None and data["source_token"] == REFRESH
            return {"access_token": "access-of-alice", "expires_in": 3600}
        if url == "https://api.amazon.com/auth/deregister":
            assert headers == {"Authorization": "Bearer access-of-alice"}
            self.deregistered.append(REFRESH)
            return {"response": {"success": {}}}
        raise AssertionError(url)

    def api_get(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        parts = urllib.parse.urlsplit(url)
        assert (parts.scheme, parts.netloc, parts.path) == ("https", "api.audible.com", "/1.0/library")
        # signed as the device: method, path and query, moment, body, ADP token
        assert headers["x-adp-token"] == ADP_TOKEN and headers["x-adp-alg"] == "SHA256withRSA:1.0"
        signature, moment = headers["x-adp-signature"].split(":", 1)
        signed = f"GET\n{parts.path}?{parts.query}\n{moment}\n\n{ADP_TOKEN}".encode()
        KEY.public_key().verify(base64.b64decode(signature), signed, padding.PKCS1v15(), hashes.SHA256())
        query = urllib.parse.parse_qs(parts.query)
        assert "category_ladders" in query["response_groups"][0]
        # a page at a time
        size, page = int(query["num_results"][0]), int(query["page"][0])
        return {"items": self.books[(page - 1) * size:page * size]}

    @staticmethod
    def fetch_cover(url: str) -> bytes | None:
        return COVER if url.endswith("/0063005409.jpg") else None


@pytest.fixture(autouse=True)
def fixture_inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ A run's job is done right away, inside the request that starts it. """
    def dispatcher(engine: Engine) -> Any:
        def dispatch(run_id: int) -> str:
            core.execute(engine, run_id)
            return f"projects/p/locations/r/jobs/myworld-import/executions/run-{run_id}"
        return dispatch
    monkeypatch.setattr(jobs, "dispatcher", dispatcher)


@pytest.fixture(name="fake")
def fixture_fake(monkeypatch: pytest.MonkeyPatch) -> FakeAudible:
    fake = FakeAudible()
    monkeypatch.setattr(audible, "amazon_post", fake.amazon_post)
    monkeypatch.setattr(audible, "api_get", fake.api_get)
    monkeypatch.setattr(audible, "fetch_cover", fake.fetch_cover)
    return fake


def connect(app: webtest.TestApp) -> dict[str, Any]:
    """ Begin the sign-in, sign in at Amazon (faked), and paste back where it ended. """
    url = app.post("/audible/connect/start").json["url"]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    landing = f"{query['openid.return_to'][0]}?openid.assoc_handle=amzn_audible_ios_us&openid.oa2.authorization_code=good-code"
    status: dict[str, Any] = app.post_json("/audible/connect/finish", {"address": landing}).json
    return status


def run(app: webtest.TestApp, status: int = 202) -> Any:
    return app.post_json("/api/importers/audible-library/runs", {"params": {}, "dry_run": False}, status=status).json


def test_the_sign_in_address_is_amazons_for_a_new_device(app: webtest.TestApp) -> None:
    sign_in(app)
    url = app.post("/audible/connect/start").json["url"]
    parts = urllib.parse.urlsplit(url)
    assert (parts.netloc, parts.path) == ("www.amazon.com", "/ap/signin")
    query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
    assert (query["openid.oa2.response_type"], query["openid.oa2.code_challenge_method"], query["openid.oa2.scope"]) == ("code", "S256", "device_auth_access")
    assert query["openid.return_to"] == "https://www.amazon.com/ap/maplanding"
    assert query["marketPlaceId"] == "AF2M0KC94RCEA"
    # the client is the device to be: its serial and type, hex encoded
    serial, device_type = bytes.fromhex(query["openid.oa2.client_id"].removeprefix("device:")).decode().split("#")
    assert (len(serial), device_type) == (32, audible.DEVICE_TYPE)
    # the challenge is of a verifier the page never sees
    assert len(query["openid.oa2.code_challenge"]) == 43


def test_the_code_is_read_from_the_address_amazon_ended_on() -> None:
    assert audible.code_from("https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=ANxyz&openid.mode=id_res") == "ANxyz"
    for wrong in ("", "https://www.amazon.com/ap/maplanding", "not an address"):
        with pytest.raises(audible.AudibleError, match="no sign-in code"):
            audible.code_from(wrong)


def test_connecting_registers_a_device_and_keeps_its_tokens_sealed(app: webtest.TestApp, engine: Engine, fake: FakeAudible) -> None:
    sign_in(app)
    assert app.get("/audible/status").json["connected"] is False
    status = connect(app)
    assert (status["connected"], status["name"], status["store"]) == (True, "Alice", "audible.com")
    # the code was traded with the verifier of the same sign-in, for the device begun there
    sent = fake.registered[0]
    assert sent["auth_data"]["authorization_code"] == "good-code" and sent["auth_data"]["code_verifier"]
    assert sent["registration_data"]["device_type"] == audible.DEVICE_TYPE
    assert sent["auth_data"]["client_id"] == audible.client_id(sent["registration_data"]["device_serial"])
    with Session(engine) as session:
        kept = session.scalars(select(AudibleConnection)).one()
        # nothing of the tokens is in the database as it is
        for value in (kept.adp_token, kept.private_key, kept.refresh_token):
            assert ADP_TOKEN not in value and "PRIVATE KEY" not in value and REFRESH not in value
    # one sign-in, one finish
    app.post_json("/audible/connect/finish", {"address": "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=good-code"}, status=400)


def test_a_bad_address_or_code_connects_nothing(app: webtest.TestApp, engine: Engine, fake: FakeAudible) -> None:
    del fake
    sign_in(app)
    # no sign-in begun
    assert "no sign-in was begun" in app.post_json("/audible/connect/finish", {"address": "x"}, status=400).json["error"]
    app.post("/audible/connect/start")
    assert "no sign-in code" in app.post_json("/audible/connect/finish", {"address": "https://www.amazon.com/ap/maplanding"}, status=400).json["error"]
    bad = "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=bad-code"
    assert "not good" in app.post_json("/audible/connect/finish", {"address": bad}, status=400).json["error"]
    with Session(engine) as session:
        assert session.scalars(select(AudibleConnection)).all() == []


def test_importing_the_library_adds_each_book_once_and_again_adds_nothing(app: webtest.TestApp, engine: Engine, fake: FakeAudible, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app)
    importer = next(i for i in app.get("/api/importers").json["importers"] if i["name"] == "audible-library")
    assert (importer["unavailable"], importer["dataset"]) == ("Connect Audible first", "audio-book-listens")
    assert run(app, status=400)["error"] == "Connect Audible first"
    connect(app)
    done = run(app)
    assert done["status"] == "done", done
    assert done["counts"] == {"audio books added": 2, "covers added": 1}
    # the log says what was done to each book
    assert "+ Making Sense (0063005409): added, a new book, with its cover" in done["log"]
    assert "+ Political Order (B07D23CFGR): added, a new book, no cover: Audible gave none" in done["log"]
    listens = {b["asin"]: b for b in app.get("/api/audio-book-listens").json}
    sense, order = listens["0063005409"], listens["B07D23CFGR"]
    assert (sense["kind"], sense["name"], sense["authors"], sense["narrators"]) == ("audible", "Making Sense", "Sam Harris", "Sam Harris, David Chalmers")
    # the genres as the library lists them: each path from its top genre down
    assert sense["genres"] == ["Science", "Physics", "Science", "Biology"]
    assert (sense["minutes"], sense["finished"], sense["source_rating"], sense["source_ratings"]) == (1346, True, 4.7, 592)
    assert (sense["added"], sense["purchased"], sense["released"]) == ("2021-08-10T08:55:06.867000Z", "2021-08-11T00:00:00Z", "2020-08-11")
    assert sense["cover_url"] == "https://m.media-amazon.com/images/I/0063005409.jpg"
    assert app.get(sense["image"]).body == COVER
    assert (order["percent_heard"], order["status"], order["image"]) == (12.5, "in_progress", None)
    # the books are shared, with their Audible versions; the user heard both
    books = {b["name"]: b for b in app.get("/api/audio-books").json}
    assert (books["Political Order"]["series"], books["Political Order"]["series_sequence"], books["Political Order"]["versions"][0]["name"]) == (
        "Political Order", "2", "Audible")
    assert sorted(b["name"] for b in app.get("/api/audio-books-heard").json) == ["Making Sense", "Political Order"]
    # again: nothing added, nothing changed (Audible still gives Political Order no cover)
    assert run(app)["counts"] == {}
    # its cover, which Audible's image server did not give when it was added, is asked for again, and given now
    monkeypatch.setattr(audible, "fetch_cover", lambda url: COVER + url.encode())
    assert run(app)["counts"] == {"covers added": 1, "audio books given Audible's details": 1}
    order = next(b for b in app.get("/api/audio-book-listens").json if b["asin"] == "B07D23CFGR")
    assert app.get(order["image"]).body.startswith(COVER)
    assert run(app)["counts"] == {}
    # heard further since, and rated here: Audible's details change, the rating stays
    mine = next(b for b in app.get("/api/audio-books-heard").json if b["name"] == "Political Order")
    app.put_json(f"/api/audio-books-heard/{mine['id']}", {"book_id": mine["book"]["id"], "rating": 8, "review": "Good"})
    fake.books[1]["percent_complete"] = 40.0
    assert run(app)["counts"] == {"audio books given Audible's details": 1}
    order = next(b for b in app.get("/api/audio-book-listens").json if b["asin"] == "B07D23CFGR")
    mine = next(b for b in app.get("/api/audio-books-heard").json if b["name"] == "Political Order")
    assert (order["percent_heard"], mine["rating"]) == (40.0, 8)
    # another account with the same books: no new book, listens of its own
    sign_in(app, sub="another")
    connect(app)
    assert run(app)["counts"] == {}
    assert len(app.get("/api/audio-book-listens").json) == 2
    with Session(engine) as session:
        assert len(session.scalars(select(AudioBook)).all()) == 2
        assert len(session.scalars(select(AudioBookListen)).all()) == 4
        assert len(session.scalars(select(Image)).all()) == 2


def test_the_library_is_read_a_page_at_a_time(app: webtest.TestApp, fake: FakeAudible, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audible, "PAGE", 1)
    sign_in(app)
    connect(app)
    assert run(app)["counts"]["audio books added"] == 2
    del fake


def test_disconnecting_deregisters_the_device_and_forgets_it(app: webtest.TestApp, engine: Engine, fake: FakeAudible) -> None:
    sign_in(app)
    connect(app)
    app.post("/audible/disconnect", status=204)
    assert fake.deregistered == [REFRESH]
    assert app.get("/audible/status").json["connected"] is False
    with Session(engine) as session:
        assert session.scalars(select(AudibleConnection)).all() == []


def test_connecting_again_deregisters_the_device_before(app: webtest.TestApp, engine: Engine, fake: FakeAudible) -> None:
    sign_in(app)
    connect(app)
    connect(app)
    assert fake.deregistered == [REFRESH]
    with Session(engine) as session:
        assert len(session.scalars(select(AudibleConnection)).all()) == 1


def test_a_request_is_signed_with_the_devices_key() -> None:
    moment = datetime.datetime(2026, 11, 21, 10, 0, 0, tzinfo=datetime.UTC)
    headers = audible.signed_headers("GET", "/1.0/library?page=1", "", ADP_TOKEN, PRIVATE_KEY, moment)
    signature, said = headers["x-adp-signature"].split(":", 1)
    assert said == "2026-11-21T10:00:00.000000Z"
    KEY.public_key().verify(base64.b64decode(signature), f"GET\n/1.0/library?page=1\n{said}\n\n{ADP_TOKEN}".encode(), padding.PKCS1v15(), hashes.SHA256())
    # a key given without its PEM lines is read too
    bare = "".join(PRIVATE_KEY.strip().splitlines()[1:-1])
    assert audible.signed_headers("GET", "/x", "", ADP_TOKEN, bare, moment)["x-adp-token"] == ADP_TOKEN
    with pytest.raises(audible.AudibleError, match="connect Audible again"):
        audible.signed_headers("GET", "/x", "", ADP_TOKEN, "not a key", moment)
