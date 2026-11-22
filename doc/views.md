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
- concerts, museum visits, audio courses, your audio books, audio book listens, your podcasts, episodes heard, YouTube videos, chess games
- people, groups, organizations (with their types, for the type filter)

The shared data (places, podcasts, cities, countries, ...) is everyone's and is not a
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
| `.../data/images/<id>?sig=...`                    | an image a row of the view shows, by the signed address the view gave it |

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
- Images: a visitor gets an image only by the address the view put in the
  rows it sent, which carries a signature (`?sig=`): an HMAC, under the
  app's secret key, of the view, the data sets it shows and the image id.
  Trying other ids gets nothing, though ids are sequential. Taking a data
  set out of the view (or deleting the view) makes the addresses it gave
  stop working; putting it back makes them work again. Whoever copied an
  address keeps that one image while the view still shows it, as with
  anything shown in public. Changing the secret key changes every address.
- Search engines: the page is a script, nothing is indexed today; a
  `noindex` choice per view is cheap to add.
- Logging: who opens a view is not recorded beyond the request log.

## Private views (designed, not built)

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

Chosen: 4 first (1 may follow). How to build it:

### Implementing private views: a list of usernames

**The data.** `shared_views.access` gets a second value, `users`
(`VIEW_ACCESS_USERS` beside `VIEW_ACCESS_PUBLIC`). A new table holds who may
open such a view:

    shared_view_members(view_id  -> shared_views.id, on delete cascade,
                        user_id  -> users.id,        on delete cascade,
                        primary key (view_id, user_id))

with an index on `user_id` (for "shared with me"). Members are kept by user
id, not by username, so a member who changes their username stays a member,
and a deleted account drops out by itself. Migration 0019 adds the table
(adds: migrate, then deploy). Switching a view back to `public` keeps its
members, so switching again restores them.

**The owner's API.** The body of `POST`/`PUT /api/shared-views` takes
`access` (`public` or `users`) and `members`, a list of usernames, which
replaces the view's list. `_apply` checks them: each must be an account's
username (400 `members: no such user: ...` otherwise; the same answer for
every unknown name), the owner's own is dropped (the owner always sees
their views), duplicates are dropped. `view_json` carries `members` (the
usernames, sorted) in the owner's answers only, never in a visitor's.

**Who may open it.** `_visited` decides, after finding the view:

| Visitor                          | A public view | A `users` view           |
|----------------------------------|---------------|--------------------------|
| not signed in                    | sees it       | is asked to sign in      |
| signed in, the owner             | sees it       | sees it                  |
| signed in, a member              | sees it       | sees it                  |
| signed in, anyone else           | sees it       | 404 "no such view"       |

The visitor's account is `auth.current_user()` (the session; these routes
are not `login_required`). It must be read *before* `api_visit_data` sets
`flask.g.user` to the owner; keep it as `flask.g.visitor`, so nothing later
in the request mistakes the owner for the visitor.

Not signed in: so that the answer does not tell whether a private view
exists, every address that is not a public view (a private one, or none at
all) gets the same answer, 401 `sign in to see this view` from the API and
from the page a page saying so with a Sign in link. Signed in and not a
member: 404, as for a view that does not exist.

**Signing in and coming back.** Sign-in today always lands on the library
(`/auth/login`, `email_login` and `email_password` answer
`url_for("views.library")`, the OAuth callback redirects there). It needs a
return address: the sign-in link carries `?next=/view/<u>/<v>`, the login
page keeps it in the session (`flask.session["next"]`) across the OAuth
round trip, and every way of signing in ends there. Only a local path is
taken (`next` must start with `/` and not `//`), so the link cannot send
anyone to another site.

**Images.** An image of a private view is checked as now (the signature),
and `_visited` runs first, so its address works only for those who may open
the view: copying it to someone else gives them nothing. The signature
need not change.

**Caching.** A private view's page and every answer of its API carry
`Cache-Control: private, no-store` (a public one keeps `no-cache`), so no
shared cache keeps a member's copy for someone else.

**The page.**

- The view dialog gets *Who may see it*: two radio buttons, *Anyone with the
  address* and *Only these users*, and under the second a usernames field.
  The field is a Tom Select in create mode with no suggestions: the owner
  types the usernames they were told, each checked on Save. There is
  deliberately no search over all usernames, which would be a directory of
  every account for anyone signed in.
- The Views table gets a *Who* column: "Anyone" or the members' usernames.
- The Views page gets a second table, *Shared with me*: the private views
  others made that list the user (`GET /api/shared-views/shared-with-me`:
  owner's username, name, title, address). Public views are not listed
  there; the user would not know of them otherwise either.
- In visitor mode the 401 for the page's configuration shows the sign-in page described above
  (the page's API calls do not redirect on a 401 when visiting, which stays
  so; the page catches it). A member sees the view as anyone sees a public one, with
  "shared with you" in the banner; the owner sees it the same way.

**Tests** (`tests/sharing_test.py`):

- making a private view; members by username, case-insensitive; an unknown
  username is 400; the owner's own name is ignored; PUT replaces the list;
- no one signed in: 401 for a private view and for one that does not exist
  alike, for the page's configuration, its data and its images;
- a member reads it (data and images); another account gets 404; the owner
  reads it;
- a member who changes their username is still a member; a deleted member
  account is gone from the list;
- taking a member off: their next request is 404;
- switching to public and back keeps the members;
- `shared-with-me` lists the private views that name the user, only;
- sign-in with `next` comes back to the view; a `next` of
  `https://elsewhere` or `//elsewhere` lands on the library.

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
