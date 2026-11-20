"""
What every importer is made of: its parameters, the report it writes, the
register it is in, and running one, which is the same for all of them.

An importer may be run again and again with nothing to fear: every row it
writes has a key it is told from the others by (a YouTube video by its id),
so a row the user has is never added twice; of a row they have it may
refresh only what the source says of it (the channel of a video, its
views), never what the user wrote (a rating, a review). So a second run
right after the first adds nothing and changes nothing.
"""

import dataclasses
from collections import Counter
from collections.abc import Callable
from typing import Any

import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from myworld.models import ImportRun, User, utcnow

# the kinds of parameter there are, as the Imports page draws them:
# "choices" is one or more of a list the importer gives for the user (a list of strings)
PARAM_KINDS = ("choices",)


class ImporterError(Exception):
    """ An import that cannot go on: it is rolled back, and the run says why. """


class ParamError(ImporterError):
    """ A parameter given wrong: nothing is run. """


@dataclasses.dataclass(frozen=True)
class Param:
    name: str
    title: str
    kind: str
    description: str = ""
    required: bool = False
    # for "choices": what may be chosen, for this user, as (value, label)
    choices: Callable[[Session, User], list[tuple[str, str]]] | None = None


class Report:
    """ What an import did: counts of what it did ("YouTube videos added": 3) and lines it said. """

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.lines: list[str] = []

    def count(self, what: str, n: int = 1) -> None:
        self.counts[what] += n

    def say(self, line: str) -> None:
        self.lines.append(line)


@dataclasses.dataclass(frozen=True)
class Importer:
    name: str
    title: str
    description: str
    # the data it adds to, a key of checks.DATASETS ("youtube")
    dataset: str
    params: tuple[Param, ...]
    # does the import into the session, without committing: run() commits or rolls back
    run: Callable[[Session, User, dict[str, Any], Report], None]
    # why the user cannot run it now ("connect YouTube first"), "" when they can
    unavailable: Callable[[Session, User], str] = lambda _session, _user: ""


IMPORTERS: dict[str, Importer] = {}


def register(importer: Importer) -> Importer:
    if importer.name in IMPORTERS:
        raise ValueError(f"importer {importer.name!r} is registered twice")
    for param in importer.params:
        if param.kind not in PARAM_KINDS:
            raise ValueError(f"importer {importer.name!r}: parameter {param.name!r} is of no kind there is ({param.kind!r})")
        if param.kind == "choices" and param.choices is None:
            raise ValueError(f"importer {importer.name!r}: parameter {param.name!r} has nothing to choose from")
    IMPORTERS[importer.name] = importer
    return importer


def parse_params(session: Session, owner: User, importer: Importer, given: Any) -> dict[str, Any]:
    """ The parameters of a run, checked against what the importer takes; ParamError when one is wrong. """
    if not isinstance(given, dict):
        raise ParamError("params: expected an object")
    names = {param.name for param in importer.params}
    unknown = sorted(set(given) - names)
    if unknown:
        raise ParamError(f"{importer.name} takes no parameter {', '.join(unknown)}")
    params: dict[str, Any] = {}
    for param in importer.params:
        value = given.get(param.name)
        # "choices", the only kind so far
        if value is None:
            value = []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ParamError(f"{param.title}: expected a list of choices")
        if param.required and not value:
            raise ParamError(f"{param.title}: choose at least one")
        if value:
            assert param.choices is not None
            allowed = {choice for choice, _label in param.choices(session, owner)}
            wrong = [v for v in value if v not in allowed]
            if wrong:
                raise ParamError(f"{param.title}: not one of the choices: {', '.join(wrong)}")
        # each once, in the order given
        params[param.name] = list(dict.fromkeys(value))
    return params


def run(session: Session, owner: User, importer: Importer, given: Any, dry_run: bool) -> ImportRun:
    """
    Run an importer as owner, and keep the run (models.ImportRun). A dry run
    does it all and rolls it back, so its counts say what a real one would
    do. One that fails is rolled back and says why. ParamError, before
    anything is run, when it cannot be.
    """
    reason = importer.unavailable(session, owner)
    if reason:
        raise ParamError(reason)
    params = parse_params(session, owner, importer, given)
    started = utcnow()
    report = Report()
    status = "done"
    try:
        importer.run(session, owner, params, report)
        session.flush()
    except IntegrityError:
        session.rollback()
        status = "failed"
        report.say("Failed: another import added the same rows meanwhile; run it again")
    except (ImporterError, requests.RequestException) as e:
        session.rollback()
        status = "failed"
        report.say(f"Failed: {e}")
    if status == "done" and not dry_run:
        session.commit()
    else:
        session.rollback()
    record = ImportRun(
        owner_id=owner.id, importer=importer.name, params=params, dry_run=dry_run, status=status,
        counts=dict(report.counts) if status == "done" else {}, log="\n".join(report.lines),
        started_at=started, finished_at=utcnow(),
    )
    session.add(record)
    session.commit()
    return record


def run_json(record: ImportRun) -> dict[str, Any]:
    importer = IMPORTERS.get(record.importer)
    return {
        "id": record.id,
        "importer": record.importer,
        "title": importer.title if importer else record.importer,
        "params": record.params,
        "dry_run": record.dry_run,
        "status": record.status,
        "counts": record.counts,
        "log": record.log,
        "started_at": record.started_at.isoformat(),
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }
