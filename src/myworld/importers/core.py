"""
What every importer is made of: its parameters, the report it writes, the
register it is in, and running one, which is the same for all of them.

A run is not done in the request that asks for it: it is queued (start),
and a job of its own does it (execute; on Cloud Run a Cloud Run Jobs
execution, see myworld.importers.jobs), saying what it has done so far and
that it is alive as it goes. A run whose job stopped answering is failed
(settle). A regular user may start RUNS_PER_MONTH runs a month; an admin,
any number.

An importer may be run again and again with nothing to fear: every row it
writes has a key it is told from the others by (a YouTube video by its id),
so a row the user has is never added twice; of a row they have it may
refresh only what the source says of it (the channel of a video, its
views), never what the user wrote (a rating, a review). So a second run
right after the first adds nothing and changes nothing.
"""

import dataclasses
import datetime as dt
import logging
import os
import threading
import time
import traceback
from collections import Counter
from typing import TYPE_CHECKING, Any, override

import requests
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from myworld.models import (
    IMPORT_ENDED,
    ROLE_ADMIN,
    ImportRun,
    ImportUsage,
    User,
    utcnow,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# the runs a regular user may start in a calendar month (UTC), dry ones too: each is a job;
# IMPORT_RUNS_PER_MONTH says otherwise. An admin has no limit.
RUNS_PER_MONTH = 100
# how often a running job says it is alive, with what it has done so far
HEARTBEAT_SECONDS = 10
# a running run whose job has not said it is alive for this long has stopped (its job died or was cancelled)
STALE_SECONDS = 120
# a queued run whose job has not started in this long never will
QUEUED_SECONDS = 600

# the kinds of parameter there are, as the Imports page draws them:
# "choices" is one or more of a list the importer gives for the user (a list of strings);
# "file" is a file the user uploads with the run (its text), which the importer's read turns
# into what the run keeps: only that is kept, never the file itself
PARAM_KINDS = ("choices", "file")
# the most an uploaded file may be
FILE_MAX_CHARS = 20 * 1024 * 1024


class ImporterError(Exception):
    """ An import that cannot go on: it is rolled back, and the run says why. """


class ParamError(ImporterError):
    """ A parameter given wrong: nothing is run. """


class LimitError(ImporterError):
    """ The user has started as many runs this month as they may. """


@dataclasses.dataclass(frozen=True)
class Param:
    name: str
    title: str
    kind: str
    description: str = ""
    required: bool = False
    # for "choices": what may be chosen, for this user, as (value, label)
    choices: Callable[[Session, User], list[tuple[str, str]]] | None = None
    # one choice at most, not as many as wanted
    single: bool = False
    # for "file": what the file is turned into for the run (JSON), ParamError when it is not what is wanted;
    # and what the run's log says of that, as one line ("12 books")
    read: Callable[[str], Any] | None = None
    said: Callable[[Any], str] | None = None
    # for "file": the kinds of file the page offers to pick (".csv")
    accept: str = ""


def stamped(line: str) -> str:
    """ A line of a run's log, with the time (UTC) it was said: "10:04:05 Countries". """
    return f"{utcnow():%H:%M:%S} {line}"


class Report:
    """
    What an import did: counts of what it did ("YouTube videos added": 3)
    and the lines it said, each with its time: the run's log, which the
    Imports page shows (its Log), as it goes and after.
    """

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.lines: list[str] = []

    def count(self, what: str, n: int = 1) -> None:
        self.counts[what] += n

    def say(self, line: str) -> None:
        self.lines.append(stamped(line))


class _Captured(logging.Handler):
    """
    While a run goes: the warnings and errors logged in its thread (the
    importer's, a library's, an exception's traceback) go into its log too,
    so the Imports page shows all of it, not only what the importer said.
    """

    def __init__(self, report: Report) -> None:
        super().__init__(logging.WARNING)
        self.report = report
        self.thread = threading.get_ident()

    @override
    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread:
            return
        self.report.say(f"{record.levelname}: {record.getMessage()}")
        if record.exc_info and record.exc_info[1] is not None:
            for line in "".join(traceback.format_exception(record.exc_info[1])).rstrip().splitlines():
                self.report.say(f"  {line}")


@dataclasses.dataclass(frozen=True)
class Importer:
    name: str
    title: str
    description: str
    # the data it adds to, a key of checks.DATASETS ("youtube"); None for one that adds to none (a test)
    dataset: str | None
    params: tuple[Param, ...]
    # does the import into the session, without committing: run() commits or rolls back
    run: Callable[[Session, User, dict[str, Any], Report], None]
    # why the user cannot run it now ("connect YouTube first"), "" when they can
    unavailable: Callable[[Session, User], str] = lambda _session, _user: ""
    # only an admin sees it, and may run it
    admin_only: bool = False
    # it writes the shared data (countries, cities, ...), everyone's: only an admin sees it, and may run it
    shared: bool = False


def for_admins(importer: Importer) -> bool:
    """ Whether only admins see and run importer: one made for them, or one that writes the shared data. """
    return importer.admin_only or importer.shared


def visible(importer: Importer, user: User) -> bool:
    return not for_admins(importer) or user.role == ROLE_ADMIN


IMPORTERS: dict[str, Importer] = {}


def register(importer: Importer) -> Importer:
    if importer.name in IMPORTERS:
        raise ValueError(f"importer {importer.name!r} is registered twice")
    for param in importer.params:
        if param.kind not in PARAM_KINDS:
            raise ValueError(f"importer {importer.name!r}: parameter {param.name!r} is of no kind there is ({param.kind!r})")
        if param.kind == "choices" and param.choices is None:
            raise ValueError(f"importer {importer.name!r}: parameter {param.name!r} has nothing to choose from")
        if param.kind == "file" and param.read is None:
            raise ValueError(f"importer {importer.name!r}: parameter {param.name!r} has nothing to read its file")
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
        if param.kind == "file":
            params[param.name] = _read_file(param, value)
            continue
        if value is None:
            value = []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ParamError(f"{param.title}: expected a list of choices")
        if param.required and not value:
            raise ParamError(f"{param.title}: choose {'one' if param.single else 'at least one'}")
        if param.single and len(value) > 1:
            raise ParamError(f"{param.title}: choose only one")
        if value:
            assert param.choices is not None
            allowed = {choice for choice, _label in param.choices(session, owner)}
            wrong = [v for v in value if v not in allowed]
            if wrong:
                raise ParamError(f"{param.title}: not one of the choices: {', '.join(wrong)}")
        # each once, in the order given
        params[param.name] = list(dict.fromkeys(value))
    return params


def _read_file(param: Param, value: Any) -> Any:
    """ An uploaded file's text as what the run keeps of it; ParamError when it is missing, too large or not what is wanted. """
    if value is None or value == "":
        if param.required:
            raise ParamError(f"{param.title}: choose a file")
        return None
    if not isinstance(value, str):
        raise ParamError(f"{param.title}: expected the file's text")
    if len(value) > FILE_MAX_CHARS:
        raise ParamError(f"{param.title}: the file is larger than {FILE_MAX_CHARS // (1024 * 1024)} MB")
    assert param.read is not None
    return param.read(value)


def runs_allowed(owner: User) -> int | None:
    """ How many runs owner may start a month; None for no limit (an admin). """
    if owner.role == ROLE_ADMIN:
        return None
    return int(os.environ.get("IMPORT_RUNS_PER_MONTH", RUNS_PER_MONTH))


def _month() -> dt.date:
    """ The first day of this calendar month (UTC). """
    return utcnow().date().replace(day=1)


def runs_used(session: Session, owner: User) -> int:
    """ How many runs owner started this calendar month (UTC), whatever became of them, deleted ones too (models.ImportUsage). """
    usage = session.get(ImportUsage, (owner.id, _month()))
    return usage.runs if usage is not None else 0


def _count_run(session: Session, owner: User) -> None:
    """ One more run started by owner this month. """
    usage = session.get(ImportUsage, (owner.id, _month()))
    if usage is None:
        session.add(ImportUsage(owner_id=owner.id, month=_month(), runs=1))
    else:
        usage.runs += 1


def start(session: Session, owner: User, importer: Importer, given: Any, *, dry_run: bool, dispatch: Callable[[int], str]) -> ImportRun:
    """
    Queue a run of importer as owner and have its job started (dispatch,
    which says the job's execution). ParamError when it cannot be run (its
    parameters, or it is not available), LimitError when owner started as
    many as they may this month. A job that cannot be started fails the run.
    """
    if not visible(importer, owner):
        raise ParamError(f"no importer called {importer.name}")
    reason = importer.unavailable(session, owner)
    if reason:
        raise ParamError(reason)
    params = parse_params(session, owner, importer, given)
    allowed = runs_allowed(owner)
    if allowed is not None and runs_used(session, owner) >= allowed:
        raise LimitError(f"You have started your {allowed} import runs of this month; more may be started on the 1st")
    record = ImportRun(owner_id=owner.id, importer=importer.name, params=params, dry_run=dry_run, status="queued", counts={}, log="", started_at=utcnow())
    session.add(record)
    _count_run(session, owner)
    session.commit()
    run_id = record.id
    try:
        execution = dispatch(run_id)
    except (requests.RequestException, ImporterError) as e:
        logger.exception("the job of import run %s could not be started", run_id)
        session.execute(
            update(ImportRun).where(ImportRun.id == run_id, ImportRun.status == "queued")
            .values(status="failed", log=stamped(f"Failed: its job could not be started: {e}"), finished_at=utcnow())
        )
        session.commit()
    else:
        if execution:
            session.execute(update(ImportRun).where(ImportRun.id == run_id).values(execution=execution))
            session.commit()
    session.expire_all()
    found = session.get(ImportRun, run_id)
    assert found is not None
    return found


class Heartbeat(threading.Thread):
    """ While a run goes: every HEARTBEAT_SECONDS, that it is alive and what it has done so far, in a session of its own. """

    def __init__(self, engine: Engine, run_id: int, report: Report) -> None:
        super().__init__(name=f"import-run-{run_id}-heartbeat", daemon=True)
        self.engine = engine
        self.run_id = run_id
        self.report = report
        self.stopping = threading.Event()

    @override
    def run(self) -> None:
        while not self.stopping.wait(HEARTBEAT_SECONDS):
            try:
                with Session(self.engine) as session:
                    session.execute(
                        update(ImportRun).where(ImportRun.id == self.run_id, ImportRun.status == "running")
                        .values(heartbeat_at=utcnow(), log="\n".join(list(self.report.lines)), counts=dict(self.report.counts))
                    )
                    session.commit()
            except SQLAlchemyError:
                # the next one may get through; a run that never does is settled as stopped
                logger.warning("import run %s: could not say it is alive", self.run_id, exc_info=True)

    def stop(self) -> None:
        self.stopping.set()
        self.join()


def _said(importer: Importer | None, key: str, value: Any) -> str:
    """ A parameter of a run as its log says it: "playlists = a, b"; a file as its importer says it ("file = 12 books"). """
    param = next((p for p in importer.params if p.name == key), None) if importer else None
    if param is not None and param.said is not None:
        return f"{key} = {param.said(value)}"
    return f"{key} = {', '.join(map(str, value)) if isinstance(value, list) else value}"


def execute(engine: Engine, run_id: int) -> None:
    """
    Do a queued run: what its job does. It is marked running and says it is
    alive as it goes; a dry run does it all and rolls it back, so its counts
    say what a real one would do; one that fails is rolled back and says
    why. A run that is not queued (done already, or settled) is left alone.
    """
    with Session(engine) as session:
        record = session.get(ImportRun, run_id)
        if record is None or record.status != "queued":
            logger.warning("import run %s is not queued: nothing to do", run_id)
            return
        record.status = "running"
        record.heartbeat_at = utcnow()
        session.commit()
        importer = IMPORTERS.get(record.importer)
        owner = session.get(User, record.owner_id)
        params = dict(record.params)
        dry_run = record.dry_run
        report = Report()
        status = "done"
        beat = Heartbeat(engine, run_id, report)
        beat.start()
        captured = _Captured(report)
        logging.getLogger().addHandler(captured)
        started = time.monotonic()
        # how it began: which importer, for whom, with what (the log says the rest as it goes)
        given = ", ".join(_said(importer, key, value) for key, value in params.items() if value not in (None, "", []))
        report.say(" ".join(filter(None, (
            f"Started {importer.title if importer else record.importer}",
            f"for {owner.email}" if owner else "",
            "(a dry run: nothing will be kept)" if dry_run else "",
            f"with {given}" if given else "",
        ))))
        try:
            if importer is None or owner is None:
                raise ImporterError(f"there is no importer {record.importer} any more")
            reason = importer.unavailable(session, owner)
            if reason:
                raise ImporterError(reason)
            importer.run(session, owner, params, report)
            session.flush()
            if not dry_run:
                session.commit()
            # how it ended, last (the runs table shows the last line): whether it was kept, and everything it counted
            kept = "a dry run, nothing kept" if dry_run else "saved"
            report.say(f"Done in {time.monotonic() - started:.1f}s ({kept}): " + ("; ".join(f"{n} {what}" for what, n in report.counts.items()) or "nothing to change"))
        except IntegrityError:
            status = "failed"
            report.say("Failed: another import added the same rows meanwhile; run it again")
        except (ImporterError, requests.RequestException) as e:
            status = "failed"
            report.say(f"Failed: {e}")
        except Exception as e:
            logger.exception("import run %s failed", run_id)
            status = "failed"
            report.say(f"Failed: {type(e).__name__}: {e}")
        finally:
            logging.getLogger().removeHandler(captured)
            beat.stop()
        session.rollback()
        session.execute(
            update(ImportRun).where(ImportRun.id == run_id).values(
                status=status, counts=dict(report.counts) if status == "done" else {}, log="\n".join(report.lines),
                heartbeat_at=utcnow(), finished_at=utcnow(),
            )
        )
        session.commit()


def settle(session: Session) -> None:
    """ Fail the runs whose jobs stopped: running ones no longer saying they are alive, queued ones never started. """
    now = utcnow()
    session.execute(
        update(ImportRun).where(ImportRun.status == "running", ImportRun.heartbeat_at < now - dt.timedelta(seconds=STALE_SECONDS))
        .values(status="failed", log=ImportRun.log + "\n" + stamped("Failed: its job stopped answering (it died, ran out of time or was cancelled)"), finished_at=now)
    )
    session.execute(
        update(ImportRun).where(ImportRun.status == "queued", ImportRun.started_at < now - dt.timedelta(seconds=QUEUED_SECONDS))
        .values(status="failed", log=stamped("Failed: its job never started"), finished_at=now)
    )
    session.commit()


def ended(record: ImportRun) -> bool:
    return record.status in IMPORT_ENDED


def run_json(record: ImportRun, owner: User | None = None) -> dict[str, Any]:
    """ A run, as the page shows it; with owner (an admin's list of everyone's runs), whose it is. """
    importer = IMPORTERS.get(record.importer)
    out: dict[str, Any] = {
        "id": record.id,
        "importer": record.importer,
        "title": importer.title if importer else record.importer,
        "params": record.params,
        "dry_run": record.dry_run,
        "status": record.status,
        "counts": record.counts,
        "log": record.log,
        "started_at": record.started_at.isoformat(),
        "heartbeat_at": record.heartbeat_at.isoformat() if record.heartbeat_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        "ended": ended(record),
        "execution": record.execution,
    }
    if owner is not None:
        out["owner"] = {"id": owner.id, "username": owner.username, "email": owner.email}
    return out
