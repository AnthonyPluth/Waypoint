"""Connecting a member's Gmail, read-only: the one module that talks to Google's mail and OAuth services.

Sign-in with Google's OAuth (authorization code with PKCE, offline access) for the `gmail.readonly` scope and nothing
else. What Waypoint keeps is the refresh token, encrypted with secretbox (the one place it's decrypted is here, to
refresh or revoke it), the address it belongs to and where a scan left off; an access token lives only for the call that
needs it. Nothing here logs or raises a token, a code or what Google said: the messages are fixed texts, safe to show.

Configuration (environment variables): GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, from the OAuth client the household
made in its own Google Cloud project (docs/src/content/docs/start/gmail.md). The client's redirect URI is
<WAYPOINT_PUBLIC_URL>/api/mailboxes/callback.

A connection belongs to the member who made it and ends when they can no longer sign in (oidc.access_lapsed), checked
before every use (access_token) and by a sweep (end_lapsed), so a connection nothing uses ends too.

Scanning (waypoint/domain/mail/scan.py) reads through the calls at the end of this module: a search that Gmail answers
with message ids only (so mail that doesn't match is never downloaded), what was added since a history id, and one message
by id. A message comes back as Google gave it, untouched: nothing here looks inside it (only domain/mail/extract.py does,
Semgrep's `waypoint-message-body`), and nothing here logs or raises what Google said.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update

from .. import oidc, tls
from ..storage import db, secretbox
from ..storage.models import Mailbox, MailboxPending, User

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
PENDING_TTL = 600           # seconds to finish at Google
MAX_PENDING = 1000          # unfinished connections kept at once (the oldest go first)
TIMEOUT = 15

CONNECTED, RECONNECT, FAILING = "connected", "reconnect", "error"   # a mailbox's status


@dataclass(frozen=True)
class Hosts:
    """Google's addresses. Tests point them at a fake Google (and allow its plain http)."""
    auth: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token: str = "https://oauth2.googleapis.com/token"
    revoke: str = "https://oauth2.googleapis.com/revoke"
    api: str = "https://gmail.googleapis.com/gmail/v1/users/me"
    allow_http: bool = False


HOSTS = Hosts()


class GmailError(Exception):
    """Something went wrong talking to Google; the message is fixed text, fit to show the person."""


class NotConfigured(GmailError):
    pass


class Declined(GmailError):
    """The person said no at Google's consent screen."""


class Refused(GmailError):
    """The return from Google didn't match a connection this person started (forged, repeated or too late)."""


class WrongScope(GmailError):
    """Google's grant doesn't include read access to the mailbox (a box was unticked), or was broader than asked."""


class Reconnect(GmailError):
    """Google no longer honours the connection (access removed, the grant expired): the person connects again."""


class Lapsed(GmailError):
    """The connection's owner can no longer sign in, so the connection was ended."""


class MessageGone(GmailError):
    """A message the search found has been deleted since."""


class HistoryExpired(GmailError):
    """Google no longer keeps history from the id a mailbox's last scan ended at (it keeps about a week)."""


# ------------------------------------------------------------------------------------------------ configuration

def credentials() -> tuple[str, str] | None:
    cid, secret = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip(), os.environ.get("GOOGLE_CLIENT_SECRET") or ""
    return (cid, secret) if cid and secret else None


def configured() -> bool:
    return credentials() is not None


def _credentials() -> tuple[str, str]:
    c = credentials()
    if not c:
        raise NotConfigured("Gmail isn’t set up: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET aren’t set.")
    return c


# ------------------------------------------------------------------------------------------------ talking to Google

def _open(req: urllib.request.Request) -> Any:
    """The JSON Google answered, or an urllib error (HTTPError for a refusal, URLError / OSError when it's unreachable)."""
    with tls.urlopen(req, timeout=TIMEOUT, allow_http=HOSTS.allow_http) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else {}


def _post(url: str, form: dict[str, str]) -> Any:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": "Waypoint/0.1"})
    return _open(req)


def _get(url: str, access_token: str) -> Any:
    return _open(urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "Waypoint/0.1"}))


def _refused_grant(e: urllib.error.HTTPError) -> bool:
    """Whether Google's refusal says the grant itself is gone (invalid_grant), rather than that it couldn't help now."""
    try:
        said = json.loads(e.read().decode())
    except (ValueError, OSError):
        return False
    return isinstance(said, dict) and said.get("error") == "invalid_grant"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ------------------------------------------------------------------------------------------------ connecting

