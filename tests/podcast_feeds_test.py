"""
The podcast feeds importer, an admin's, into the shared data (myworld.podcasts,
myworld.importers.podcast_feeds), against feeds that are faked: what a feed
says, every episode brought once, what is empty filled, the cover; and each
user's Next podcast episodes (myworld.importers.podcast_next): the next
episodes after the last one heard, as heard now.
"""

import datetime as dt
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from myworld import podcasts
from myworld.importers import core, jobs
from myworld.models import EpisodeHeard, Image, Podcast, PodcastEpisode
from myworld.timeutil import naive_utc
from tests.conftest import sign_in, sign_in_admin

if TYPE_CHECKING:
    import webtest
    from sqlalchemy.engine import Engine

FEED_URL = "https://feeds.example.com/history"
COVER_URL = "https://img.example.com/cover.jpg"
COVER = b"\xff\xd8\xffcover"


def item(n: int, **more: str) -> str:
    """ An episode of the feed: n-th, published on the n-th of March 2020. """
    fields = {
        "title": f"{n}. Episode {n}", "description": f"About {n}", "pubDate": f"Sun, {n:02d} Mar 2020 10:00:00 +0200", "guid": f"g{n}", "itunes:episode": str(n), "itunes:duration": "1:02:03",
        "itunes:episodeType": "full", "itunes:explicit": "no", "itunes:author": "Goalhanger", **more,
    }
    inner = "".join(f"<{tag}>{value}</{tag}>" for tag, value in fields.items() if value)
    return f'<item>{inner}<enclosure url="https://audio.example.com/{n}.mp3" type="audio/mpeg"/><itunes:image href="https://img.example.com/{n}.jpg"/></item>'


def feed(*numbers: int) -> bytes:
    """ A feed of the episodes numbered, newest first as feeds list them. """
    items = "".join(item(n) for n in sorted(numbers, reverse=True))
    return (
        '<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>'
        f'<title>History</title><link>https://history.example.com</link><itunes:image href="{COVER_URL}"/>{items}</channel></rss>'
    ).encode()


class FakeWeb:
    def __init__(self) -> None:
        self.feeds = {FEED_URL: feed(1, 2, 3, 4, 5)}

    def fetch_feed(self, url: str) -> bytes:
        if url not in self.feeds:
            raise podcasts.FeedError(f"{url} answered 404: Not Found")
        return self.feeds[url]

    @staticmethod
    def fetch_cover(url: str) -> tuple[bytes, str] | None:
        return (COVER, "image/jpeg") if url == COVER_URL else None


@pytest.fixture(autouse=True)
def fixture_inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ A run's job is done right away, inside the request that starts it. """
    def dispatcher(engine: Engine) -> Any:
        def dispatch(run_id: int) -> str:
            core.execute(engine, run_id)
            return f"projects/p/locations/r/jobs/myworld-import/executions/run-{run_id}"
        return dispatch
    monkeypatch.setattr(jobs, "dispatcher", dispatcher)


@pytest.fixture(name="web")
def fixture_web(monkeypatch: pytest.MonkeyPatch) -> FakeWeb:
    web = FakeWeb()
    monkeypatch.setattr(podcasts, "fetch_feed", web.fetch_feed)
    monkeypatch.setattr(podcasts, "fetch_cover", web.fetch_cover)
    return web


def run(app: webtest.TestApp, importer: str, params: dict[str, list[str]], *, dry_run: bool = False) -> Any:
    record = app.post_json(f"/api/importers/{importer}/runs", {"params": params, "dry_run": dry_run}, status=202).json
    assert record["status"] == "done", record["log"]
    return record


def feeds(app: webtest.TestApp, chosen: list[str] | None = None, *, dry_run: bool = False) -> Any:
    return run(app, "podcast-feeds", {"podcasts": chosen or []}, dry_run=dry_run)


def next_heard(app: webtest.TestApp, podcast: int, count: str) -> Any:
    return run(app, "podcast-next", {"podcasts": [str(podcast)], "next": [count]})


def episodes(engine: Engine) -> list[PodcastEpisode]:
    with Session(engine) as session:
        return list(session.scalars(select(PodcastEpisode).order_by(PodcastEpisode.published_utcz)))


def heard(engine: Engine) -> list[EpisodeHeard]:
    with Session(engine) as session:
        return list(session.scalars(select(EpisodeHeard).options(selectinload(EpisodeHeard.episode)).order_by(EpisodeHeard.id)))


def history(app: webtest.TestApp, engine: Engine) -> int:
    """ The shared podcast History with its feed, added by an admin, who stays signed in. """
    sign_in_admin(app, engine)
    return int(app.post_json("/api/podcasts", {"name": "History", "rss_feed": FEED_URL}, status=201).json["id"])


