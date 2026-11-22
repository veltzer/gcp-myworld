# Database checks

Rules the data should follow that the app does not enforce when it is
written: a logo inserted with SQL, a row an old version left behind. The
checks read the whole database, every account's rows, and change nothing.

## Running them

- **In the app:** the Checks page (sidebar, Overview, admins only; see
  `accounts.md`) lists the checks by dataset, a dataset for every page of
  data in the sidebar (Books, Concerts to Chess, People,
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

- `book-covers`: every book has at least one cover (it may have several).
- `book-links`: every book has a Goodreads or a Simania id, so its card
  links to its page.
- `book-authors`: every book has an author: one of the account's people,
  linked to it.
- `book-years`: every book has the year it came out.
- `book-original-languages`: every book says the language it was first
  written in.
- `book-original-titles`: every book that says the language it was first
  written in has a title in that language.
- `book-reads`: every book has at least one reading: where its status, its
  rating and its review are, with its day and its language.
- `book-languages`: every finished (Done) reading of a book says the
  language it was read in.
- `book-read-dates`: every finished (Done) reading of a book has the day it
  was finished.
- `book-titles`: every book has at least one title (its main title is not
  empty).
- `book-english-titles`: every book that has a title in Hebrew has one in
  English as well: the published one, or a translation of the Hebrew where
  the book never came out in English.
- `book-title-languages`: every title of a book, the main one and those in
  other languages, is written in the script of the language it says (a
  title in Hebrew letters is not English). The forms and the API refuse a
  title that is not; `scripts/fix_languages.py` repairs the ones kept
  before they did.
- `book-ratings`: every book read (Done) has a rating.
- `book-duplicates`: no account has two books of the same title and
  author.
- `book-notes`: no note of a book repeats what the book says elsewhere (the
  language it was written in, a name it once had that is its title told a
  little differently).
- `book-translations`: every book read was read at least once in the
  language it was written in. A book read only in translation is no
  mistake: this lists them, and whoever does not want the list turns it
  off.

### Concerts (`concerts`)

- `concert-dates`: every concert, of every account, has a date (a day, a
  month, a year or a full time).
- `concert-places`: every concert, of every account, points to the place
  it was at (the Places page); one seen on TV need not.
- `concert-performers`: every concert, of every account, has at least
  one performer: a person or a group.
- `concert-photos`: every concert, of every account, has a photo.
- `concert-duplicates`: no account has two concerts of the same name on
  the same date (ignoring case and spaces at the ends).
- `concert-company`: every concert has people in With or is marked "I went
  alone", and none is both.
- `concert-reviews`: every concert has a review.
- `concerts-credits`: every photo of a concert that has a credit says its
  source and its license (its author only when one is known).

### Museums (`museums`)

- `museum-visits`: every museum has at least one visit.
- `museum-dates`: every museum visit has a date (a day, a month, a year
  or a full time).
- `museum-addresses`: every museum has an address.
- `museum-locations`: every museum has a latitude and a longitude.
- `museum-company`: every museum visit has people in With or is marked
  "I went alone", and none is both.
- `museum-photos`: every museum has a photo.
- `museum-cities`: every museum says which city it is in.
- `museum-ratings`: every museum visit has a rating and a review.
- `museum-duplicates`: no account has two museums of the same name in the
  same city.
- `museum-near-city`: every museum on the map is within 50 km of its city.
- `museum-websites`: every museum's website is a web address.

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

### Your audio books (`audio-books-heard`)

- `audio-book-reviews`: every book in Your audio books that you finished
  a version of has your own rating and a review.

### Audio book listens (`audio-book-listens`)

- `audio-book-listen-progress`: every version you heard but did not
  finish says how far you got: how much was heard (Audible says), or in
  words ("did part03").

### Your podcasts (`podcasts-heard`)

- `podcast-reviews`: every podcast in Your podcasts (one you heard an
  episode of) has your own rating and a review.

### Episodes heard (`episodes-heard`)

- `episode-heard-dates`: every episode heard has the date it was heard.

### Film watches (`film-watches`)

- `film-watch-dates`: every film watched says when.
- `film-watch-reviews`: every film watched has the user's rating and
  review.

### YouTube (`youtube`)

- `youtube-ids`: every YouTube video id is one YouTube could have given
  (11 letters, digits, - and _); one that is not links to no video.
- `youtube-dates`: every YouTube video has the date it was watched.
- `youtube-reviews`: every YouTube video has a rating and a review.
- `youtube-devices`: every YouTube video has the device it was watched on.

### Chess (`chess`)

- `chess-dates`: every chess game with its text has the date it was
  played; one recorded without its moves need not.
- `chess-players`: every chess game names its two players, and they are
  not the same name; one recorded without its sides names the opponent.
- `chess-positions`: every chess game with moves says where its pieces
  stood when it ended, as eight ranks of pieces; one added while the page
  could not play its moves has none. A game with no move (none made, or
  none recorded) has no position to show and is not asked for one.

### Groups (`groups`)

- `group-members`: every group has at least one member (a person).
- `group-used`: every group performed at at least one concert.
- `group-duplicates`: no account has two groups of the same name
  (ignoring case and spaces).
- `groups-credits`: every photo of a group that has a credit says its
  source and its license (its author only when one is known).
- `group-websites`: every group's website is a web address.

### Places (`places`)

- `place-used`: every place has at least one concert that was there.
- `place-cities`: every place says which city it is in.
- `place-locations`: every place has a latitude and a longitude, so the
  Map layout shows it.
- `place-duplicates`: no account has two places of the same name in the
  same city (ignoring case and spaces).
- `place-addresses`: every place has a street or a district.
- `place-photos`: every place has a photo.
- `place-exact-locations`: no place's remark says its location is
  approximate.
- `place-near-city`: every place on the map is within 50 km of its city.
- `place-websites`: every place's website is a web address.
- `places-credits`: every photo of a place that has a credit says its
  source and its license (its author only when one is known).

### Podcasts (`podcasts`, shared)

- `podcast-covers`: every podcast has a cover.
- `podcast-feeds`: every podcast has its RSS feed, which the Podcast feeds
  importer brings its episodes from.

### Podcast episodes (`podcast-episodes`, shared)

- `podcast-episode-guids`: every episode has its id in the feed (guid): one
  typed in without it is not found in the feed again.

### Audio books (`audio-books`, shared)

- `audio-book-authors`: every audio book says who wrote it.
- `audio-book-duplicates`: no two audio books have the same title and
  subtitle: one book's versions belong together.

### Audio book versions (`audio-book-versions`, shared)

- `audio-book-covers`: every version has its cover: an Audible one
  Audible's, MP3 files a print edition's.
- `audio-book-version-asins`: every Audible version has its ASIN, which the
  Audible library importer finds it again by and its page is linked by.

### Films (`films`, shared)

- `film-posters`: every film has its poster.
- `film-imdb-ids`: every film has its IMDb id, which the importers find it
  again by and its page is linked by.
- `film-years`: every film says the year it came out.

### Cities (`cities`)

- `city-used`: every city has a place, a museum visit or an organization
  in it.
- `city-countries`: every city says which country it is in.
- `city-locations`: every city has a latitude and a longitude.
- `city-photos`: every city has a photo.
- `city-duplicates`: no account has one city twice, however spaced,
  hyphenated or capitalized ("Tel-Aviv", "Tel Aviv").
- `city-regions`: the cities of a country either all say their region or
  none does.
- `cities-credits`: every photo of a city that has a credit says its
  source and its license (its author only when one is known).

### Countries (`countries`)

- `country-used`: every country has a city in it.
- `country-locations`: every country has a latitude and a longitude.
- `country-flags`: every country has its flag.
- `country-duplicates`: no account has one country twice, however it is
  written ("USA", "United States of America").
- `countries-credits`: every flag of a country that has a credit says its
  source and its license (its author only when one is known).

### People (`people`)

- `people-known`: every person has a profession, a relation to another
  person, or an organization.
- `people-names`: every honorific, first name and surname is one word (a
  surname of two words hyphenated, more names in the middle name). What
  `scripts/tidy_names.py` could not split is listed: mostly bands and
  descriptions kept whole in the first name.
- `people-english-names`: every person has an English name: the name
  parts, written in Latin letters. Someone whose name is not known has
  none, and then has a description to be known by.
- `people-hebrew-names`: every person who wrote a book that has a Hebrew
  title has a name in Hebrew among their names, the one the book is shown
  with in Hebrew.
- `people-name-languages`: every name in another language is written in the
  script of that language; `scripts/fix_languages.py` repairs those too.
- `people-photos`: every person with a profession has a photo.
- `people-duplicates`: no account has two people of the same name.
- `people-used`: every person is linked to something: a concert, a museum
  visit, a book, a course, a group, an organization or another person.
- `people-credits`: every photo of a person that has a credit says its
  source and its license (its author only when one is known).

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
- `organization-cities`: every organization says which city it is in.
- `organization-duplicates`: no account has two organizations of the same
  name.
- `organization-near-city`: every organization on the map is within 50 km
  of its city.
- `organization-websites`: every organization's website is a web address.

### Org types (`organization-types`)

- `organization-type-used`: every organization type, of every account,
  is used by at least one row; one used by nothing can go.
- `organization-type-descriptions`: every organization type, of every
  account, has a description, so its tooltip and page say what it means.
- `organization-type-duplicates`: no account has two organization types
  of the same name (ignoring case and spaces at the ends).

### Professions (`person-types`)

- `person-type-used`: every profession, of every account, is someone's;
  one nobody has can go.
- `person-type-descriptions`: every profession, of every account, has a
  description, so its tooltip and page say what it means.
- `person-type-duplicates`: no account has two professions of the same
  name (ignoring case and spaces at the ends).
- `person-type-photos`: every profession, of every account, has a photo
  (`scripts/fetch_pictures.py --only professions` takes Wikipedia's).
- `person-types-credits`: every photo of a profession that has a credit says its
  source and its license (its author only when one is known).

### Org relation types (`relation-types`)

- `relation-type-used`: every relation type, of every account, is used
  by at least one row; one used by nothing can go.
- `relation-type-descriptions`: every relation type, of every account,
  has a description, so its tooltip and page say what it means.
- `relation-type-duplicates`: no account has two relation types of the
  same name (ignoring case and spaces at the ends).

### Person relation types (`person-relation-types`)

- `person-relation-type-used`: every person relation type, of every
  account, is used by at least one relation; one used by nothing can go.
- `person-relation-type-descriptions`: every person relation type, of
  every account, has a description.
- `person-relation-type-duplicates`: no account has two person relation
  types of the same name (ignoring case and spaces at the ends).

### Devices (`devices`)

- `device-used`: every device, of every account, is used by at least one
  row; one used by nothing can go.
- `device-descriptions`: every device, of every account, has a
  description, so its tooltip and page say what it means.
- `device-duplicates`: no account has two devices of the same name
  (ignoring case and spaces at the ends).
- `device-photos`: every device, of every account, has a photo
  (`scripts/fetch_pictures.py --only devices` takes Wikipedia's).
- `devices-credits`: every photo of a device that has a credit says its
  source and its license (its author only when one is known).

### Languages (`locales`)

- `locale-native-names`: every language says what it is called in itself,
  in its own script: its picture is that name, written out.
- `locale-scripts`: every language of the locales table names the script it
  is written in as Unicode names it (Latin, Hebrew, Cyrillic): a title or a
  name is told to be in a language by its letters.

## Adding one

A check is one function in the module of its page in
`src/myworld/checks/` (`concerts.py`, `library.py`, ...), from a database
session to a `Result` (how many things it looked at, and a `Problem` for
each thing wrong: what it is about, so a person can find it, and what is
wrong). Read the rows with `rows(session, Model)` and tell what is wrong
with one with `problem(row, message)`, both in `core.py`, which also has
`twice()` for what is listed twice. Register it with `@check(name, title, noun, dataset)`, the
dataset a key of `DATASETS` (a new dataset is one more entry there); its
docstring is the description the page (as the title's tooltip) and
`--list` show. The Checks page, the dataset's page, the API
(`GET /api/checks[?dataset=book]`, `GET /api/checks/<name>`) and the
script pick it up with no other change. Give it a test in `tests/checks_test.py`.
