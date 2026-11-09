# Database checks

Rules the data should follow that the app does not enforce when it is
written: a logo inserted with SQL, a row an old version left behind. The
checks read the whole database, every account's rows, and change nothing.

## Running them

- **In the app:** the Checks page (sidebar, Overview, admins only; see
  `accounts.md`) lists the checks by dataset, a dataset for every page of
  data in the sidebar (Books, Concerts to YouTube, People,
  Organizations, and the four Types pages), each dataset under a heading
  with its own Run all. Every check is one row of the same height: a box
  that turns it on or off, its title (the description is the tooltip),
  what it found, and a Run button; Run all at the top runs them all in
  turn.
- **On a dataset's page:** the Checks button in the toolbar (next to the
  count) opens that page's checks over its rows and runs them all: on
  Books, the book checks. Every page of data has checks
  (`test_every_page_has_checks` fails when one has none); the button is
  disabled on the other pages (Stats, Checks, ...) and for an account
  that is not an admin.
- **Turning a check off:** clear its box, on either page, for a check
  you cannot pass yet. It is saved in the database for your account
  (`disabled_checks`): Run all skips it and says Off, and its Run is
  disabled until you tick it again. Each admin has their own.
- **What a problem says:** a failing check's count opens the
  list of problems under its row; a problem with a row of your own in the
  app (an organization, a person, a museum visit, a book) links to it. A check
  with thousands of problems sends the first 500, and says how many more
  there are.
- **From the command line:** `scripts/check.py` runs the same checks
  against `DATABASE_URL` (the local sqlite file by default) and exits 1
  when one finds a problem:

```bash
scripts/check.py                        # every check
scripts/check.py logos                  # only these
scripts/check.py --dataset book         # one dataset's, as its page runs them
scripts/check.py --list                 # what there is, by dataset
scripts/check.py --email me@example.com # skip the checks that account turned off
scripts/with_cloud_db.sh scripts/check.py   # production
```

`scripts/with_cloud_db.sh` runs any command with `DATABASE_URL` pointing
at Cloud SQL through the Auth Proxy (it is what `import_world_cloud.sh`
uses too).

## The checks

By dataset: the key is the page's name in the app (`#book`) and what
`--dataset` takes.

### Books (`book`)

- `book-covers`: every book has a cover.
- `book-links`: every book has a Goodreads or a Simania id, so its card
  links to its page.
- `book-authors`: every book has an author: one of the account's people,
  linked to it.
- `book-ratings`: every book read (Done) has a rating.
- `book-duplicates`: no account has two books of the same title and
  author.

### Concerts (`concerts`)

- `concert-dates`: every concert, of every account, has a date (a day, a
  month, a year or a full time).
- `concert-places`: every concert, of every account, has a venue and a
  city; one seen on TV need not.
- `concert-performers`: every concert, of every account, has at least
  one performer (a person).
- `concert-photos`: every concert, of every account, has a photo.
- `concert-duplicates`: no account has two concerts of the same name on
  the same date (ignoring case and spaces at the ends).

### Museums (`museums`)

- `museum-dates`: every museum visit has a date (a day, a month, a year
  or a full time).
- `museum-addresses`: every museum visit has an address.
- `museum-locations`: every museum visit has a latitude and a longitude.
- `museum-company`: every museum visit has people in With or is marked
  "I went alone", and none is both.

### Audio courses (`audio-courses`)

- `audio-course-lecturers`: every audio course has a lecturer.
- `audio-course-devices`: every audio course has a device.
- `audio-course-status`: every audio course is finished (has a date) or
  in progress (has a start), never neither.
- `audio-course-reviews`: every finished audio course has a rating and a
  review.
- `audio-course-covers`: every audio course has a cover.
- `audio-course-links`: every audio course has a Great Courses slug, an
  Audible ASIN or a link (any page about it, for a course no longer
  sold), so its card links to its page.
- `audio-course-stalled`: no audio course has been in progress for more
  than a year.
- `audio-course-duplicates`: no account has two audio courses of the same
  name.

### YouTube (`youtube`)

- `youtube-ids`: every YouTube video id is one YouTube could have given
  (11 letters, digits, - and _); one that is not links to no video.
- `youtube-dates`: every YouTube video has the date it was watched.
- `youtube-reviews`: every YouTube video has a rating and a review.
- `youtube-devices`: every YouTube video has the device it was watched on.

### People (`people`)

- `people-types`: every person has at least one person type.
- `people-names`: every first name and surname is one word (a surname of
  two words hyphenated, more names in the middle name). What
  `scripts/tidy_names.py` could not split is listed: mostly bands and
  descriptions kept whole in the first name.

### Organizations (`organizations`)

- `logos`: every SVG image follows the logo convention in `logos.md`
  (canvas, square viewBox, nothing active or external). The margin and
  centering are not checked: they need a renderer.
- `organization-logos`: every organization has a logo.
- `organization-relations`: every organization has at least one relation
  type.
- `organization-addresses`: every organization has an address.
- `organization-locations`: every organization has a latitude and a
  longitude, so it is on the map.

### Org types (`organization-types`)

- `organization-type-used`: every organization type, of every account,
  is used by at least one row; one used by nothing can go.
- `organization-type-descriptions`: every organization type, of every
  account, has a description, so its tooltip and page say what it means.
- `organization-type-duplicates`: no account has two organization types
  of the same name (ignoring case and spaces at the ends).

### Person types (`person-types`)

- `person-type-used`: every person type, of every account, is used by at
  least one row; one used by nothing can go.
- `person-type-descriptions`: every person type, of every account, has a
  description, so its tooltip and page say what it means.
- `person-type-duplicates`: no account has two person types of the same
  name (ignoring case and spaces at the ends).

### Relation types (`relation-types`)

- `relation-type-used`: every relation type, of every account, is used
  by at least one row; one used by nothing can go.
- `relation-type-descriptions`: every relation type, of every account,
  has a description, so its tooltip and page say what it means.
- `relation-type-duplicates`: no account has two relation types of the
  same name (ignoring case and spaces at the ends).

### Devices (`devices`)

- `device-used`: every device, of every account, is used by at least one
  row; one used by nothing can go.
- `device-descriptions`: every device, of every account, has a
  description, so its tooltip and page say what it means.
- `device-duplicates`: no account has two devices of the same name
  (ignoring case and spaces at the ends).

## Adding one

A check is one function in `src/myworld/checks.py`, from a database
session to a `Result` (how many things it looked at, and a `Problem` for
each thing wrong: what it is about, so a person can find it, and what is
wrong). Register it with `@check(name, title, noun, dataset)`, the
dataset a key of `DATASETS` (a new dataset is one more entry there); its
docstring is the description the page (as the title's tooltip) and
`--list` show. The Checks page, the dataset's page, the API
(`GET /api/checks[?dataset=book]`, `GET /api/checks/<name>`) and the
script pick it up with no other change. Give it a test in `tests/checks_test.py`.
