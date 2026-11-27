# Accounts and sign-in

How the app decides which account a sign-in belongs to: one person, one
account, however they sign in, and only with an email that is proven.

## One person, many ways in

A user (`users`) is a person, one row per email, and owns the data. Each
way they sign in is a login (`logins`), keyed by a provider-qualified
subject (see `src/myworld/auth.py` and `User` and `Login` in
`src/myworld/models.py`):

| Method             | Subject                   | The email is proven by                                       |
| ------------------ | ------------------------- | ------------------------------------------------------------ |
| Google             | `google:<sub claim>`      | Google's `email_verified`                                    |
| GitHub             | `github:<github user id>` | GitHub's verified primary address                            |
| Email and password | `email:<address>`         | the mailed link, followed                                    |
| Development login  | `dev:<address>`           | nothing: only with `MYWORLD_DEV_LOGIN=1`, never on Cloud Run |

A login is found by its subject, never by email, so it survives an address
change at the provider. A login that is new joins the user of its email, or
makes that user, so signing in with Google, then GitHub, then a password,
all with the same address, reaches one account and one library, and the
account panel lists the three ways.

Only a proven email gets an account. A provider that does not vouch for
the address (Google without `email_verified`, GitHub with no verified
primary address) sends the person back to the sign-in page saying so, and
nothing is stored. An address merely typed into a form proves nothing: were
it joined to the account of that address, anyone could walk into it, and
were it an account of its own it would be a second account of one email.
So email sign-up takes only the address and mails it a link (Identity
Platform sends it: `src/myworld/verification.py`); the page the link opens
is where its reader chooses the password. Whoever reads the mailbox is the
only one who ever sets a password for the address, and until the link is
followed the address can sign in to nothing. A link works once and for a
day, a new one voids the old, and the same link replaces a forgotten
password. `deploy.md` has the details and the one-time Identity Platform
setup.

## Roles: users and admins

Every account has a role in `users.role`: `user`, which every new account
gets, or `admin`. Sign-in is the app's own code (`src/myworld/auth.py`,
no framework), and so is this: `auth.admin_required` guards what only an
admin may do, reading the role from the database on every request, so a
change takes effect at once, without signing out.

An admin opens the Users page (sidebar; disabled for everyone else),
which lists every account, and can make any account an admin, which is
how the role is delegated, or turn an admin back into a user. The last
admin cannot be demoted (409), so the site always has one. The role
belongs to the account, which is the person: whichever way they sign in,
they are the same admin.

The first admin comes from `scripts/migrate.sh`: when no account is an
admin, it makes the oldest account one. In production that is the site
owner's account (user 1). On a fresh local database, sign in once and run
`scripts/migrate.sh --local`.