def test_what_a_feed_says() -> None:
    said = podcasts.parse_feed(feed(2, 1))
    assert (said.link, said.image_url) == ("https://history.example.com", COVER_URL)
    first = said.episodes[0]
    assert [e.guid for e in said.episodes] == ["g1", "g2"]
    assert first == podcasts.Episode(
        name="1. Episode 1", description="About 1", published_utcz=naive_utc(2020, 3, 1, 8), number=1, duration=3723,
        episode_type="full", explicit="no", enclosure_url="https://audio.example.com/1.mp3", image_url="https://img.example.com/1.jpg",
        author="Goalhanger", guid="g1",
    )
    for wrong in (b"not xml", b"<feed/>"):
        with pytest.raises(podcasts.FeedError):
            podcasts.parse_feed(wrong)
    # a description in HTML is kept as its text
    assert podcasts.plain('<div class="x"><p>How did <b>certain</b> people &amp; ideas</p><p>come?</p></div>') == "How did certain people & ideas come?"
    assert podcasts.plain("  Plain\n text ") == "Plain text"
    html = feed(1).replace(b"<description>About 1</description>", b"<description><![CDATA[<p>About <i>1</i></p>]]></description>")
    assert podcasts.parse_feed(html).episodes[0].description == "About 1"
    assert [podcasts.duration_seconds(v) for v in ("286", "32:55", "1:02:03.5", "", "x", "1:2:3:4")] == [286, 1975, 3723, None, None, None]


def test_only_http_is_read() -> None:
    for url in ("file:///etc/passwd", "ftp://example.com/feed", "feed"):
        with pytest.raises(podcasts.FeedError, match="not an http or https address"):
            podcasts.fetch_feed(url)


def importer(app: webtest.TestApp, name: str) -> dict[str, Any] | None:
    return next((i for i in app.get("/api/importers").json["importers"] if i["name"] == name), None)


@pytest.mark.usefixtures("web")
def test_the_feeds_are_an_admins_and_the_next_episodes_everyones(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app, sub="someone")
    # the feeds write the shared data: only admins see that importer
    assert importer(app, "podcast-feeds") is None
    app.post_json("/api/importers/podcast-feeds/runs", {"params": {}}, status=404)
    nothing = importer(app, "podcast-next")
    assert nothing is not None
    assert nothing["unavailable"] == "No podcast has episodes yet: an admin brings them from the feeds (Podcast feeds)"
    history(app, engine)
    app.post_json("/api/podcasts", {"name": "No feed"}, status=201)
    feeds_importer = importer(app, "podcast-feeds")
    assert feeds_importer is not None
    assert (feeds_importer["shared"], feeds_importer["unavailable"]) == (True, "")
    assert [c["label"] for c in feeds_importer["params"][0]["choices"]] == ["History"]
    feeds(app)
    sign_in(app, sub="someone")
    next_importer = importer(app, "podcast-next")
    assert next_importer is not None
    assert next_importer["unavailable"] == ""
    assert next_importer["dataset"] == "episodes-heard"
    assert [c["label"] for c in next_importer["params"][0]["choices"]] == ["History"]
    assert next_importer["params"][1]["single"] is True


def test_a_feed_brings_every_episode_and_fills_what_is_empty(app: webtest.TestApp, engine: Engine, web: FakeWeb) -> None:
    podcast = history(app, engine)
    # one typed in by an admin before, with a title of their own
    app.post_json("/api/podcast-episodes", {"podcast_id": podcast, "name": "My own name", "guid": "g1"}, status=201)
    record = feeds(app)
    assert record["counts"] == {"podcast episodes added": 4, "episodes given the feed's details": 1, "covers added": 1, "podcasts given their page": 1}
    first, *_ = episodes(engine)
    # what was typed is kept; what was empty is the feed's
    assert (first.name, first.description, first.duration, first.published_utcz) == ("My own name", "About 1", 3723, naive_utc(2020, 3, 1, 8))
    assert [e.guid for e in episodes(engine)] == ["g1", "g2", "g3", "g4", "g5"]
    with Session(engine) as session:
        shared = session.scalars(select(Podcast)).one()
        assert shared.url == "https://history.example.com"
        assert shared.image is not None
        assert (shared.image.data, shared.image.filename) == (COVER, f"podcast-feed-{shared.id}.jpg")
    # the cover is everyone's to see
    sign_in(app, sub="someone")
    assert app.get(app.get("/api/podcasts").json[0]["image"]).body == COVER
    sign_in_admin(app, engine)
    # a description cut short is given the feed's whole one; one written in its place is kept
    second, third = episodes(engine)[1:3]
    with Session(engine) as session:
        session.get_one(PodcastEpisode, second.id).description = "<p>Abo"
        session.get_one(PodcastEpisode, third.id).description = "Mine"
        session.commit()
    assert feeds(app)["counts"] == {"episodes given the feed's details": 1}
    assert [e.description for e in episodes(engine)[1:3]] == ["About 2", "Mine"]
    # again: nothing left to do; and a new episode in the feed is added, keeping every id
    assert feeds(app)["counts"] == {}
    ids = [e.id for e in episodes(engine)]
    web.feeds[FEED_URL] = feed(1, 2, 3, 4, 5, 6)
    assert feeds(app)["counts"] == {"podcast episodes added": 1}
    assert [e.id for e in episodes(engine)][:5] == ids


