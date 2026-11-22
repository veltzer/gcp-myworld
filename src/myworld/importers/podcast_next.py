"""
The next episodes of a podcast, as heard: of each podcast chosen, the next
so many (or every one left) of its episodes (shared, as the Podcast feeds importer brought them
from its feed, oldest first) after the last one the user heard, or from its
first when they heard none, are added to their Episodes heard as heard now,
where, in what time zone and on what device the last one heard was (what
veltzer.github.io's podcasts_add_chapters.py did). The podcast goes in their
Podcasts heard when it is not there yet.

An episode is heard once, so it runs again safely: each run adds the next
ones. It reads no feed: an episode the shared data does not have yet is
brought by an admin's Podcast feeds run.
"""

import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from myworld.importers.core import Importer, Param, Report, register
from myworld.models import (
    EpisodeHeard,
    Podcast,
    PodcastEpisode,
    PodcastHeard,
    User,
    utcnow,
)

# how many may be chosen; ALL is every one after the last heard
NEXT_CHOICES = (1, 2, 3, 5, 10, 20)
ALL = "all"


def _with_episodes(session: Session) -> list[Podcast]:
    return list(session.scalars(select(Podcast).where(Podcast.episodes.any()).order_by(Podcast.name)))


def podcast_choices(session: Session, _owner: User) -> list[tuple[str, str]]:
    return [(str(podcast.id), podcast.name) for podcast in _with_episodes(session)]


def count_choices(_session: Session, _owner: User) -> list[tuple[str, str]]:
    return [(str(n), f"The next {n}" if n > 1 else "The next one") for n in NEXT_CHOICES] + [(ALL, "Every one left")]


def unavailable(session: Session, _owner: User) -> str:
    return "" if _with_episodes(session) else "No podcast has episodes yet: an admin brings them from the feeds (Podcast feeds)"


def in_order(episodes: list[PodcastEpisode]) -> list[PodcastEpisode]:
    """ A podcast's episodes, the first published first (one with no date where it was added). """
    return sorted(episodes, key=lambda e: (e.published_utcz is None, e.published_utcz or datetime.datetime.min, e.id))


def add_next(session: Session, owner: User, podcast: Podcast, count: int | None) -> list[EpisodeHeard]:
    """ The next count episodes of podcast after the last of it owner heard (every one when count is None), added as heard now. """
    episodes = in_order(podcast.episodes)
    mine = {heard.episode_id: heard for e in episodes for heard in e.heard if heard.owner_id == owner.id}
    positions = [i for i, e in enumerate(episodes) if e.id in mine]
    following = episodes[max(positions) + 1:] if positions else episodes
    # heard where and on what the last one heard was
    last = max(mine.values(), key=lambda h: (h.date_utcz or datetime.datetime.min, h.id), default=None)
    now = utcnow().replace(microsecond=0)
    added = []
    for episode in following[:count]:
        heard = EpisodeHeard(
            owner_id=owner.id, episode=episode, date_utcz=now,
            date_timezone=last.date_timezone if last else "",
            listened_at=last.listened_at if last else "",
            device_id=last.device_id if last else None,
        )
        session.add(heard)
        added.append(heard)
    if added and not any(row.owner_id == owner.id for row in podcast.heard):
        session.add(PodcastHeard(owner_id=owner.id, podcast=podcast))
    return added


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    chosen = set(params["podcasts"])
    chosen_count = params["next"][0]
    count = None if chosen_count == ALL else int(chosen_count)
    query = (select(Podcast).where(Podcast.id.in_([int(c) for c in chosen]))
             .options(selectinload(Podcast.heard), selectinload(Podcast.episodes).selectinload(PodcastEpisode.heard)).order_by(Podcast.name))
    for podcast in session.scalars(query):
        added = add_next(session, owner, podcast, count)
        report.say(f"{podcast.name}: {len(added)} episodes heard" + ("" if added else " (none left after the last you heard)"))
        for heard in added:
            report.say(f"  + {heard.episode.name}")
        if added:
            report.count("episodes heard added", len(added))
    session.flush()


IMPORTER = register(Importer(
    name="podcast-next",
    title="Next podcast episodes",
    description=(
        "Adds the next episodes of the podcasts chosen (so many, or every one left), after the last one you heard of each (or from the first), to your "
        "Episodes heard, as heard now, where and on what device the last one was. Adds an episode once: each run adds the next ones."
    ),
    dataset="episodes-heard",
    params=(
        Param(name="podcasts", title="Podcasts", kind="choices", choices=podcast_choices, required=True,
              description="The podcasts to add the next episodes of."),
        Param(name="next", title="Episodes to add", kind="choices", choices=count_choices, required=True, single=True,
              description="How many of the episodes after the last one you heard to add, of each podcast: Every one left adds them all, up to the newest."),
    ),
    run=run,
    unavailable=unavailable,
))
