# Ideas for a more flexible data model

Suggestions only: nothing here is built. Each names what is rigid today,
what would replace it, and what it costs.

## Recommended order

Do 1 first, since it makes every later change safer, then 2 and 3: those
two remove the most special cases and fix things already run into. The rest
are worth doing only when the specific pain is felt.

## 1. Versioned migrations instead of the hand-written script

- **Today:** `scripts/migrate.sh` guesses what to do by looking at which
  columns exist, in two dialects. That guessing broke once: an old step
  tried to run again after the original-language column was added.
- **Proposal:** Alembic, with a version table. Each change is one numbered
  step that runs once.
- **Cost:** about half a day, no data change. The old script stays for
  history.

## 2. One pictures table for everything

- **Today:** there are six shapes:
  - a single photo with a credit (places, groups, countries);
  - a single photo without a credit (museums, organizations);
  - concerts with their own credit columns;
  - three separate "many photos" tables for books, cities and people.
- **Proposal:** one table: what it belongs to, the image, its position and
  its credit. Everything can then have several pictures with a default, and
  the credit is stored once per image.
- **Cost:** a data migration of about 1,000 images and a rewrite of the
  picture code, which gets shorter. Medium.

## 3. Editions of a book

- **Today:** a book has titles per language, "owned in" per language,
  readings per language, one ISBN "of the edition read", and the publisher
  still sits in the notes. These are all facts about an edition with no
  place to live.
- **Proposal:** an editions table under each book: language, title,
  publisher, year, ISBN, translator. A reading and an owned copy point at
  an edition.
- **Cost:** the largest change to books; the dialog gains an Editions box.
  It would absorb the remaining "Publisher: ..." notes.

## 4. Roles between people and works

- **Today:** a book has authors as people and also a text copy of their
  names (`creator`), which is part of the book's identity. Films keep the
  director as text only.
- **Proposal:** one link table of work, person and role (author,
  translator, director, actor); drop the text copy.
- **Cost:** medium. It also changes how a duplicate book is detected, so
  that would move to the ISBN or the catalog ids.

## 5. One kind of "place" for everything with an address

- **Today:** places, museums and organizations each carry their own city,
  street, map pin, website and photo, with three sets of the same checks.
- **Proposal:** a museum and an organization's office become a place with a
  kind. Visits and concerts both point at places.
- **Cost:** large, and it touches the three biggest pages. The benefit is
  mostly less code; little would look different.

## 6. Names in other languages for everything

- **Today:** only people and books have names per language. Cities,
  countries, places, museums, organizations and groups have one English
  name: Heichal HaTarbut and Tzavta have no Hebrew name.
- **Proposal:** one translations table of what, language and name, used by
  all of them. People and book titles could move onto it later.
- **Cost:** small to add, medium if people and books are moved too.

## 7. Partial dates everywhere

- **Today:** concerts and museum visits can say "2003" or "July 2003", but
  a book reading takes a full day or nothing. Most readings say "date
  unknown", though the year is likely known for many.
- **Proposal:** one partial-date type used by every date field, including
  the day a reading was started and finished.
- **Cost:** small to medium.

## 8. One table for the small lists, and real lists where there is free text

- **Today:** professions, organization types, three kinds of relation types
  and devices are six near-identical tables. Concert genre, organization
  status and YouTube category are free text.
- **Proposal:** one "terms" table with a vocabulary name; genre and status
  become vocabularies.
- **Cost:** medium, mostly mechanical.

## 9. Relations with dates, in one table

- **Today:** person to person, person to organization and organization to
  the user are three separate mechanisms, and none can say when ("worked at
  Amdocs 2001-2005").
- **Proposal:** one links table: who, relation, to whom or what, from,
  until.
- **Cost:** medium.

## 10. Fields for what the remarks keep collecting

- **Today:** "Location approximate", "closed in 2001" and "(now closed)"
  live in remarks and names.
- **Proposal:** real fields (how exact the pin is, the years it opened and
  closed) plus free tags on anything.
- **Cost:** small. This is the cheapest visible win, and it would let the
  23 "Location approximate." remarks be cleared properly.