@pytest.mark.usefixtures("web")
def test_the_next_episodes_are_added_as_heard_now(app: webtest.TestApp, engine: Engine) -> None:
    podcast = history(app, engine)
    feeds(app)
    sign_in(app, sub="someone")
    # heard where and on what the last one was
    device = app.post_json("/api/devices", {"name": "Samsung S25"}, status=201).json["id"]
    second = next(e for e in app.get("/api/podcast-episodes").json if e["guid"] == "g2")
    app.post_json("/api/episodes-heard", {"episode_id": second["id"], "date": "2026-03-02", "date_timezone": "Asia/Jerusalem",
                                          "listened_at": "Night Walks", "device_id": device}, status=201)
    before = dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0)
    assert next_heard(app, podcast, "2")["counts"] == {"episodes heard added": 2}
    added = heard(engine)[1:]
    assert [(e.episode.guid, e.listened_at, e.date_timezone, e.device_id) for e in added] == [
        ("g3", "Night Walks", "Asia/Jerusalem", device), ("g4", "Night Walks", "Asia/Jerusalem", device),
    ]
    assert all(e.date_utcz is not None and e.date_utcz >= before for e in added)
    # the next after those, as many as there are; then none
    assert next_heard(app, podcast, "10")["counts"] == {"episodes heard added": 1}
    record = next_heard(app, podcast, "10")
    assert record["counts"] == {}
    assert "none left after the last you heard" in record["log"]
    # the ones before the first heard are not added: g1 was skipped
    assert sorted(e.episode.guid or "" for e in heard(engine)) == ["g2", "g3", "g4", "g5"]
    assert [p["name"] for p in app.get("/api/podcasts-heard").json] == ["History"]


@pytest.mark.usefixtures("web")
def test_from_the_first_when_none_was_heard_and_each_their_own(app: webtest.TestApp, engine: Engine) -> None:
    podcast = history(app, engine)
    feeds(app)
    sign_in(app, sub="someone")
    next_heard(app, podcast, "1")
    sign_in(app, sub="another")
    next_heard(app, podcast, "2")
    someone, another = heard(engine)[0].owner_id, heard(engine)[1].owner_id
    assert [(e.owner_id, e.episode.guid) for e in heard(engine)] == [(someone, "g1"), (another, "g1"), (another, "g2")]
    # the episodes stay as the feed brought them, one each
    assert len(episodes(engine)) == 5


@pytest.mark.usefixtures("web")
def test_every_one_left(app: webtest.TestApp, engine: Engine) -> None:
    podcast = history(app, engine)
    feeds(app)
    sign_in(app, sub="someone")
    next_heard(app, podcast, "1")
    assert next_heard(app, podcast, "all")["counts"] == {"episodes heard added": 4}
    assert [e.episode.guid for e in heard(engine)] == ["g1", "g2", "g3", "g4", "g5"]
    assert next_heard(app, podcast, "all")["counts"] == {}


@pytest.mark.usefixtures("web")
def test_a_dry_run_keeps_nothing(app: webtest.TestApp, engine: Engine) -> None:
    history(app, engine)
    record = feeds(app, dry_run=True)
    assert record["counts"]["podcast episodes added"] == 5
    assert episodes(engine) == []
    with Session(engine) as session:
        assert session.scalars(select(Image)).first() is None


@pytest.mark.usefixtures("web")
def test_a_feed_that_cannot_be_read_is_skipped(app: webtest.TestApp, engine: Engine) -> None:
    good = history(app, engine)
    gone = app.post_json("/api/podcasts", {"name": "Gone", "rss_feed": "https://feeds.example.com/gone"}, status=201).json["id"]
    record = feeds(app)
    assert record["counts"] == {"feeds that could not be read": 1, "covers added": 1, "podcasts given their page": 1, "podcast episodes added": 5}
    assert "Gone: https://feeds.example.com/gone answered 404" in record["log"]
    # only the podcasts chosen
    assert feeds(app, chosen=[str(gone)])["counts"] == {"feeds that could not be read": 1}
    assert feeds(app, chosen=[str(good)])["counts"] == {}