def start(conn: db.Connection, owner: str, redirect_uri: str, now: float | None = None) -> str:
    """Where to send the browser to connect a Gmail for `owner`: Google's consent screen for read-only access, with this
    connection's state and PKCE challenge. Raises NotConfigured."""
    client_id, _secret = _credentials()
    now = time.time() if now is None else now
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    conn.execute(delete(MailboxPending).where(MailboxPending.created < now - PENDING_TTL))
    conn.execute(delete(MailboxPending).where(MailboxPending.state.in_(
        select(MailboxPending.state).order_by(MailboxPending.created.desc()).offset(MAX_PENDING - 1))))
    db.insert_ignore(conn, MailboxPending, {"state": state, "owner_sub": owner, "verifier": verifier, "created": now})
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": SCOPE,
              "access_type": "offline", "prompt": "consent select_account", "state": state,
              "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
    return HOSTS.auth + "?" + urllib.parse.urlencode(params)


def finish(conn: db.Connection, owner: str, params: dict[str, str], redirect_uri: str, now: float | None = None) -> str:
    """Handle Google's return for `owner`: trade the code for a refresh token and keep it, encrypted, with the address it
    belongs to. Returns that address. Raises Declined, Refused, WrongScope, NotConfigured or GmailError."""
    now = time.time() if now is None else now
    state = params.get("state") or ""
    row = conn.execute(select(MailboxPending.owner_sub, MailboxPending.verifier, MailboxPending.created)
                       .where(MailboxPending.state == state)).fetchone() if state else None
    if row:   # one try per connection, whatever comes of it
        conn.execute(delete(MailboxPending).where(MailboxPending.state == state))
    conn.commit()   # nothing held while we talk to Google
    if not row or now - row["created"] > PENDING_TTL or not secrets.compare_digest(str(row["owner_sub"]), owner):
        raise Refused("This connection didn’t start here, or took too long.")
    if params.get("error"):
        raise Declined("Google didn’t connect the mailbox.")
    code = params.get("code") or ""
    if not code:
        raise Refused("Google’s answer was missing its code.")
    client_id, client_secret = _credentials()
    try:
        tokens = _post(HOSTS.token, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                     "code_verifier": row["verifier"], "client_id": client_id, "client_secret": client_secret})
    except (urllib.error.URLError, OSError, ValueError) as e:   # (HTTPError is a URLError)
        raise GmailError("Google refused the connection, or couldn’t be reached.") from e
    refresh, access = tokens.get("refresh_token"), tokens.get("access_token")
    if not isinstance(access, str) or not access:
        raise GmailError("Google didn’t return access.")
    if not isinstance(refresh, str) or not refresh:
        _revoke_quietly(access)
        raise GmailError("Google didn’t grant lasting access. Remove Waypoint at myaccount.google.com/permissions and connect again.")
    if SCOPE not in str(tokens.get("scope") or "").split():
        _revoke_quietly(refresh)
        raise WrongScope("Waypoint needs permission to read your email, and Google didn’t give it.")
    try:
        profile = _get(HOSTS.api + "/profile", access)
    except (urllib.error.URLError, OSError, ValueError) as e:
        _revoke_quietly(refresh)
        raise GmailError("Google connected, but Waypoint couldn’t read which mailbox it is.") from e
    address = str(profile.get("emailAddress") or "").strip().lower() if isinstance(profile, dict) else ""
    if not address:
        _revoke_quietly(refresh)
        raise GmailError("Google connected, but Waypoint couldn’t read which mailbox it is.")
    history = profile.get("historyId")
    # Connecting an address again (to repair it) keeps where its scans had got to.
    db.upsert(conn, Mailbox, {"owner_sub": owner, "address": address, "token": secretbox.encrypt(refresh),
                              "history_id": str(history) if history is not None else None, "status": CONNECTED,
                              "last_error": None, "created": now},
              key=["owner_sub", "address"], update=["token", "status", "last_error"])
    return address


def _revoke_quietly(token: str) -> None:
    """Tell Google to drop a grant Waypoint won't keep. Nothing more can be done if it can't be reached."""
    with contextlib.suppress(urllib.error.URLError, OSError, ValueError):   # else the person removes it at myaccount.google.com/permissions
        _post(HOSTS.revoke, {"token": token})


# ------------------------------------------------------------------------------------------------ using a connection

def listing(conn: db.Connection, owner: str) -> list[dict[str, Any]]:
    """`owner`'s own mailboxes, never anyone else's, without their tokens."""
    return db.rows(conn.execute(select(Mailbox.id, Mailbox.address, Mailbox.status, Mailbox.last_error, Mailbox.last_scan,
                                       Mailbox.scan_error).where(Mailbox.owner_sub == owner).order_by(Mailbox.id)))


