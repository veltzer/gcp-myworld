"""
Starting the job that does a run (core.execute). On Cloud Run that is an
execution of the Cloud Run Job IMPORT_JOB names
("projects/<project>/locations/<region>/jobs/<job>"), deployed with the
service from the same image (.gcp.conf, gcp_job_*): it runs
`python -m myworld.importers.worker <run id>` in a container of its own,
with the whole CPU for as long as the run takes, and nothing is billed
between runs. The service starts it as its service account, which may run
the job with other arguments (roles/run.jobsExecutorWithOverrides).

Anywhere else (development) a run is done in a thread of the app itself.
"""

import os
import threading
from typing import TYPE_CHECKING

import requests

from myworld.importers.core import ImporterError, execute

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.engine import Engine

RUN_API = "https://run.googleapis.com/v2"
# the token of the service account the service runs as, from the metadata server of Cloud Run
TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
HTTP_TIMEOUT = 30

# the command the job runs, but for the run's id (the job's own command is python)
WORKER_ARGS = ["-m", "myworld.importers.worker"]


def access_token() -> str:
    response = requests.get(TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


def run_job(job: str, run_id: int) -> str:
    """ Start an execution of job for run_id; the execution's name. """
    response = requests.post(
        f"{RUN_API}/{job}:run",
        headers={"Authorization": f"Bearer {access_token()}"},
        json={"overrides": {"containerOverrides": [{"args": [*WORKER_ARGS, str(run_id)]}]}},
        timeout=HTTP_TIMEOUT,
    )
    if not response.ok:
        raise ImporterError(f"Cloud Run answered {response.status_code}: {response.text[:300]}")
    # a long-running operation, whose metadata is the execution
    return str((response.json().get("metadata") or {}).get("name") or "")


def in_thread(engine: Engine) -> Callable[[int], str]:
    def dispatch(run_id: int) -> str:
        threading.Thread(target=execute, args=(engine, run_id), name=f"import-run-{run_id}", daemon=True).start()
        return ""
    return dispatch


def dispatcher(engine: Engine) -> Callable[[int], str]:
    """ How runs are started here: a Cloud Run Jobs execution when IMPORT_JOB is set, else a thread. """
    job = os.environ.get("IMPORT_JOB", "")
    if job:
        return lambda run_id: run_job(job, run_id)
    return in_thread(engine)
