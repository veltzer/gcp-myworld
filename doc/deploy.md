# Deploying the app to Cloud Run

The app runs as a Cloud Run service called `myworld` in `us-central1`, with
its data in a Cloud SQL (PostgreSQL) instance in the same region. The
gcloud configuration, region and resource names are in `.gcp.conf`.

## Regular deploy

```bash
gcloud_run_deploy.sh
```

The script (from `utils-bash`) wraps `gcloud run deploy --source .`:
Cloud Build builds the `Dockerfile` and the new revision replaces the old
one with no downtime. Everything the service needs (Cloud SQL attachment,
environment, secrets, scaling, the service account) lives in `.gcp.conf` as
`gcp_run_args`, so a redeploy always converges the service to what that
file says.

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
1. Deploy: `gcloud_run_deploy.sh`. The app refuses to start on Cloud Run
   without `GOOGLE_CLIENT_ID`, so do the OAuth step first.

## Custom domain

The service answers on `https://myworld.stream` (`gcp_domain` in
`.gcp.conf`). The domain is registered at Cloudflare, which also serves
its DNS; Cloud Run owns the TLS certificate through a domain mapping, so
the Cloudflare records must be plain DNS (proxy off, "DNS only"), or
Google cannot issue and renew the certificate.

One-time setup, in this order:

1. Verify the domain for your Google account, which domain mappings
   require. `gcloud domains verify myworld.stream` opens Search Console;
   choose the `Domain` property type, copy the `google-site-verification=`
   value, add it at Cloudflare as a `TXT` record on `@`, and click Verify.
   `gcloud domains list-user-verified` shows it afterwards.
1. Deploy at least once, then `./scripts/map_domain.sh`. It creates the
   domain mapping and prints the `A` and `AAAA` records to add at
   Cloudflare on `@` (DNS only). The script is safe to re-run and doubles
   as a status check: the certificate is issued once the records resolve,
   usually within minutes, at most an hour.
1. Register the new origin with the sign-in providers, which reject
   unknown redirect targets: on the Google OAuth client add
   `https://myworld.stream` to the authorized JavaScript origins and
   `https://myworld.stream/auth/login` to the redirect URIs; on GitHub and
   Microsoft add `https://myworld.stream/auth/oauth/<provider>/callback`.

`www.myworld.stream` is not mapped; if wanted, add a second mapping for it
(`gcloud beta run domain-mappings create --domain www.myworld.stream`,
a `CNAME` to `ghs.googlehosted.com`) or a Cloudflare redirect rule.

## How sign-in works

The landing page (static HTML plus `static/app.js`, with the animated
scene in `static/scene.svg`) offers four ways in. Whichever one is used,
the server ends up creating or updating a row in `users` keyed by a
provider-qualified subject and storing only our own user id in the signed
Flask session cookie. Accounts are never matched by email: the same email
signed in through Google and through the password form is two accounts.

- Google: the Google Identity Services button in redirect mode. On success
  Google POSTs a signed ID token to `/auth/login` along with a CSRF token
  that is also set as a cookie. The server checks the two CSRF copies
  match, verifies the token against `GOOGLE_CLIENT_ID` with `google-auth`,
  and matches the user by the Google `sub` claim. No Firebase is involved.
- Email and password: `POST /auth/email/register` and
  `POST /auth/email/login` take `{"email", "password"}` as JSON and answer
  with `{"next": "/library"}` or `{"error": "..."}`. Passwords are stored
  as werkzeug hashes in `users.password_hash`; the subject is
  `email:<address>`. Always available, nothing to configure.
- GitHub and Microsoft: the plain OAuth 2.0 authorization code flow.
  `GET /auth/oauth/<provider>` redirects to the provider with a random
  `state` kept in the session; `/auth/oauth/<provider>/callback` checks the
  state, exchanges the code for an access token and asks the provider's
  user endpoint who signed in (subject `github:<id>` or
  `microsoft:<sub>`). A provider is offered only when both
  `<PROVIDER>_CLIENT_ID` and `<PROVIDER>_CLIENT_SECRET` are set, e.g.
  `GITHUB_CLIENT_ID`; the landing page disables the rest. Register the
  callback URL, `https://<service-url>/auth/oauth/github/callback` and
  the same for `microsoft`, with the provider when creating the OAuth app
  (GitHub: `Settings -> Developer settings -> OAuth Apps`; Microsoft:
  `Entra admin center -> App registrations`, single-page or web platform,
  accounts in any organizational directory and personal accounts). The
  secrets belong in Secret Manager and `--set-secrets` in `.gcp.conf`,
  next to `SECRET_KEY`.
- Development login: with `MYWORLD_DEV_LOGIN=1` (never on Cloud Run) the
  page also shows a form that signs in as any email, subject
  `dev:<address>`.

The `users.password_hash` column and the wider `google_sub` column were
added after the first deploy, so a database that predates them needs
`scripts/migrate_sign_in_methods.sh` once before deploying this version
(`--local` does the same for the sqlite file). It runs the ALTER TABLE
statements through the Cloud SQL Auth Proxy with the password from Secret
Manager, so there is nothing to type, and is safe to re-run; see the note on migrations under "Data
model".

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

- `users`: one row per account (`google_sub` is the stable key: the Google
  `sub` claim, or a provider-qualified subject for the other sign-in
  methods; `password_hash` is set only for email accounts).
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
