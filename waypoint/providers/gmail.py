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
PENDING_TTL = 600
MAX_PENDING = 1000
TIMEOUT = 15

CONNECTED, RECONNECT, FAILING = "connected", "reconnect", "error"


@dataclass(frozen=True)
class Hosts:
    auth: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token: str = "https://oauth2.googleapis.com/token"
    revoke: str = "https://oauth2.googleapis.com/revoke"
    api: str = "https://gmail.googleapis.com/gmail/v1/users/me"
    allow_http: bool = False


HOSTS = Hosts()


class GmailError(Exception):
    pass


class NotConfigured(GmailError):
    pass


class Declined(GmailError):
    pass


class Refused(GmailError):
    pass


class WrongScope(GmailError):
    pass


class Reconnect(GmailError):
    pass


class Lapsed(GmailError):
    pass


class MessageGone(GmailError):
    pass


class HistoryExpired(GmailError):
    pass


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


def _open(req: urllib.request.Request) -> Any:
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
    try:
        said = json.loads(e.read().decode())
    except (ValueError, OSError):
        return False
    return isinstance(said, dict) and said.get("error") == "invalid_grant"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def start(conn: db.Connection, owner: str, redirect_uri: str, now: float | None = None) -> str:
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
    now = time.time() if now is None else now
    state = params.get("state") or ""
    row = conn.execute(select(MailboxPending.owner_sub, MailboxPending.verifier, MailboxPending.created)
                       .where(MailboxPending.state == state)).fetchone() if state else None
    if row:
        conn.execute(delete(MailboxPending).where(MailboxPending.state == state))
    conn.commit()
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
    except (urllib.error.URLError, OSError, ValueError) as e:
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
    db.upsert(conn, Mailbox, {"owner_sub": owner, "address": address, "token": secretbox.encrypt(refresh),
                              "history_id": str(history) if history is not None else None, "status": CONNECTED,
                              "last_error": None, "created": now},
              key=["owner_sub", "address"], update=["token", "status", "last_error"])
    return address


def _revoke_quietly(token: str) -> None:
    with contextlib.suppress(urllib.error.URLError, OSError, ValueError):
        _post(HOSTS.revoke, {"token": token})


def listing(conn: db.Connection, owner: str) -> list[dict[str, Any]]:
    return db.rows(conn.execute(select(Mailbox.id, Mailbox.address, Mailbox.status, Mailbox.last_error, Mailbox.last_scan,
                                       Mailbox.scan_error, Mailbox.share_review).where(Mailbox.owner_sub == owner).order_by(Mailbox.id)))


def set_share_review(conn: db.Connection, mailbox_id: int, owner: str, share: bool) -> bool:
    return conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id, Mailbox.owner_sub == owner).values(share_review=share)).rowcount > 0


def _find(conn: db.Connection, mailbox_id: int, owner: str | None = None) -> Any:
    q = select(Mailbox.id, Mailbox.owner_sub, Mailbox.token).where(Mailbox.id == mailbox_id)
    if owner is not None:
        q = q.where(Mailbox.owner_sub == owner)
    return conn.execute(q).fetchone()


def _mark(conn: db.Connection, mailbox_id: int, status: str, error: str | None) -> None:
    conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(status=status, last_error=error))
    conn.commit()


def access_token(conn: db.Connection, mailbox_id: int, now: float | None = None) -> str:
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
    except secretbox.SecretError as e:
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
    now = time.time() if now is None else now
    ended = 0
    for m in db.rows(conn.execute(select(Mailbox.id, Mailbox.owner_sub))):
        email = conn.execute(select(User.email).where(User.sub == m["owner_sub"])).scalar()
        if oidc.access_lapsed(conn, m["owner_sub"], email, now):
            end(conn, m["id"])
            ended += 1
    return ended


def disconnect(conn: db.Connection, mailbox_id: int, owner: str) -> bool:
    row = _find(conn, mailbox_id, owner)
    if not row:
        raise KeyError(mailbox_id)
    try:
        token = secretbox.decrypt(row["token"])
    except secretbox.SecretError:
        token = None
    if token is not None and not _revoke(token):
        raise GmailError("Couldn’t reach Google to revoke Waypoint’s access, so the mailbox is still connected. "
                         "Try again, or remove Waypoint at myaccount.google.com/permissions.")
    conn.execute(delete(Mailbox).where(Mailbox.id == mailbox_id))
    return token is not None


SEARCH_PAGE = 100
MAX_FOUND = 5000
FETCH_ATTEMPTS = 3


def _api(path: str, token: str, params: dict[str, str] | None = None) -> Any:
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
    profile = _api("/profile", token)
    found = profile.get("historyId") if isinstance(profile, dict) else None
    return str(found) if found is not None else None


def search(token: str, query: str) -> list[str]:
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
    ids: set[str] = set()
    page: str | None = None
    while True:
        params = {"startHistoryId": start, "historyTypes": "messageAdded", "maxResults": "500",
                  **({"pageToken": page} if page else {})}
        try:
            found = _api("/history", token, params)
        except MessageGone as e:
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
    raise GmailError("Couldn’t reach Google while reading the mailbox.")


def open_url(address: str, message_id: str) -> str:
    return "https://mail.google.com/mail/?" + urllib.parse.urlencode({"authuser": address}) + "#all/" + urllib.parse.quote(message_id, safe="")
