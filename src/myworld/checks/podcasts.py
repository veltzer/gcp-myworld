"""
Checks of the podcasts and their episodes (shared), and of the podcasts
and episodes each account heard.
"""

from typing import TYPE_CHECKING

from sqlalchemy import select

from myworld.checks.core import (
    Result,
    check,
    dated,
    problem,
    rows,
)
from myworld.models import EpisodeHeard, Podcast, PodcastEpisode, PodcastHeard

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@check("podcast-covers", "Every podcast has a cover", "podcasts", "podcasts")
def check_podcast_covers(session: Session) -> Result:
    """ Every podcast has a cover image. """
    podcasts = rows(session, Podcast)
    return Result(checked=len(podcasts), problems=[problem(p, "has no cover") for p in podcasts if p.image_id is None])


@check("podcast-feeds", "Every podcast has its feed", "podcasts", "podcasts")
def check_podcast_feeds(session: Session) -> Result:
    """ Every podcast has the address of its RSS feed, which the Podcast feeds importer brings its episodes from. """
    podcasts = rows(session, Podcast)
    return Result(checked=len(podcasts), problems=[problem(p, "has no RSS feed") for p in podcasts if not p.rss_feed])


@check("podcast-episode-guids", "Every podcast episode is its feed's", "podcast episodes", "podcast-episodes")
def check_podcast_episode_guids(session: Session) -> Result:
    """ Every podcast episode has its id in the feed (guid): one typed in without it is not found in the feed again, and may be added from it twice. """
    episodes = rows(session, PodcastEpisode)
    return Result(checked=len(episodes), problems=[problem(e, "has no id in the feed") for e in episodes if not e.guid])


def _podcasts_heard(session: Session) -> list[PodcastHeard]:
    """ Every account's Your podcasts: the podcasts heard of which it heard an episode (the others are not listed). """
    with_episodes = {(owner, podcast) for owner, podcast in session.execute(select(EpisodeHeard.owner_id, PodcastEpisode.podcast_id).join(PodcastEpisode))}
    found = session.scalars(select(PodcastHeard).join(Podcast).order_by(PodcastHeard.owner_id, Podcast.name, PodcastHeard.id))
    return [row for row in found if (row.owner_id, row.podcast_id) in with_episodes]


def _episodes_heard(session: Session) -> list[EpisodeHeard]:
    return list(session.scalars(select(EpisodeHeard).join(PodcastEpisode).order_by(EpisodeHeard.owner_id, PodcastEpisode.name, EpisodeHeard.id)))


@check("podcast-reviews", "Every one of your podcasts is rated and reviewed", "podcasts", "podcasts-heard")
def check_podcast_reviews(session: Session) -> Result:
    """ Every podcast in Your podcasts, of every account, has the user's own rating and review. """
    heard = _podcasts_heard(session)
    problems = []
    for row in heard:
        missing = [what for what, absent in (("rating", row.rating is None), ("review", not row.review.strip())) if absent]
        if missing:
            problems.append(problem(row, f"has no {' and no '.join(missing)}"))
    return Result(checked=len(heard), problems=problems)


@check("episode-heard-dates", "Every episode heard says when", "episodes heard", "episodes-heard")
def check_episode_heard_dates(session: Session) -> Result:
    """ Every episode heard, of every account, has the date it was heard. """
    heard = _episodes_heard(session)
    return Result(checked=len(heard), problems=[problem(e, "has no date") for e in heard if not dated(e)])
