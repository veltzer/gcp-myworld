# Deploying the app to Cloud Run

The app runs as a Cloud Run service called `myworld` in `us-central1`, with
its data in a Cloud SQL (PostgreSQL) instance in the same region. The
gcloud configuration, region and resource names are in `.gcp.conf`.

## Regular deploy

```bash
./scripts/deploy.sh
```

The script wraps `gcloud run deploy --source .`: Cloud Build builds the
`Dockerfile` and the new revision replaces the old one with no downtime.
Everything the service needs (Cloud SQL attachment, environment, secrets,
scaling, the service account) lives in the script as flags.

## One-time project setup

1. Create the resources: `./scripts/setup.sh`. It enables the APIs, creates
   the service account the app runs as, the Cloud SQL instance, database
   and user, and puts the database password and the Flask session key in
   Secret Manager. Note the Cloud SQL instance is billed per hour.
1. Create the OAuth client for "Sign in with Google". This part cannot be
   scripted for a project outside an organization:
   1. Console: `APIs & Services -> OAuth consent screen`. Configure it as
      `External`, set the app name and support email, and publish it. No
      scopes are needed beyond the defaults (email, profile, openid).
   1. Console: `APIs & Services -> Credentials -> Create credentials ->
      OAuth client ID`, application type `Web application`.
   1. Under `Authorized JavaScript origins` add the service URL and
      `http://localhost:8080` for local development. The service URL is
      deterministic, `https://myworld-<project-number>.us-central1.run.app`
      (`gcloud projects describe <project> --format 'value(projectNumber)'`),
      so it can be registered before the first deploy.
   1. Under `Authorized redirect URIs` add the login endpoint on both
      origins: `http://localhost:8080/auth/login` and
      `https://myworld-<project-number>.us-central1.run.app/auth/login`.
      The sign-in button runs in redirect mode, and Google refuses to POST
      the credential to an unregistered URI (`redirect_uri_mismatch`).
   1. Paste the client ID into `gcp_oauth_client_id` in `.gcp.conf`. Client
      IDs are public, so it is fine to commit it.
1. Deploy: `./scripts/deploy.sh`. The first deploy can happen before the
   OAuth client exists only by temporarily leaving the check in the script,
   so do the OAuth step first and use a placeholder origin if the URL is
   not known yet; the URL is deterministic
   (`https://myworld-<project-number>.us-central1.run.app`).

## How sign-in works

The landing page (static HTML plus `static/app.js`) renders the Google
Identity Services button in redirect mode. On success Google POSTs a signed
ID token to `/auth/login` along with a CSRF token that is also set as a
cookie. The server checks the two CSRF copies match,
verifies the token against `GOOGLE_CLIENT_ID` with `google-auth`, upserts
the user by the Google `sub` claim, and stores only our own user id in the
signed Flask session cookie. No Firebase is involved.

## Pages and API

The HTML under `src/myworld/html/` is static; `static/app.js` fetches
`/api/config` (who is signed in, the kinds and statuses) and then reads and
writes `/api/library` as JSON. The API is what a future mobile client or a
script would use as well:

- `GET /api/library[?kind=book]`: the user's entries.
- `POST /api/library`: add (or update, if the work is already in the
  library) with `kind`, `title`, `creator`, `year`, `status`, `rating`,
  `started_on`, `finished_on`, `notes`.
- `PUT /api/library/<work_id>`: update the per-user fields.
- `DELETE /api/library/<work_id>`: remove from the library.

## Data model

- `users`: one row per Google account (`google_sub` is the stable key).
- `works`: books, films, series, albums, games; one shared row per work,
  identified by kind, title, creator and year. New kinds are added to
  `KINDS` in `src/myworld/models.py`.
- `user_works`: what a user thinks about a work: status, rating, dates,
  notes. All per-user queries go through this table, so users never see
  each other's entries even though the work rows are shared.

Tables are created on startup with `create_all`; there is no migration
tool yet. Adding columns to an existing deployment needs a manual
`ALTER TABLE` (or introducing Alembic) at that point.

## Local development

```bash
uv sync
MYWORLD_DEV_LOGIN=1 python src/main.py
```

Runs the Flask dev server on port 8080 against a sqlite file in `db.gi/`.
With `MYWORLD_DEV_LOGIN=1` the landing page also offers a development
login by email, so no OAuth client is needed locally; the route is disabled
on Cloud Run regardless of the variable. To test the real Google button
locally, export `GOOGLE_CLIENT_ID` and make sure `http://localhost:8080` is
among the client's authorized origins.

To develop against the real Cloud SQL instance, run the Cloud SQL Auth
Proxy and point `DATABASE_URL` at it:

```bash
cloud-sql-proxy "$(gcloud config get-value project):us-central1:myworld-db" &
DATABASE_URL="postgresql+pg8000://myworld:<password>@127.0.0.1:5432/myworld" python src/main.py
```
