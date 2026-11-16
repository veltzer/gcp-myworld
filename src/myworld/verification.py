"""
The verification mail of email sign-up, with Google Identity Platform as
the mail sender (the same as gcp-machines).

Identity Platform is used for nothing but its verification mail: the
accounts themselves stay in our database. To have Google send the mail, an
Identity Platform user must exist for the address and the request must
carry that user's ID token, so sending

  1. deletes any earlier Identity Platform user for the address,
  2. creates one with a random password nobody keeps,
  3. signs in as it to get an ID token, and
  4. asks for the VERIFY_EMAIL mail, whose link opens Google's page on
     <project>.firebaseapp.com; that page offers a Continue button back to
     the continue URL, which carries our own secret token.

What proves the address is the token: it travels only inside the mail, so
whoever brings it back reads that mailbox. Once it is back, the Identity
Platform user has done its job and is deleted.

Every call uses the app's own Google credentials (the service account needs
roles/identitytoolkit.admin), so no API key is involved. Google does not let
the project change the mail's text or the page the link opens, so both are
Google's defaults.

Off Cloud Run there is no mail: LogMailer writes the link to the server log.
"""

import logging
import secrets
from typing import Any, Protocol

import google.auth
import google.auth.credentials
from google.auth.transport.requests import AuthorizedSession

API = "https://identitytoolkit.googleapis.com/v1"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
HTTP_TIMEOUT = 10

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    pass


class Mailer(Protocol):
    def send(self, email: str, continue_url: str) -> None:
        """ Mail the address a link that leads to continue_url. """

    def forget(self, email: str) -> None:
        """ The address is verified: drop whatever sending it needed. """


class IdentityPlatform:
    """ The verification mail, sent through Identity Platform. """

    def __init__(self, credentials: google.auth.credentials.Credentials, project_id: str) -> None:
        credentials = google.auth.credentials.with_scopes_if_required(credentials, SCOPES)
        self.session = AuthorizedSession(credentials)
        self.admin = f"{API}/projects/{project_id}"

    @classmethod
    def from_environment(cls) -> IdentityPlatform:
        credentials, project_id = google.auth.default()
        if not project_id:
            raise VerificationError("no Google Cloud project for Identity Platform")
        return cls(credentials, project_id)

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(url, json=body, timeout=HTTP_TIMEOUT)
        data: dict[str, Any] = response.json()
        if not response.ok:
            message = data.get("error", {}).get("message", response.reason)
            raise VerificationError(f"Identity Platform: {message}")
        return data

    def _lookup(self, email: str) -> dict[str, Any] | None:
        users: list[dict[str, Any]] = self._post(f"{self.admin}/accounts:lookup", {"email": [email]}).get("users", [])
        return users[0] if users else None

    def forget(self, email: str) -> None:
        user = self._lookup(email)
        if user is not None:
            self._post(f"{self.admin}/accounts:delete", {"localId": user["localId"]})

    def send(self, email: str, continue_url: str) -> None:
        self.forget(email)
        password = secrets.token_urlsafe(32)
        self._post(f"{self.admin}/accounts", {"email": email, "password": password})
        signed_in = self._post(f"{API}/accounts:signInWithPassword", {"email": email, "password": password, "returnSecureToken": True})
        self._post(f"{API}/accounts:sendOobCode", {"requestType": "VERIFY_EMAIL", "idToken": signed_in["idToken"], "continueUrl": continue_url})


class LogMailer:
    """ Local development: the link goes to the server log instead of a mailbox. """

    def send(self, email: str, continue_url: str) -> None:
        logger.warning("verification link for %s: %s", email, continue_url)

    def forget(self, email: str) -> None:
        pass