def _find(conn: db.Connection, mailbox_id: int, owner: str | None = None) -> Any:
    q = select(Mailbox.id, Mailbox.owner_sub, Mailbox.token).where(Mailbox.id == mailbox_id)
    if owner is not None:
        q = q.where(Mailbox.owner_sub == owner)
    return conn.execute(q).fetchone()


def _mark(conn: db.Connection, mailbox_id: int, status: str, error: str | None) -> None:
    conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(status=status, last_error=error))
    conn.commit()


def access_token(conn: db.Connection, mailbox_id: int, now: float | None = None) -> str:
    """A fresh access token for a mailbox, for the one call that needs it: refreshed with the stored token after checking
    its owner may still sign in (a lapsed owner's connection is ended: Lapsed). Raises Reconnect when Google no longer
    honours the connection (shown as Reconnect in Settings), GmailError when it couldn't be reached right now."""
    now = time.time() if now is None else now
    row = _find(conn, mailbox_id)
    if not row:
        raise GmailError("That mailbox isn’t connected.")
    email = conn.execute(select(User.email).where(User.sub == row["owner_sub"])).scalar()
    if oidc.access_lapsed(conn, row["owner_sub"], email, now):
        end(conn, mailbox_id)
        raise Lapsed("The person who connected this mailbox can no longer sign in, so it was disconnected.")
    try:
        refresh = secretbox.decrypt(row["token"])
    except secretbox.SecretError as e:   # the key changed: only connecting again helps
        _mark(conn, mailbox_id, RECONNECT, "Waypoint can’t unlock the saved connection with its current key.")
        raise Reconnect("This connection can’t be unlocked any more.") from e
    client_id, client_secret = _credentials()
    try:
        tokens = _post(HOSTS.token, {"grant_type": "refresh_token", "refresh_token": refresh or "",
                                     "client_id": client_id, "client_secret": client_secret})
    except urllib.error.HTTPError as e:
        if _refused_grant(e):
            _mark(conn, mailbox_id, RECONNECT, "Google no longer lets Waypoint read this mailbox.")
            raise Reconnect("Google no longer lets Waypoint read this mailbox.") from e
        _mark(conn, mailbox_id, FAILING, "Google refused to refresh the connection just now.")
        raise GmailError("Google refused to refresh the connection just now.") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        _mark(conn, mailbox_id, FAILING, "Couldn’t reach Google just now.")
        raise GmailError("Couldn’t reach Google just now.") from e
    token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(token, str) or not token:
        _mark(conn, mailbox_id, FAILING, "Google didn’t return access.")
        raise GmailError("Google didn’t return access.")
    _mark(conn, mailbox_id, CONNECTED, None)
    return token


def _revoke(token: str | None) -> bool:
    """Whether Google no longer honours `token` afterwards. Google answers 400 for one that's already gone, which is as
    good; anything else (unreachable, an error) means it may still work. A token Waypoint can't read can't be revoked."""
    if not token:
        return False
    try:
        _post(HOSTS.revoke, {"token": token})
    except urllib.error.HTTPError as e:
        return e.code == 400
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return True


def end(conn: db.Connection, mailbox_id: int) -> bool:
    """End a connection whatever Google says (its owner can't sign in any more): revoke the token if it can be, delete the
    row. Returns whether Google revoked it."""
    row = _find(conn, mailbox_id)
    if not row:
        return True
    try:
        token = secretbox.decrypt(row["token"])
    except secretbox.SecretError:
        token = None
    conn.execute(delete(Mailbox).where(Mailbox.id == mailbox_id))
    conn.commit()
    return _revoke(token)


def end_lapsed(conn: db.Connection, now: float | None = None) -> int:
    """End every connection whose owner can no longer sign in (revoked at Google when it can be, then deleted), without
    waiting for something to use it. Returns how many ended."""
    now = time.time() if now is None else now
    ended = 0
    for m in db.rows(conn.execute(select(Mailbox.id, Mailbox.owner_sub))):
        email = conn.execute(select(User.email).where(User.sub == m["owner_sub"])).scalar()
        if oidc.access_lapsed(conn, m["owner_sub"], email, now):
            end(conn, m["id"])
            ended += 1
    return ended


def disconnect(conn: db.Connection, mailbox_id: int, owner: str) -> bool:
    """Revoke `owner`'s mailbox at Google and delete it. Returns True once Google dropped the token; False when it
    couldn't be read (the key changed) and the connection was deleted anyway. Raises GmailError, deleting nothing, when
    Google couldn't be reached: the access would otherwise stay while Settings said it was gone. A mailbox that isn't
    `owner`'s answers as one that isn't there (KeyError)."""
    row = _find(conn, mailbox_id, owner)
    if not row:
        raise KeyError(mailbox_id)
    try:
        token = secretbox.decrypt(row["token"])
    except secretbox.SecretError:
        token = None   # nothing to revoke with: the person removes Waypoint at Google themselves
    if token is not None and not _revoke(token):
        raise GmailError("Couldn’t reach Google to revoke Waypoint’s access, so the mailbox is still connected. "
                         "Try again, or remove Waypoint at myaccount.google.com/permissions.")
    conn.execute(delete(Mailbox).where(Mailbox.id == mailbox_id))
    return token is not None


