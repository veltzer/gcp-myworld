# Ideas for new features

Taken from the Claude doc "My World — Feature Ideas" on 2026-11-20
(<https://claude.ai/artifact/BQW4TvZ4iN5n6MsyoXXr9v>). Suggestions only,
like `ideas_datamodel.md`. Where part of an idea is already built, a
**Today:** line says what exists, so the idea is only what is left.

## More categories

- Places travelled
- Restaurants
- Podcasts
- Museums and exhibitions
- People met

**Today:** museum visits (`museum_visits`) and people (`people`) are
built; places (`places`) are addresses, not trips.

## Timeline

Everything in one scrollable timeline, so a user can ask "what was I doing
in 2015?" and see it all. Every dated row already has the same date
columns (`date_utcz`, `date_ymd`, `date_my`, `date_y`), which is what a
merged timeline needs.

## Links between entries

Connect related items: a movie made from a book you read, or a concert by
a band you studied in a course.

## Ratings and notes

A rating and a short note on each entry, so you remember what you thought,
not just that you were there.

**Today:** a book reading (`library_reads`) and a museum visit have a
rating and a review; concerts, courses, videos and games do not.

## Quick import

Pull in existing history from Goodreads, Letterboxd, Spotify, or ticket
confirmation emails, so nothing has to be typed in by hand.

## On this day

Reminders of what you saw, read, or attended on this date in past years.

## Country data import

Import complete data for every country into the existing countries table:

- Flags
- Locale data (languages, number and date formats)
- Currency
- Time zones
- Everything else available per country

**Today:** `scripts/fetch_pictures.py` gives every country its flag
(Wikidata P41); a country is otherwise a name and a remark.

## Importers

Importers for these sources:

- Audible
- Goodreads
- YouTube playlists
- Google Photos (images)

**Today:** `scripts/import_chess.py` imports PGN files and
`scripts/import_chess_xml.py` the over-the-board games of `chess.xml`
(no moves), both safe to run again; `scripts/import_world.py` imports the world JSON, including a
YouTube history snapshot.

## Bookmarks

A bookmarks collection in My World, used to sync bookmarks across browsers.

## Passwords and keys

A vault for passwords and keys, such as API keys and SSH keys.

Open question: this is the riskiest feature in a multi-user system. It
needs client-side encryption, so the server never sees plaintext, and
isolation from the rest of the data. An alternative is to integrate with
an existing self-hosted vault such as Vaultwarden instead of building one.

## Face recognition and friend tagging

Link friends in My World to sample photos of them, then use image
recognition to tag them automatically across imported images.

## Recurring tasks

A built-in cron-like scheduler: tasks that run automatically on a
schedule, such as re-running importers to pull in new data. Example:
import the latest games from chess.com every week.

- **On GCP:** Cloud Scheduler for the schedules, triggering Cloud Run jobs
  (or an HTTP endpoint, or Pub/Sub) that run each importer.
- **Per user:** each user can enable or disable each importer for their
  own account. Rather than one Cloud Scheduler job per user, a single
  scheduled dispatcher reads every user's importer settings and runs only
  the enabled ones.
- **Idempotent:** running the same import twice never creates duplicates,
  for example by upserting on each source's own id (a chess.com game id,
  a Goodreads book id).
- **Incremental:** after the first full import, each run fetches only
  recent data, not the whole history. Each importer keeps a per-user
  cursor, such as the time of the last item imported, and starts from
  there with a small overlap; idempotency makes the overlap harmless.
  chess.com serves games in monthly archives, so a weekly run fetches only
  the current month (and the previous one near a month boundary) instead
  of all 30,000 games.
- **One-off or recurring:** each importer says which it is. One-off ones,
  such as the country data and the reference data below, can still be
  re-run by hand.

One-off reference importers:

- **Cities:** from GeoNames, with coordinates, population and time zone,
  linked to countries by country code.
- **Languages:** from ISO 639, for tagging books, movies and courses by
  language (`locales` already holds the languages titles are in).
- **Currencies:** from ISO 4217, as their own table.
- **Airports:** from OurAirports, for logging flights and showing them on
  the map.
- **Venues:** concert halls, stadiums and theatres, so concerts link to a
  real place.
- **Genres:** for books, movies and music, to keep tagging consistent.

## More ideas

- **Import log and alerts:** record each run's status and item count, and
  tell the user when an importer keeps failing, for example when a token
  expires.
- **Secure credentials:** store each user's OAuth tokens and API keys
  encrypted, for example with Secret Manager or Cloud KMS.
- **Rate limiting with backoff,** so sources like Goodreads or chess.com
  do not block the importers.
- **Plugin interface for importers:** each new source is one module
  implementing a standard contract.
- **Stats dashboards:** books per year, chess rating over time, and
  similar. **Today:** Stats counts rows, and chess games by outcome and
  by year.
- **Export and account deletion:** data portability and the right to
  erasure, needed under GDPR once other people register.

## Even more ideas

- **Search across everything:** one query ("Pink Floyd") finds the
  concerts, albums, books and photos together.
- **Wishlists:** books to read, movies to see, places to visit; logging
  an item moves it to done. **Today:** a book reading can have the status
  "Want to".
- **Concert setlists:** pulled in from setlist.fm for shows you attended.
- **Map view:** every country, city and venue you have been to.
  **Today:** museum visits and organizations have a Map layout
  (`doc/maps.md`).
- **Shared memories:** when two friends log the same concert, their
  entries link up.
- **AI year in review:** an automatic summary of each user's year every
  December.
