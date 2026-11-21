# Views: showing your data to others

A *view* is a named selection of a user's own data that anyone can open at

    https://myworld.stream/view/<username>/<viewname>

without an account. A user may have any number of views (a "music" view
with the concerts and the groups, a "reading" view with the books, a
"chess" view with the games), and creates, changes and deletes them on the
Views page (sidebar, Overview). This is why accounts got usernames.

Status: a first implementation is live (public views only); the rest of
this document is the design it starts, and the questions still open.

## What a view is

| Field         | What                                                                 |
|---------------|----------------------------------------------------------------------|
| `name`        | the last part of its address: 1 to 60 lowercase letters, digits, `.`, `-`, `_`, starting with a letter or digit; unique among the owner's views |
| `title`       | what the page says it is ("Mark's concerts"); the name when empty    |
| `description` | a line or two shown above it                                         |
| `datasets`    | which of the owner's data sets it shows (below)                      |
| `access`      | `public` (anyone with the address); later `private` (see below)      |

It is a row of `shared_views` (migration 0018), owned by its user, deleted
with them. Renaming a view changes its address: the old one stops working
(see *Open questions*).

### Data sets

A view shows only the owner's *own* data, and of that only what it enables:

- the library kinds: books, films, ... (`/api/library-entries?kind=...`)
- concerts, museum visits, audio courses, YouTube videos, chess games
- people, groups, organizations (with their types, for the type filter)

The shared data (places, cities, countries, ...) is everyone's and is not a
data set of a view. The cards of a view still name the places, cities and
people their rows point to; such a link leads nowhere unless that data set is
part of the view too (the visitor is told it is not).

Not data sets of a view, ever: the account itself (email, logins, settings),
import runs and their logs, the stats page, the admin pages.

## How it is shown

The view's address serves the same page as the library, in *visitor
mode*, so a view has everything a page of the library has: the List, Cards,
Tiles, Gallery and Map layouts, search, sort, the type filter, paging, the
chess board. In visitor mode:

- the sidebar lists the view's data sets only, under its title;
- the top bar shows whose view it is, and a link to sign in to My World;
- nothing can be changed: the Add button is disabled, a card opens no edit
  dialog, and the page never sends anything but GETs;
- every API call the page makes goes to the view's own endpoints instead
  (`/api/views/<username>/<viewname>/...`); the page itself is unchanged
  otherwise.

### The API

Owner's (signed in):

| Call                              | What                                          |
|-----------------------------------|-----------------------------------------------|
| `GET /api/shared-views`           | your views, and the data sets a view can show |
| `POST /api/shared-views`          | a new view (you need a username first)        |
| `PUT /api/shared-views/<id>`      | change one                                    |
| `DELETE /api/shared-views/<id>`   | delete one (its address stops working)        |

Visitor's (no sign-in needed):

| Call                                              | What                                         |
|---------------------------------------------------|----------------------------------------------|
| `GET /view/<username>/<viewname>`                 | the page                                     |
| `GET /api/views/<username>/<viewname>`            | the page's configuration: the vocabularies, whose view it is, its data sets |
| `GET /api/views/<username>/<viewname>/data/<api>` | `GET /api/<api>` answered as the owner would see it, if `<api>` belongs to a data set the view enables; 404 otherwise |
| `.../data/images/<id>`                            | an image of the owner's (or a shared one)    |

The data endpoint does not have endpoints of its own: it finds the library
endpoint `<api>` names and runs it as the owner, read only, after checking it
against a fixed list of what each data set may read (`sharing.READS`). An
endpoint not on the list is never reached through a view, so a new endpoint is
private until it is added there.

## Privacy

- A view is public: whoever has the address sees what it enables. The page
  says so where views are made.
- A view's rows are the JSON the owner's own page gets. Fields the owner
  would not want shown (a remark, who they were with, a review) are shown
  too. See *Open questions*: per-field choices.
- Images: a visitor may fetch any image of the owner's by its id, not only
  those the view's rows show. Ids are sequential, so this should be narrowed
  to the images of the enabled data sets before views are advertised.
- Search engines: the page is a script, nothing is indexed today; a
  `noindex` choice per view is cheap to add.
- Logging: who opens a view is not recorded beyond the request log.

## Private views (not built)

Options, roughly from simplest to richest:

1. **A secret link.** The view's address carries an unguessable token
   (`/view/veltzer/music?key=...`); whoever has the link sees it, and making
   a new token revokes the old. No accounts, no passwords. Weakest, but it
   is what most sites call "anyone with the link".
2. **A password per view.** One password, typed once per browser, kept in a
   cookie. Simple to give out, impossible to revoke for one person only.
3. **A list of users and passwords per view** (what was first suggested).
   Each visitor gets a name and a password the owner made for them; one can
   be taken away. But the owner then manages passwords for others, and the
   passwords must be stored hashed (as the email logins are), never shown
   again, and reset by the owner.
4. **A list of My World usernames.** The view is visible to the accounts
   named, signed in as themselves; no new passwords exist, revoking is
   removing a name, and the sign-in (Google, GitHub, email) is the one
   already there. Needs visitors to have accounts.

Suggestion: 4, with 1 as the way to show a view to someone without an
account. Both fit `access` (`public`, `link`, `users`) and a small
`shared_view_members` table; 3 adds a password store and its upkeep for
little over 4.

## Open questions

- **Renaming:** keep the old name as a redirect, or let it go?
- **Per-field choices:** hide reviews, remarks, companions per view?
- **Filters:** a view of only some rows (the concerts of 2024, the books
  rated 8 and up), not whole data sets?
- **A user's page:** `/view/<username>` listing their public views?
- **Links between views:** a person card in a "music" view linking to a
  "people" view of the same owner?
- **Counts and stats** for a view (the sidebar counts appear as each data
  set is opened, today).
- **Rate limits** on the visitor endpoints, which need no sign-in.
