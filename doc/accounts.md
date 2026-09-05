# Accounts and sign-in identities

How the app decides which user a sign-in belongs to, why it works that
way today, and the design to move to if accounts should ever be merged.

## Current behavior: every sign-in method is its own account

A user row is keyed by a provider-qualified subject in `users.google_sub`
(the column name predates the other providers; see `src/myworld/auth.py`
and `User` in `src/myworld/models.py`):

| Method             | Subject                     | Email is       |
|--------------------|-----------------------------|----------------|
| Google             | the Google `sub` claim      | verified       |
| GitHub             | `github:<github user id>`   | verified       |
| Email and password | `email:<address>`           | not verified   |
| Development login  | `dev:<address>`             | not verified   |

Every lookup is by subject, never by email. The email column is stored
for display and refreshed on every login. So signing in with Google, then
with GitHub, then with the password form, all with the same address, gives
three accounts with three separate libraries. Nothing is lost: each
library comes back when signing in the way it was created.

The reasons this was chosen, and still hold:

- Email addresses change and get reassigned, so they are unsafe as the key
  for third-party sign-in. Matching on subject survives an address change
  at the provider.
- The password form does not verify the address. If accounts were merged
  by email, anyone could register your address with a password and inherit
  your Google-created library, or register it first and have your later
  Google login land in their account (an account takeover set up before the victim ever signs up).
- Keeping identities apart needs no extra infrastructure: no outgoing
  mail, no verification tokens, no linking page.

The cost is that a user who forgets which button they used sees an empty
library, with no hint that another account holds their data. The app
creates the second account silently, which is the least common choice
among sites.

## What most sites do

Most sites merge, but not blindly. The common pattern has three parts:

1. A verified email from a trusted provider (Google, GitHub, ...) links a
   new login to an existing account with that address automatically. This
   is what Firebase Authentication, Auth0, Clerk and Supabase default to or
   offer as the standard setting.
1. Password accounts never merge on their own, because a password sign-up
   proves nothing about the address. Sites either verify the address with
   a mail link at registration, after which it counts as verified, or keep
   the password account separate until the user links it.
1. A "connected accounts" page lets a signed-in user attach another
   provider or set a password. Linking from a live session proves control
   of both sides and covers every case the automatic rule leaves out.

Two structural habits go with this: one user row with many identity rows
(provider plus provider subject), and the email treated as data rather
than as the key. Matching by verified email happens once, at first login;
from then on the identity is found by subject.

## Design for merging, if and when wanted

Merge Google and GitHub by verified email, keep password accounts separate
until linked from inside a session, and leave email verification out.

1. **Split identities out of the user row.** A new `identities` table:
   `user_id`, `provider`, `subject`, `email`, `verified`, unique on
   `(provider, subject)`. `users.google_sub` goes away; `users.email` and
   `users.name` stay as display values. `scripts/migrate.sh` turns each
   existing user row into one identity.
1. **Google and GitHub link automatically.** On a login whose subject is
   unknown, look for a user who has a *verified* identity with the same
   email. Attach the new identity to that user if found, otherwise create a
   user. Both providers assert verified addresses; the GitHub code already
   takes only the verified primary email.
1. **Password accounts do not auto-link in either direction.** A
   registration on an address that a verified identity already owns is
   refused with a message to sign in with that provider (the endpoint
   already refuses duplicate addresses, so this reveals nothing new). A
   Google or GitHub login never attaches to a password-only account.
1. **A "Connected accounts" section on a settings page.** While signed
   in: add Google, add GitHub, set a password. The OAuth start routes get a
   `link` mode that, on callback, attaches the identity to the current
   user instead of signing in, refusing if the subject already belongs to
   another user. Setting a password from a Google session is how a Google
   account gains an email login.
1. **Email verification stays out.** It needs an outgoing mail provider,
   templates and token handling; the linking page makes it unnecessary for
   correctness. Add it later only if the password path should merge
   automatically too, at which point a verified password identity joins
   rule 2.

Migration of existing data is small: every current row becomes one
identity, and duplicate accounts of the same person are merged by hand
once, by moving `user_works.user_id` and deleting the spare user.

Roughly a day of work: models and migration, the linking rule in the two
OAuth paths, the settings page with its three link actions, and tests for
each merge and refusal case.

Decision (2026-09-05): keep all accounts separate for now.
