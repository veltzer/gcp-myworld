# The Imports page

The Imports page (sidebar, Overview, every account) brings a user's data in
from elsewhere. Each importer has parameters of its own, a Dry run and a
Run, and the page lists the user's last runs. An importer imports into the
signed-in user's own data only.

## Running again is safe

Every importer may be run again whenever, on the same source or on a newer
one:

- Every row it writes has a key it is told from the others by (a YouTube
  video by its id, `uq_youtube_video_id`), so a row the user has is never
  added twice. The unique constraint keeps it so even when two runs go at
  once: the second fails, keeps nothing, and says to run it again.
- Of a row the user has, it may refresh only what the source says of it (a
  video's channel, category, length, upload day and views) and fill what is
  empty; never what the user wrote (a name, a rating, a review, a device, a
  date).
- So a second run right after the first adds nothing and changes nothing,
  and its counts say so ("YouTube videos unchanged: 40").

A dry run does everything and rolls it back: its counts say what a run
would do. A run that fails (YouTube refused, the connection is gone) is
rolled back whole and says why. Every run, dry or not, done or failed, is
kept in `import_runs`: the importer, its parameters, its counts and what it
said.

## YouTube playlists

`youtube-playlists` adds the videos of playlists of the user's own YouTube
account to their YouTube videos, as videos they watched. Its parameter is
the playlists, any number of them, picked from the account's own (their
liked videos first, then every playlist by title); the page starts with
those of the user's last run picked, but for any deleted on YouTube since. A video they do not have is added with what
YouTube says of it; one they have gets YouTube's details as they are now. A
video YouTube no longer has (deleted, private) is added with its id only,
marked unavailable; one the user has keeps what was known of it and is
marked unavailable. It only ever adds: a video taken out of a playlist
since stays. A playlist does not say when a video was watched, only when
it was put in the playlist, so a video it adds has no date.

## YouTube details

`youtube-details` gives YouTube's details (channel, category, length,
upload day, views) to the user's YouTube videos that have none: no channel,
or no length. Those are videos that came with a name only (a watch history
that had no details for them), and the ones YouTube no longer had, asked
about again in case it has them back. It takes no parameters and adds
nothing; a video YouTube does not have is marked unavailable and keeps what
was known of it, and what the user wrote is never changed. It reads YouTube
through the same connection as the playlists, so a run again asks only
about the videos still without details.

## Connecting YouTube

The YouTube importers read YouTube as the user, through the YouTube Data API: the user
connects their YouTube account on the page once ("Connect YouTube"), which
asks Google's consent for the `youtube.readonly` scope, read only. Signing
in with Google asks nothing of the kind: it only says who the user is.

- `GET /youtube/connect` sends the user to Google's consent screen;
  `/youtube/callback` trades the code for a refresh token and keeps it in
  `youtube_connections`, sealed (Fernet) with a key derived from
  `SECRET_KEY`, so the database alone does not give it away. A new
  `SECRET_KEY` makes it unreadable, and the user connects again.
- Each run trades it for an access token, which lasts an hour and is never
  kept.
- `POST /youtube/disconnect` revokes it at Google and forgets it.

There is no API key: a key reads only what is public, and the token reads
everything the user's account may, private playlists too. A token reaches
only its own account. The quota (10,000 units a day for the whole site) is
spent at about one unit per 50 videos.

### One-time setup

It uses the OAuth web client that "Sign in with Google" uses
(`gcp_oauth_client_id` in `.gcp.conf`), with its secret, and is offered only
when `GOOGLE_CLIENT_SECRET` is set; without it the page says connecting is
not set up and the importer stays, disabled.

1. In the Cloud Console of the project: enable the YouTube Data API v3
   (`APIs & Services -> Library`).
2. On the OAuth consent screen (`Google Auth Platform -> Data access`) add
   the scope `https://www.googleapis.com/auth/youtube.readonly`. Under
   `Branding` give the home page `https://myworld.stream`, the privacy
   policy `https://myworld.stream/privacy` (`html/privacy.html`, linked
   from the landing page's footer) and the authorized domains, then publish
   the app (`Audience`): in "Testing" Google lets a refresh token live
   seven days only. Until Google verifies the app, Google's consent screen
   warns that the app is unverified, and at most 100 users may connect.
3. On the web client (`Google Auth Platform -> Clients`) add the authorized
   redirect URIs `https://myworld.stream/youtube/callback` and
   `http://localhost:8080/youtube/callback`. Connecting on the alias host
   comes back through the canonical one, as GitHub's sign-in does.
4. Put the client's secret in the password store as
   `keys/google.com.myworld-oauth`, add
   `"${gcp_service}-google-client-secret=pass:keys/google.com.myworld-oauth"`
   to `gcp_secrets` and `GOOGLE_CLIENT_SECRET=${gcp_service}-google-client-secret:latest`
   to `--set-secrets` in `.gcp.conf`, run `gcloud_project_setup.sh` to
   create the secret, and deploy.

Locally:

```bash
GOOGLE_CLIENT_ID=<gcp_oauth_client_id> GOOGLE_CLIENT_SECRET="$(pass show keys/google.com.myworld-oauth)" \
  MYWORLD_DEV_LOGIN=1 python src/main.py
```

## API

- `GET /api/importers`: the importers, each with its parameters and, for a
  parameter of choices, what may be chosen (asked of the source only when
  the importer can run; `error` says why they could not be read), and
  `chosen`, what the user's last run of it chose of those (the page starts
  with them), and `unavailable`, why the user cannot run it now ("Connect YouTube first"),
  `""` when they can; and `youtube`, the state of the connection.
- `POST /api/importers/<name>/runs` with
  `{"params": {...}, "dry_run": false}`: runs it and answers the run (`status` `done` or `failed`,
  `counts`, `log`). 400 for parameters it does not take, a choice that is
  not one, or an importer that cannot run; nothing is run then.
- `GET /api/import-runs`: the user's last 20 runs, newest first.
- `GET /youtube/status`: whether connecting is set up, whether the user
  connected, and the channel connected.

## A new importer

A module in `src/myworld/importers/` that registers an `Importer` (name,
title, description, the page of data it adds to, its parameters, and the
function that does the import into the session, counting what it does on
the `Report`) and is named in `importers/__init__.py`. The page draws its
parameters, and running it, keeping the run, dry runs and rolling back are
the same for all (`importers/core.py`). It keeps to the rules above: a key
for every row, and only the source's columns refreshed.
