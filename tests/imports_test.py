"""
The importers (myworld.importers), the Imports page's API (myworld.imports)
and the YouTube connection they read through (myworld.youtube), against a
YouTube that is faked: connecting, importing playlists, and that a second
run adds nothing and changes nothing.
"""

import datetime
import urllib.parse
from typing import Any

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import importers, youtube
from myworld.importers import core
from myworld.models import ImportRun, User, YouTubeConnection, YouTubeVideo
from tests.conftest import sign_in

REFRESH = "refresh-token-of-alice"


class FakeYouTube:
    """ Google's token endpoint and the YouTube Data API, with a channel, two playlists and a liked list. """

    def __init__(self) -> None:
        self.playlists: dict[str, tuple[str, list[str]]] = {
            "LLalice": ("", ["vidLiked001"]),
            "PLmusic": ("Music", ["vidMusic001", "vidMusic002", "vidGone0001"]),
            "PLtalks": ("Talks", ["vidMusic001", "vidTalks001"]),
        }
        self.videos: dict[str, dict[str, Any]] = {
            "vidLiked001": self.video("Liked one", "Some Channel", "10", "PT3M", "2020-01-02T03:04:05Z", "100"),
            "vidMusic001": self.video("Song", "Band", "10", "PT1H2M3S", "2019-05-06T00:00:00Z", "5000"),
            "vidMusic002": self.video("Song two", "Band", "10", "PT4M1S", "2019-05-07T00:00:00Z", "6000"),
            "vidTalks001": self.video("A talk", "Talks", "27", "PT45M", "2021-07-08T00:00:00Z", "77"),
        }
        self.revoked: list[str] = []
        self.calls: list[str] = []

    @staticmethod
    def video(title: str, channel: str, category: str, duration: str, published: str, views: str) -> dict[str, Any]:
        return {
            "snippet": {"title": title, "channelTitle": channel, "categoryId": category, "publishedAt": published},
            "contentDetails": {"duration": duration},
            "statistics": {"viewCount": views},
        }

    def token_post(self, data: dict[str, str]) -> dict[str, Any]:
        assert data["client_secret"] == "test-client-secret"
        if data["grant_type"] == "authorization_code":
            assert data["code"] == "good-code"
            return {"access_token": "access", "refresh_token": REFRESH, "scope": f"openid {youtube.SCOPE}"}
        if data["refresh_token"] != REFRESH:
            raise youtube.YouTubeError("Google no longer accepts the YouTube connection")
        return {"access_token": "access"}

    def api_get(self, access_token: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        assert access_token == "access"
        self.calls.append(path)
        if path == "channels":
            return {"items": [{"snippet": {"title": "Alice's channel"}, "contentDetails": {"relatedPlaylists": {"likes": "LLalice"}}}]}
        if path == "playlists":
            # a page at a time, as YouTube does
            mine = [{"id": pid, "snippet": {"title": title}} for pid, (title, _) in self.playlists.items() if title]
            if params.get("pageToken") == "2":
                return {"items": mine[1:]}
            return {"items": mine[:1], "nextPageToken": "2"}
        if path == "playlistItems":
            ids = self.playlists[params["playlistId"]][1]
            return {"items": [{"contentDetails": {"videoId": vid}} for vid in ids]}
        if path == "videos":
            return {"items": [{"id": vid, **self.videos[vid]} for vid in params["id"].split(",") if vid in self.videos]}
        if path == "videoCategories":
            names = {"10": "Music", "27": "Education"}
            return {"items": [{"id": c, "snippet": {"title": names[c]}} for c in params["id"].split(",")]}
        raise AssertionError(path)

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


@pytest.fixture(name="fake")
def fixture_fake(monkeypatch: pytest.MonkeyPatch) -> FakeYouTube:
    fake = FakeYouTube()
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(youtube, "token_post", fake.token_post)
    monkeypatch.setattr(youtube, "api_get", fake.api_get)
    monkeypatch.setattr(youtube, "revoke", fake.revoke)
    return fake


def location(response: webtest.TestResponse) -> str:
    """ Where a redirect sends the browser. """
    assert isinstance(response.location, str)
    return response.location


def query_of(response: webtest.TestResponse) -> dict[str, list[str]]:
    """ The query of where a redirect sends the browser. """
    return urllib.parse.parse_qs(urllib.parse.urlsplit(location(response)).query)


def connect(app: webtest.TestApp) -> None:
    """ Go through /youtube/connect and Google's consent screen, saying yes. """
    response = app.get("/youtube/connect")
    assert response.status_int == 302
    query = query_of(response)
    assert query["scope"] == [youtube.SCOPE]
    assert query["access_type"] == ["offline"]
    back = app.get("/youtube/callback", {"state": query["state"][0], "code": "good-code"})
    assert back.status_int == 302
    assert location(back).endswith("/library#imports")


def alice(engine: Engine) -> User:
    with Session(engine) as session:
        return session.scalars(select(User).where(User.email == "alice@example.com")).one()


def videos(engine: Engine) -> dict[str, YouTubeVideo]:
    with Session(engine) as session:
        return {v.youtube_id: v for v in session.scalars(select(YouTubeVideo))}


def run(app: webtest.TestApp, playlists: list[str], dry_run: bool = False, status: int = 200) -> Any:
    return app.post_json("/api/importers/youtube-playlists/runs", {"params": {"playlists": playlists}, "dry_run": dry_run}, status=status).json


# ─── connecting ─────────────────────────────────────────────────────────────

def test_connecting_keeps_the_refresh_token_sealed(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    assert app.get("/youtube/status").json["connected"] is False
    connect(app)
    status = app.get("/youtube/status").json
    assert (status["configured"], status["connected"], status["channel"]) == (True, True, "Alice's channel")
    with Session(engine) as session:
        kept = session.get(YouTubeConnection, alice(engine).id)
        assert kept is not None
        # not as it was given: sealed with a key from SECRET_KEY
        assert REFRESH not in kept.refresh_token
        sealed = kept.refresh_token
    # the app's SECRET_KEY is the environment's (conftest)
    assert youtube.unseal(sealed) == REFRESH
    # disconnecting revokes it at Google and forgets it (and again is fine)
    app.post("/youtube/disconnect", status=204)
    app.post("/youtube/disconnect", status=204)
    assert fake.revoked == [REFRESH]
    assert app.get("/youtube/status").json["connected"] is False


def test_a_callback_with_a_wrong_state_is_refused(app: webtest.TestApp, fake: FakeYouTube) -> None:
    sign_in(app)
    app.get("/youtube/connect")
    app.get("/youtube/callback", {"state": "forged", "code": "good-code"}, status=400)
    assert app.get("/youtube/status").json["connected"] is False
    assert fake.calls == []


def test_saying_no_on_the_consent_screen(app: webtest.TestApp, fake: FakeYouTube) -> None:
    sign_in(app)
    query = query_of(app.get("/youtube/connect"))
    back = app.get("/youtube/callback", {"state": query["state"][0], "error": "access_denied"})
    assert "youtube_error=Connecting+YouTube+was+cancelled" in location(back)
    assert app.get("/youtube/status").json["connected"] is False
    assert fake.calls == []


def test_without_a_client_secret_youtube_cannot_be_connected(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    sign_in(app)
    app.get("/youtube/connect", status=404)
    listing = app.get("/api/importers").json
    assert listing["youtube"]["configured"] is False
    importer = next(i for i in listing["importers"] if i["name"] == "youtube-playlists")
    assert importer["unavailable"] == "Connecting YouTube is not set up on this site"
    assert importer["params"][0]["choices"] == []
    assert "not set up" in run(app, ["PLmusic"], status=400)["error"]


def test_the_imports_api_needs_a_sign_in(app: webtest.TestApp) -> None:
    app.get("/api/importers", status=401)
    app.get("/api/import-runs", status=401)
    app.post_json("/api/importers/youtube-playlists/runs", {}, status=401)
    app.get("/youtube/connect", status=401)


# ─── the importer ───────────────────────────────────────────────────────────

def test_the_playlists_to_choose_from(app: webtest.TestApp, fake: FakeYouTube) -> None:
    sign_in(app)
    importer = next(i for i in app.get("/api/importers").json["importers"] if i["name"] == "youtube-playlists")
    # not connected: nothing to choose from, and it says why
    assert importer["unavailable"] == "Connect YouTube first"
    assert run(app, ["PLmusic"], status=400)["error"] == "Connect YouTube first"
    connect(app)
    importer = next(i for i in app.get("/api/importers").json["importers"] if i["name"] == "youtube-playlists")
    assert importer["unavailable"] == ""
    # the liked videos first, then every playlist (all the pages of them) by title
    assert importer["params"][0]["choices"] == [
        {"value": "LLalice", "label": "Liked videos"},
        {"value": "PLmusic", "label": "Music"},
        {"value": "PLtalks", "label": "Talks"},
    ]


def test_importing_playlists_adds_each_video_once_and_again_adds_nothing(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    done = run(app, ["PLmusic", "PLtalks"])
    assert done["status"] == "done"
    assert done["counts"] == {"YouTube videos added": 4, "of them YouTube no longer has": 1}
    assert done["log"] == "Music: 3 videos\nTalks: 2 videos"
    have = videos(engine)
    assert sorted(have) == ["vidGone0001", "vidMusic001", "vidMusic002", "vidTalks001"]
    song = have["vidMusic001"]
    assert (song.name, song.channel, song.category, song.duration, song.uploaded, song.views, song.unavailable) == (
        "Song", "Band", "Music", 3723, datetime.date(2019, 5, 6), 5000, False,
    )
    # a playlist does not say when it was watched
    assert song.date_utcz is None and song.date_ymd is None
    gone = have["vidGone0001"]
    assert (gone.name, gone.channel, gone.unavailable) == ("", "", True)
    # again: nothing added, nothing changed
    again = run(app, ["PLmusic", "PLtalks"])
    assert again["counts"] == {"YouTube videos unchanged": 4}
    assert len(videos(engine)) == 4


def test_a_video_the_user_has_keeps_what_they_wrote(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    with Session(engine) as session:
        session.add(YouTubeVideo(
            owner_id=alice(engine).id, youtube_id="vidMusic001", name="My name for it", rating=9, review="Great",
            watched_at="Home", date_ymd=datetime.date(2022, 1, 1), channel="Old", views=1,
        ))
        session.commit()
    done = run(app, ["PLmusic"])
    assert done["counts"] == {"YouTube videos added": 2, "YouTube videos given YouTube's details": 1, "of them YouTube no longer has": 1}
    song = videos(engine)["vidMusic001"]
    # YouTube's details are YouTube's as they are now; the rest is the user's
    assert (song.channel, song.views, song.duration) == ("Band", 5000, 3723)
    assert (song.name, song.rating, song.review, song.watched_at, song.date_ymd) == ("My name for it", 9, "Great", "Home", datetime.date(2022, 1, 1))
    # one YouTube took down since keeps what was known of it, and says it is gone
    del fake.videos["vidMusic001"]
    assert run(app, ["PLmusic"])["counts"] == {"YouTube videos given YouTube's details": 1, "YouTube videos unchanged": 2}
    song = videos(engine)["vidMusic001"]
    assert (song.channel, song.unavailable, song.rating) == ("Band", True, 9)


def test_it_only_ever_adds(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    run(app, ["PLtalks"])
    # taken out of the playlist on YouTube: it stays
    fake.playlists["PLtalks"] = ("Talks", ["vidTalks001"])
    assert run(app, ["PLtalks"])["counts"] == {"YouTube videos unchanged": 1}
    assert sorted(videos(engine)) == ["vidMusic001", "vidTalks001"]


def test_a_dry_run_keeps_nothing_but_says_what_a_run_would_do(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    dry = run(app, ["LLalice"], dry_run=True)
    assert (dry["status"], dry["dry_run"], dry["counts"]) == ("done", True, {"YouTube videos added": 1})
    assert videos(engine) == {}
    runs = app.get("/api/import-runs").json
    assert [(r["importer"], r["dry_run"], r["params"]) for r in runs] == [("youtube-playlists", True, {"playlists": ["LLalice"]})]


def test_wrong_parameters_run_nothing(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    assert run(app, [], status=400)["error"] == "Playlists: choose at least one"
    assert "not one of the choices: PLsomeone" in run(app, ["PLsomeone"], status=400)["error"]
    error = app.post_json("/api/importers/youtube-playlists/runs", {"params": {"colour": "red"}}, status=400).json["error"]
    assert error == "youtube-playlists takes no parameter colour"
    app.post_json("/api/importers/youtube-playlists/runs", {"params": {}, "dry_run": "yes"}, status=400)
    app.post_json("/api/importers/unicorns/runs", {"params": {}}, status=404)
    with Session(engine) as session:
        assert session.scalars(select(ImportRun)).all() == []


def test_a_connection_google_no_longer_accepts_fails_the_run(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    with Session(engine) as session:
        kept = session.get(YouTubeConnection, alice(engine).id)
        assert kept is not None
        kept.refresh_token = youtube.seal("revoked-token")
        session.commit()
    # the playlists cannot be read to check the choice against: it says why
    assert "no longer accepts" in run(app, ["PLmusic"], status=409)["error"]
    listing = app.get("/api/importers").json["importers"][0]
    assert "no longer accepts" in listing["params"][0]["error"]


def test_a_failing_import_is_rolled_back_and_kept_as_failed(app: webtest.TestApp, engine: Engine, fake: FakeYouTube, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app)
    connect(app)
    original = fake.api_get

    def failing(access_token: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        if path == "videos":
            raise youtube.YouTubeError("YouTube answered 403 to videos: quota exceeded")
        return original(access_token, path, params)

    monkeypatch.setattr(youtube, "api_get", failing)
    failed = run(app, ["PLmusic"])
    assert (failed["status"], failed["counts"]) == ("failed", {})
    assert failed["log"].endswith("Failed: YouTube answered 403 to videos: quota exceeded")
    assert videos(engine) == {}
    assert app.get("/api/import-runs").json[0]["status"] == "failed"


def test_each_user_imports_into_their_own_data(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    run(app, ["LLalice"])
    sign_in(app, "bob")
    assert app.get("/youtube/status").json["connected"] is False
    assert app.get("/api/import-runs").json == []
    assert run(app, ["LLalice"], status=400)["error"] == "Connect YouTube first"
    assert [v.owner_id for v in videos(engine).values()] == [alice(engine).id]


# ─── the parts ──────────────────────────────────────────────────────────────

def test_seconds() -> None:
    assert youtube.seconds("PT1H2M3S") == 3723
    assert youtube.seconds("PT45S") == 45
    assert youtube.seconds("P1DT1M") == 86460
    # a live stream has none
    assert youtube.seconds("P0D") is None
    assert youtube.seconds("") is None
    assert youtube.seconds("garbage") is None


def test_sealing_needs_the_same_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "one")
    sealed = youtube.seal("token")
    assert youtube.unseal(sealed) == "token"
    monkeypatch.setenv("SECRET_KEY", "another")
    with pytest.raises(youtube.YouTubeError, match="connect YouTube again"):
        youtube.unseal(sealed)


def test_an_importer_is_registered_once_with_parameters_there_are(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "IMPORTERS", dict(core.IMPORTERS))

    def nothing(_session: Session, _owner: User, _params: dict[str, Any], _report: core.Report) -> None:
        return None

    def made(name: str, *params: core.Param) -> core.Importer:
        return core.Importer(name=name, title="T", description="D", dataset="youtube", params=params, run=nothing)

    with pytest.raises(ValueError, match="registered twice"):
        core.register(made("youtube-playlists"))
    with pytest.raises(ValueError, match="of no kind there is"):
        core.register(made("odd", core.Param(name="p", title="P", kind="colour")))
    with pytest.raises(ValueError, match="nothing to choose from"):
        core.register(made("odd", core.Param(name="p", title="P", kind="choices")))
    assert core.register(made("fine")) is core.IMPORTERS["fine"]


def test_every_importer_adds_to_a_page_there_is() -> None:
    from myworld.checks import DATASETS
    assert importers.IMPORTERS
    for importer in importers.IMPORTERS.values():
        assert importer.dataset in DATASETS, importer.name
        assert importer.title and importer.description


def test_the_privacy_page_says_what_youtube_access_is_for(app: webtest.TestApp) -> None:
    """ The OAuth consent screen links to it: it is open to anyone, signed in or not, and the landing page links to it. """
    page = app.get("/privacy")
    assert page.status_int == 200
    assert "youtube.readonly" in page.text and "Limited Use" in page.text
    assert 'href="/privacy"' in app.get("/").text


def test_the_playlists_of_the_last_run_are_picked_to_start_with(app: webtest.TestApp, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)

    def chosen() -> list[str]:
        return app.get("/api/importers").json["importers"][0]["params"][0]["chosen"]

    assert chosen() == []
    # any number of them, dry run or not, in the order picked
    run(app, ["PLtalks", "LLalice", "PLmusic"], dry_run=True)
    assert chosen() == ["PLtalks", "LLalice", "PLmusic"]
    run(app, ["PLmusic", "PLtalks"])
    assert chosen() == ["PLmusic", "PLtalks"]
    # a run refused for its parameters is no run, and changes nothing
    run(app, ["PLsomeone"], status=400)
    assert chosen() == ["PLmusic", "PLtalks"]
    # one deleted on YouTube since is no longer picked
    del fake.playlists["PLmusic"]
    assert chosen() == ["PLtalks"]
    # each user's own
    sign_in(app, "bob")
    assert chosen() == []


def test_youtube_details_fills_in_the_videos_that_have_none(app: webtest.TestApp, engine: Engine, fake: FakeYouTube) -> None:
    sign_in(app)
    connect(app)
    owner = alice(engine).id
    with Session(engine) as session:
        session.add_all([
            # came with a name only: gets YouTube's details, keeps the user's name and rating
            YouTubeVideo(owner_id=owner, youtube_id="vidMusic001", name="My name", rating=7, review="", watched_at=""),
            # had them already: not asked for
            YouTubeVideo(owner_id=owner, youtube_id="vidTalks001", name="A talk", review="", watched_at="", channel="Mine", duration=60),
            # YouTube has it no more: marked so, its name stays
            YouTubeVideo(owner_id=owner, youtube_id="vidGone0001", name="Gone", review="", watched_at=""),
        ])
        session.commit()

    def post(dry_run: bool) -> Any:
        return app.post_json("/api/importers/youtube-details/runs", {"params": {}, "dry_run": dry_run}).json

    assert post(True)["counts"] == {"YouTube videos given YouTube's details": 2}
    assert videos(engine)["vidMusic001"].duration is None
    done = post(False)
    assert done["status"] == "done"
    assert done["counts"] == {"YouTube videos given YouTube's details": 2}
    assert done["log"] == "2 videos without YouTube's details"
    have = videos(engine)
    assert (have["vidMusic001"].name, have["vidMusic001"].rating, have["vidMusic001"].channel, have["vidMusic001"].duration) == ("My name", 7, "Band", 3723)
    assert (have["vidTalks001"].channel, have["vidTalks001"].duration) == ("Mine", 60)
    assert (have["vidGone0001"].name, have["vidGone0001"].unavailable) == ("Gone", True)
    # again: only the gone one is asked about, and nothing changes
    assert post(False)["counts"] == {"YouTube videos unchanged": 1}
    assert len(videos(engine)) == 3
