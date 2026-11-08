# Database checks

Rules the data should follow that the app does not enforce when it is
written: a logo inserted with SQL, a row an old version left behind. The
checks read the whole database, every account's rows, and change nothing.

## Running them

- **In the app:** the Checks page (top bar, admins only; see
  `accounts.md`) lists every check with a Run button and a Run all
  button, and shows what each one found.
- **From the command line:** `scripts/check.py` runs the same checks
  against `DATABASE_URL` (the local sqlite file by default) and exits 1
  when one finds a problem:

```bash
scripts/check.py                        # every check
scripts/check.py logos                  # only these
scripts/check.py --list                 # what there is
scripts/with_cloud_db.sh scripts/check.py   # production
```

`scripts/with_cloud_db.sh` runs any command with `DATABASE_URL` pointing
at Cloud SQL through the Auth Proxy (it is what `import_world_cloud.sh`
uses too).

## The checks

- `logos`: every SVG image follows the logo convention in `logos.md`
  (canvas, square viewBox, nothing active or external). The margin and
  centering are not checked: they need a renderer.
- `organization-logos`: every organization has a logo.
- `organization-relations`: every organization has at least one relation
  type.
- `person-types`: every person has at least one person type.

## Adding one

A check is one function in `src/myworld/checks.py`, from a database
session to a `Result` (how many things it looked at, and a `Problem` for
each thing wrong: what it is about, so a person can find it, and what is
wrong). Register it with `@check(name, title, noun)`; its docstring is
the description the page and `--list` show. The page, the API
(`GET /api/checks`, `GET /api/checks/<name>`) and the script pick it up
with no other change. Give it a test in `tests/checks_test.py`.
