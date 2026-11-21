"""
Checks of the podcasts and the episodes of them heard.
"""

from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    dated,
    problem,
    rows,
    twice,
)
from myworld.models import Podcast, PodcastEpisode


@check("podcast-covers", "Every podcast has a cover", "podcasts", "podcasts")
def check_podcast_covers(session: Session) -> Result:
    """ Every podcast, of every account, has a cover image. """
    podcasts = rows(session, Podcast)
    return Result(checked=len(podcasts), problems=[problem(p, "has no cover") for p in podcasts if p.image_id is None])


@check("podcast-reviews", "Every podcast is rated and reviewed", "podcasts", "podcasts")
def check_podcast_reviews(session: Session) -> Result:
    """ Every podcast, of every account, has the user's own rating and review. """
    podcasts = rows(session, Podcast)
    problems = []
    for podcast in podcasts:
        missing = [what for what, absent in (("rating", podcast.rating is None), ("review", not podcast.review.strip())) if absent]
        if missing:
            problems.append(problem(podcast, f"has no {' and no '.join(missing)}"))
    return Result(checked=len(podcasts), problems=problems)


@check("podcast-episodes-heard", "Every podcast has an episode heard", "podcasts", "podcasts")
def check_podcast_episodes_heard(session: Session) -> Result:
    """ Every podcast, of every account, has at least one episode heard: one without is a podcast only meant to be heard. """
    podcasts = rows(session, Podcast)
    return Result(checked=len(podcasts), problems=[problem(p, "has no episode heard") for p in podcasts if not p.episodes])


@check("podcast-episode-dates", "Every podcast episode says when it was heard", "podcast episodes", "podcast-episodes")
def check_podcast_episode_dates(session: Session) -> Result:
    """ Every podcast episode, of every account, has the date it was heard. """
    episodes = rows(session, PodcastEpisode)
    return Result(checked=len(episodes), problems=[problem(e, "has no date") for e in episodes if not dated(e)])


@check("podcast-episode-duplicates", "No podcast episode is listed twice", "podcast episodes", "podcast-episodes")
def check_podcast_episode_duplicates(session: Session) -> Result:
    """ No podcast has two episodes of the same title (ignoring case and spaces at the ends). """
    episodes = rows(session, PodcastEpisode)
    return Result(checked=len(episodes), problems=twice(episodes, lambda e: (e.podcast_id, e.name.strip().lower()), "title", "podcast episode"))
