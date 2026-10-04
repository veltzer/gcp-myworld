# TOFIX

Findings from a code scan on 2026-10-04.

## High

- `src/myworld/views.py:213` - `Work` rows are shared between all users (`src/myworld/models.py:4`), yet `_apply_work_ids` lets any signed-in user overwrite `imdb_id`, `tmdb_id` and `rotten_tomatoes_id` on an existing shared work with whatever the request body carries, changing the IMDb/RT links every other user sees for that title. Only fill ids that are currently empty (the docstring at line 148 already promises "only ever filled in"), or resolve ids server-side from `tmdb_id` via `movies.details()` instead of trusting the client.

## Medium

- `src/myworld/models.py:130` - the Cloud SQL URL is built with an f-string, so a `DB_PASS` (or user/db name) containing `@`, `:`, `/`, `?` or `#` produces a broken or misparsed URL. Build it with `sqlalchemy.engine.URL.create("postgresql+pg8000", username=..., password=..., database=..., query={"unix_sock": socket})`.
- `src/myworld/auth.py:173` - `/auth/email/login` has no attempt limiting, so passwords of email accounts can be brute-forced against the public Cloud Run service. Add per-account/per-IP throttling (e.g. a failed-attempt counter with lockout/backoff on `User`).
- `rsconstruct.toml:28` - ruff and mypy (`:31`) list `scripts` and `config`, which hold no `.py` files (only `scripts/migrate.sh` and Lua), and shellcheck (`:46`) lists `src` and `config`, which hold no `.sh` files. Make them precise: ruff/mypy `["src", "tests"]`, shellcheck `["scripts"]`.

## Low

- `src/myworld/auth.py:178` - when the email has no account the password hash check is skipped, so response time reveals which emails are registered despite the single error message; run `check_password_hash` against a dummy hash in that branch.
- `src/myworld/views.py:207` - two concurrent adds of the same new work both miss the `select` and the second `flush` hits `uq_work_identity` as an unhandled `IntegrityError` (500); catch it, roll back and re-select. Note also that the unique constraint does not stop duplicates when `year` is NULL (NULLs are distinct).
- `src/myworld/movies.py:163` - `USER_AGENT` advertises `https://github.com/veltzer/myworld`, but the repo is `veltzer/gcp-myworld`; it also hardcodes version `0.0.1` while `pyproject.toml:7` says `0.0.0` and `config/version.lua:2` says `0.0.1`. Fix the URL and keep one version source.
- `pyproject.toml:32` - `mypy_path = "src:python:scripts"` names a `python/` directory that does not exist and `scripts/` has no Python; use `"src"`.
- `src/myworld/models.py:70` (also `:93`, `tests/conftest.py:21`) - `# pylint: disable=...` comments, but pylint is neither a dev dependency nor a configured processor; remove the stale suppressions.
- `src/myworld/models.py:68` - `created_at`/`updated_at` (`:109`) are `DateTime` without `timezone=True` while `utcnow()` returns aware datetimes; on PostgreSQL the value is coerced through the session time zone. Use `DateTime(timezone=True)` (with a `scripts/migrate.sh` step) or store naive UTC consistently.