# ------------------------------------------------------------------------------------------------ reading mail

SEARCH_PAGE = 100
MAX_FOUND = 5000     # messages one search returns at most (a mailbox's bookings from months are far fewer)
FETCH_ATTEMPTS = 3   # a message that Google fails to give is tried this many times before the scan stops


def _api(path: str, token: str, params: dict[str, str] | None = None) -> Any:
    """One call to Gmail's API, answered as JSON. Raises GmailError (fixed text) for anything that goes wrong, MessageGone
    for a message that's no longer there."""
    url = HOSTS.api + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        return _get(url, token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise MessageGone("That message is gone.") from e
        if e.code == 429:
            raise GmailError("Google asked Waypoint to slow down; the scan carries on next time.") from e
        raise GmailError("Google refused a request while reading the mailbox.") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GmailError("Couldn’t reach Google while reading the mailbox.") from e


def history_id(token: str) -> str | None:
    """Where the mailbox is now (its history id), to note before a scan so that nothing arriving during it is missed."""
    profile = _api("/profile", token)
    found = profile.get("historyId") if isinstance(profile, dict) else None
    return str(found) if found is not None else None


def search(token: str, query: str) -> list[str]:
    """The ids of the messages Gmail finds for this search (newest first), up to MAX_FOUND: the search runs at Google, so
    only what matches is ever downloaded, and only ids come back here."""
    ids: list[str] = []
    page: str | None = None
    while len(ids) < MAX_FOUND:
        params = {"q": query, "maxResults": str(SEARCH_PAGE), **({"pageToken": page} if page else {})}
        found = _api("/messages", token, params)
        listed = found.get("messages") if isinstance(found, dict) else None
        ids += [str(m["id"]) for m in listed or [] if isinstance(m, dict) and m.get("id")]
        page = found.get("nextPageToken") if isinstance(found, dict) else None
        if not page:
            break
    return ids[:MAX_FOUND]


def added_since(token: str, start: str) -> set[str]:
    """The ids of the messages added to the mailbox since this history id. Raises HistoryExpired when Google no longer
    has it (the scan then looks back by date instead)."""
    ids: set[str] = set()
    page: str | None = None
    while True:
        params = {"startHistoryId": start, "historyTypes": "messageAdded", "maxResults": "500",
                  **({"pageToken": page} if page else {})}
        try:
            found = _api("/history", token, params)
        except MessageGone as e:   # (Google answers 404 for a history id it has dropped)
            raise HistoryExpired("Google no longer has the history this scan resumes from.") from e
        for record in (found.get("history") if isinstance(found, dict) else None) or []:
            for added in record.get("messagesAdded") or []:
                message = added.get("message") if isinstance(added, dict) else None
                if isinstance(message, dict) and message.get("id"):
                    ids.add(str(message["id"]))
        page = found.get("nextPageToken") if isinstance(found, dict) else None
        if not page:
            return ids


def fetch(token: str, message_id: str) -> dict[str, Any]:
    """One message as Google gives it (`format=raw`), for domain/mail/extract.py alone to read: it's passed on untouched, in
    memory. Raises MessageGone when it was deleted meanwhile, GmailError when Google fails to give it."""
    quoted = urllib.parse.quote(message_id, safe="")
    for attempt in range(FETCH_ATTEMPTS):
        try:
            found = _api(f"/messages/{quoted}", token, {"format": "raw"})
        except MessageGone:
            raise
        except GmailError:
            if attempt == FETCH_ATTEMPTS - 1:
                raise
            time.sleep(0.2 * (attempt + 1))
            continue
        return found if isinstance(found, dict) else {}
    raise GmailError("Couldn’t reach Google while reading the mailbox.")   # (not reached)


def open_url(address: str, message_id: str) -> str:
    """Where a person opens a message in Gmail itself (a link for their browser; Waypoint doesn't call it)."""
    # The account is chosen with `authuser` (an address works there; Gmail's /mail/u/<address>/ form answers "account
    # temporarily unavailable" for some accounts).
    return "https://mail.google.com/mail/?" + urllib.parse.urlencode({"authuser": address}) + "#all/" + urllib.parse.quote(message_id, safe="")
