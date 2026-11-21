"""
The user's podcasts, from their RSS feeds: each podcast chosen (or every
one with a feed) has its feed read, and

- an episode the user has (found by its feed's guid) is given what the feed
  says of it where it says nothing yet: what they wrote or edited is kept;
- a podcast with no cover, or no page, is given the feed's;
- with "Episodes to add", the next so many episodes of the feed after the
  last one heard are added as heard now, where and on what device the last
  one was (what the old podcasts_add_chapters.py of veltzer.github.io did).

An episode is added once, so it runs again safely; one the feed no longer
has stays. A feed that cannot be read is said in the log and skipped.
"""

import dataclasses
import datetime
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from myworld import podcasts
from myworld.importers.core import Importer, Param, Report, register
from myworld.models import Image, Podcast, PodcastEpisode, User, utcnow
from myworld.pictures import IMAGE_EXTENSIONS

# "Episodes to add": how many may be chosen
NEXT_CHOICES = (1, 2, 3, 5, 10, 20)
# the feed's fields of an episode, filled where the episode has nothing yet
FEED_FIELDS = tuple(field.name for field in dataclasses.fields(podcasts.Episode) if field.name not in ("name", "guid"))
# what the columns take (models.PodcastEpisode); a feed may say more
LIMITS = {"name": 500, "episode_type": 20, "explicit": 10, "enclosure_url": 2000, "image_url": 2000, "author": 300, "guid": 500}


def _fitted(episode: podcasts.Episode) -> dict[str, Any]:
    """ The columns of episode, each cut to what its column takes. """
    values = dataclasses.asdict(episode)
    for field, limit in LIMITS.items():
        value = values[field]
        if isinstance(value, str):
            values[field] = value[:limit]
    return values


def _with_feeds(session: Session, owner: User) -> list[Podcast]:
    return list(session.scalars(select(Podcast).where(Podcast.owner_id == owner.id, Podcast.rss_feed != "").order_by(Podcast.name)))


def podcast_choices(session: Session, owner: User) -> list[tuple[str, str]]:
    return [(str(podcast.id), podcast.name) for podcast in _with_feeds(session, owner)]


def next_choices(_session: Session, _owner: User) -> list[tuple[str, str]]:
    return [(str(n), f"The next {n}" if n > 1 else "The next one") for n in NEXT_CHOICES]


def unavailable(session: Session, owner: User) -> str:
    return "" if _with_feeds(session, owner) else "Give a podcast its RSS feed first (Podcasts, Edit)"


def _cover(session: Session, owner: User, podcast: Podcast, url: str) -> bool:
    """ Give podcast the feed's cover when it has none; whether it was given. """
    if podcast.image_id is not None or not url:
        return False
    fetched = podcasts.fetch_cover(url)
    if fetched is None:
        return False
    data, content_type = fetched
    filename = f"podcast-feed-{podcast.id}{IMAGE_EXTENSIONS[content_type]}"
    image = session.scalars(select(Image).where(Image.owner_id == owner.id, Image.filename == filename)).first()
    if image is None:
        image = Image(owner_id=owner.id, filename=filename, content_type=content_type, sha256=hashlib.sha256(data).hexdigest(), data=data)
        session.add(image)
    podcast.image = image
    return True


def _fill(episode: PodcastEpisode, said: podcasts.Episode) -> bool:
    """ Give episode what the feed says where it has nothing yet; whether anything was given. """
    values = _fitted(said)
    changed = False
    for field in FEED_FIELDS:
        if getattr(episode, field) in ("", None) and values[field] not in ("", None):
            setattr(episode, field, values[field])
            changed = True
    return changed


def _add_next(podcast: Podcast, feed: podcasts.Feed, count: int) -> list[PodcastEpisode]:
    """ The next count episodes of feed after the last of it heard, added as heard now. """
    heard = {episode.guid for episode in podcast.episodes if episode.guid}
    positions = [i for i, said in enumerate(feed.episodes) if said.guid in heard]
    following = feed.episodes[max(positions) + 1:] if positions else feed.episodes
    # heard where and on what the last one was
    last = max(podcast.episodes, key=lambda e: (e.date_utcz or datetime.datetime.min, e.id or 0), default=None)
    now = utcnow().replace(microsecond=0)
    added = []
    for said in following:
        if len(added) == count:
            break
        if said.guid is None or said.guid in heard:
            continue
        episode = PodcastEpisode(
            owner_id=podcast.owner_id,
            **_fitted(said),
            date_utcz=now,
            date_timezone=last.date_timezone if last else "",
            listened_at=last.listened_at if last else "",
            device_id=last.device_id if last else None,
        )
        podcast.episodes.append(episode)
        heard.add(said.guid)
        added.append(episode)
    return added


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    chosen = set(params.get("podcasts") or [])
    count = int(params["next"][0]) if params.get("next") else 0
    query = (select(Podcast).where(Podcast.owner_id == owner.id, Podcast.rss_feed != "")
             .options(selectinload(Podcast.episodes)).order_by(Podcast.name))
    for podcast in session.scalars(query):
        if chosen and str(podcast.id) not in chosen:
            continue
        try:
            feed = podcasts.parse_feed(podcasts.fetch_feed(podcast.rss_feed))
        except podcasts.FeedError as e:
            report.say(f"{podcast.name}: {e}")
            report.count("feeds that could not be read")
            continue
        report.say(f"{podcast.name}: the feed has {len(feed.episodes)} episodes")
        if not podcast.url and feed.link.startswith(("https://", "http://")):
            podcast.url = feed.link[:1000]
            report.count("podcasts given their page")
        if _cover(session, owner, podcast, feed.image_url):
            report.count("covers added")
        by_guid = {said.guid: said for said in feed.episodes if said.guid}
        for episode in podcast.episodes:
            said = by_guid.get(episode.guid) if episode.guid else None
            if said is not None and _fill(episode, said):
                report.count("episodes given the feed's details")
        for episode in _add_next(podcast, feed, count):
            report.say(f"  + {episode.name}")
            report.count("podcast episodes added")
    session.flush()


IMPORTER = register(Importer(
    name="podcast-feeds",
    title="Podcast feeds",
    description=(
        "Reads the RSS feeds of your podcasts (the ones chosen, or every one with a feed). Episodes you have get what "
        "the feed says of them where they have nothing yet, and a podcast with no cover or page gets the feed's. With "
        "Episodes to add, the next ones after the last you heard are added as heard now, where and on what device the "
        "last one was. Keeps your edits, adds an episode once: safe to run again."
    ),
    dataset="podcast-episodes",
    params=(
        Param(name="podcasts", title="Podcasts", kind="choices", choices=podcast_choices,
              description="The podcasts whose feeds are read; none chosen reads every one with a feed."),
        Param(name="next", title="Episodes to add", kind="choices", choices=next_choices, single=True,
              description="How many of the episodes after the last one you heard to add as heard now; none chosen adds none."),
    ),
    run=run,
    unavailable=unavailable,
))
