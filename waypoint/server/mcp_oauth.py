"""OAuth for Waypoint's MCP endpoint: Waypoint is both the authorization server and the resource server (/mcp).

The person approving an app is whoever is signed in to Waypoint (waypoint/oidc.py): there's no other identity provider,
and the assistant then acts as that member (what they see, nothing more). The pieces: protected-resource metadata (RFC 9728),
authorization-server metadata (RFC 8414), dynamic client registration (RFC 7591, without the management API of RFC 7592),
the authorization code flow with PKCE (S256 only), refresh tokens that rotate, with a replayed one revoking its grant,
revocation (RFC 7009), resource indicators (RFC 8707) and the iss parameter on redirects (RFC 9207). Scopes: "read"
(always) and "write" (opt-in, any change outside mcp_access.BLOCKED, only while "Let assistants change trips" is on:
mcp_access.allow_writes). What the consent page says the opt-in allows is CONSENT. Loyalty and Known Traveler numbers are
out of an assistant's reach whatever it is allowed (mcp_access.BLOCKED).

A grant is one approval on the consent page: the unit Settings lists and revokes. Codes and tokens are random
(secrets.token_urlsafe(32), with a prefix) and only their sha256 is stored; revoke_grant() ends everything under a
grant at once. Access tokens last an hour, refresh tokens 90 days (a fresh 90 days on each rotation), codes 10 minutes.
A grant ends when its approver can no longer sign in (oidc.access_lapsed: see cut_off_reason), checked on every use.

Nothing here makes an outbound request: clients register by POSTing their metadata, and Waypoint never fetches a URL a
client gives it. Client ID metadata documents (a client_id that is a URL to fetch) aren't supported; adding them needs
host and IP filtering against request forgery first. oauth_clients.kind and metadata_url are reserved for it.

The functions here are pure over a connection: the HTTP side is in waypoint/server/oauth_http.py. A function that raises
OAuthError may have written something that must be kept (a replayed code or refresh token revokes its grant first), so
callers catch it inside their db.session() block, which then commits.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, exists, insert, or_, select, true, update

from .. import oidc
from ..storage.models import OAuthClient, OAuthCode, OAuthConsent, OAuthGrant, OAuthToken

SCOPES = ("read", "write")
# What the consent page says ticking each opt-in scope lets the assistant do (and, switched off, what to do first).
CONSENT = {
    "write": ("Change trips",
              "Add, change and remove trips, bookings, travellers, people and guests, and the distance unit. "
              "Never mailboxes, the “Couldn’t read” queue, AI settings, backups, loyalty numbers, sign-in or these assistant settings. It's told "
              "to ask you before every change.",
              "Turn on Let assistants change trips in Settings first. Until then this connection can't make changes."),
}
ACCESS_TTL = 3600                 # seconds
REFRESH_TTL = 90 * 86400
CODE_TTL = 600
CONSENT_TTL = 600
UNCONSENTED_TTL = 24 * 3600       # a registered app nobody approved is dropped after this (a day, to come back to it)
MAX_UNCONSENTED = 50              # ... and at most this many are kept once they're older than CONSENT_TTL (the oldest go first):
MAX_UNCONSENTED_ALL = 1000        # a burst of registrations can't push out an app that's connecting right now; this bounds the burst
KEEP = 30 * 86400                 # spent tokens and revoked grants are kept this long, then deleted
MAX_BODY = 8 * 1024               # bytes in a request to /oauth/register, /oauth/token or /oauth/revoke
MAX_NAME = 100
MAX_REDIRECTS = 10
MAX_URI = 2000
AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")
GRANT_TYPES = ("authorization_code", "refresh_token")
LOOPBACK = ("127.0.0.1", "::1", "localhost")
TOUCH_EVERY = 60                  # seconds between updates of a grant's last_used

_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*")
_PUBLIC_URL = re.compile(r"https?://[A-Za-z0-9.-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~/-]*)?")   # nothing to escape in a header
_HOST_HEADER = re.compile(r"(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|\[[0-9a-f:.]+\])(?::\d{1,5})?")
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")


# An app registered long ago and never approved is forgotten, but an assistant may keep its client_id and try again:
# this page can't send it an error, so it tells the person how to start over.
UNKNOWN_APP = ("Waypoint doesn't know this app any more (it was never approved, or it was removed). Remove Waypoint from "
               "the assistant and add it again, then connect.")


class OAuthError(Exception):
    """An OAuth error answer: RFC 6749's `error` code and a description (HTTP status 400, or 401 for invalid_client)."""

    def __init__(self, error: str, description: str, status: int = 400):
        super().__init__(description)
        self.error, self.description, self.status = error, description, status

    def body(self) -> dict:
        return {"error": self.error, "error_description": self.description}


class PageError(Exception):
    """An authorization request that can't be sent back to the app (unknown app, or a redirect_uri it didn't register):
    shown on Waypoint's own page, never redirected."""


class RedirectError(OAuthError):
    """An authorization request that's wrong in some other way: the error goes back to the app's verified redirect_uri."""

    def __init__(self, error: str, description: str, redirect_uri: str, state: str | None):
        super().__init__(error, description)
        self.redirect_uri, self.state = redirect_uri, state


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _same(a: str | None, b: str) -> bool:
    return a is not None and hmac.compare_digest(a, b)


# ------------------------------------------------------------------------------------------------ issuer and metadata

def issuer(host: str | None) -> str | None:
    """Waypoint's address as an OAuth issuer: WAYPOINT_PUBLIC_URL (https://, or http:// on a home address). Without it,
    http://<Host> only for an address that makes sense only at home (oidc.local_host); otherwise None, and OAuth is off."""
    public = oidc.config()["public_url"]
    if public:
        if not _PUBLIC_URL.fullmatch(public):
            return None
        p = urllib.parse.urlsplit(public)
        ok = p.scheme == "https" or (p.scheme == "http" and oidc.local_host(p.hostname or ""))
        return public if ok and p.hostname else None
    host = (host or "").strip().lower()
    if not _HOST_HEADER.fullmatch(host):
        return None
    try:
        name = urllib.parse.urlsplit("//" + host).hostname
    except ValueError:
        return None
    return "http://" + host if name and oidc.local_host(name) else None


def unavailable_reason() -> str:
    if oidc.config()["public_url"]:
        return ("WAYPOINT_PUBLIC_URL must be an https:// address (or http:// on a home network) for assistants to connect "
                "with OAuth.")
    return "Set WAYPOINT_PUBLIC_URL to the address you open Waypoint at, so assistants can connect with OAuth."


def resource(iss: str) -> str:
    """The canonical address of the MCP endpoint (RFC 8707): what every token is for."""
    return iss + "/mcp"


def protected_resource_metadata(iss: str) -> dict:
    return {"resource": resource(iss), "authorization_servers": [iss], "scopes_supported": list(SCOPES),
            "bearer_methods_supported": ["header"]}


def authorization_server_metadata(iss: str) -> dict:
    return {"issuer": iss, "authorization_endpoint": iss + "/oauth/authorize", "token_endpoint": iss + "/oauth/token",
            "registration_endpoint": iss + "/oauth/register", "revocation_endpoint": iss + "/oauth/revoke",
            "response_types_supported": ["code"], "grant_types_supported": list(GRANT_TYPES),
            "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": list(AUTH_METHODS),
            "revocation_endpoint_auth_methods_supported": list(AUTH_METHODS), "scopes_supported": list(SCOPES),
            "authorization_response_iss_parameter_supported": True}


def resource_metadata_url(iss: str) -> str:
    return iss + "/.well-known/oauth-protected-resource/mcp"


# ------------------------------------------------------------------------------------------------ checking values

def check_redirect_uri(uri: Any) -> str:
    """A redirect URI an app may register: https://, or http:// to this computer (127.0.0.1, [::1], localhost). No
    other schemes, fragments or user names."""
    def bad(why: str) -> OAuthError:
        return OAuthError("invalid_redirect_uri", why)
    if not isinstance(uri, str) or not uri or len(uri) > MAX_URI:
        raise bad(f"Each redirect URI must be a string of at most {MAX_URI} characters.")
    if not uri.isascii() or any(ord(ch) <= 32 or ord(ch) == 127 for ch in uri) or "\\" in uri:
        raise bad("A redirect URI can't contain spaces, control characters, backslashes or non-ASCII characters.")
    try:
        p = urllib.parse.urlsplit(uri)
        _ = p.port   # raises ValueError for a port that isn't a number
    except ValueError:
        raise bad(f"{uri} isn't a valid URI.") from None
    if "#" in uri:
        raise bad("A redirect URI can't have a fragment.")
    if "@" in p.netloc:
        raise bad("A redirect URI can't have a user name or password.")
    host = p.hostname or ""
    if p.scheme == "https":
        if not _HOSTNAME.fullmatch(host):
            raise bad(f"{uri} doesn't name a host.")
    elif p.scheme == "http":
        if host not in LOOPBACK:
            raise bad("An http:// redirect URI must be to this computer (127.0.0.1, [::1] or localhost); use https:// otherwise.")
    else:
        raise bad("A redirect URI must be https://, or http:// to this computer. Other schemes aren't supported.")
    return uri


def _loopback(uri: str) -> tuple[str, str, str] | None:
    """A loopback redirect URI without its port (RFC 8252 §7.3: a native app gets whatever port is free)."""
    p = urllib.parse.urlsplit(uri)
    return (p.hostname or "", p.path, p.query) if p.scheme == "http" and p.hostname in LOOPBACK else None


def redirect_matches(registered: list[str], given: Any) -> bool:
    """Whether `given` is one of the app's registered redirect URIs: exactly, or for http:// loopback ones, exactly
    but for the port."""
    try:
        check_redirect_uri(given)
    except OAuthError:
        return False
    if given in registered:
        return True
    key = _loopback(given)
    return key is not None and any(_loopback(r) == key for r in registered)


def parse_scope(value: Any, error: str = "invalid_scope") -> frozenset[str]:
    """Space-separated scopes; nothing means "read", and "read" is always included."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return frozenset({"read"})
    if not isinstance(value, str):
        raise OAuthError(error, "scope must be a string.")
    parts = set(value.split())
    unknown = parts - set(SCOPES)
    if unknown:
        raise OAuthError(error, f"Unknown scope {sorted(unknown)[0]!r}: Waypoint has {', '.join(SCOPES)}.")
    return frozenset(parts | {"read"})


def scope_text(scopes: frozenset[str] | set[str]) -> str:
    return " ".join(s for s in SCOPES if s in scopes)


def check_resource(given: Any, canonical: str, error: type[OAuthError] | None = None, **kw: Any) -> None:
    """`resource`, if sent, must be this MCP endpoint (a trailing slash aside)."""
    if given is None or given == "":
        return
    if not isinstance(given, str) or given.rstrip("/") != canonical:
        raise (error or OAuthError)("invalid_target", f"Waypoint can only issue tokens for {canonical}.", **kw)


def pkce_ok(verifier: Any, challenge: str) -> bool:
    if not isinstance(verifier, str) or not _VERIFIER.fullmatch(verifier):
        return False
    made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(made, challenge)


def with_params(uri: str, params: dict[str, str | None]) -> str:
    """`uri` with these added to its query (keeping whatever query it has)."""
    p = urllib.parse.urlsplit(uri)
    extra = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return urllib.parse.urlunsplit(p._replace(query=(p.query + "&" if p.query else "") + extra))


# ------------------------------------------------------------------------------------------------ clients

def register(conn, meta: Any, now: float | None = None) -> dict:
    """Dynamic client registration (RFC 7591): check an app's metadata, save it, and answer its client_id (and a
    client_secret if it asked for a method that uses one; only a hash of it is kept)."""
    now = time.time() if now is None else now

    def bad(why: str) -> OAuthError:
        return OAuthError("invalid_client_metadata", why)
    if not isinstance(meta, dict):
        raise bad("Send the client metadata as a JSON object.")
    uris = meta.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECTS:
        raise OAuthError("invalid_redirect_uri", f"redirect_uris must list 1 to {MAX_REDIRECTS} URIs.")
    uris = list(dict.fromkeys(check_redirect_uri(u) for u in uris))
    name = meta.get("client_name")
    if name is not None:
        if not isinstance(name, str) or len(name) > MAX_NAME or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
            raise bad(f"client_name must be text of at most {MAX_NAME} characters.")
        name = name.strip() or None
    method = meta.get("token_endpoint_auth_method", "none")
    if method not in AUTH_METHODS:
        raise bad(f"token_endpoint_auth_method must be one of {', '.join(AUTH_METHODS)}.")
    grants = meta.get("grant_types", list(GRANT_TYPES))
    if (not isinstance(grants, list) or not grants or any(g not in GRANT_TYPES for g in grants)
            or "authorization_code" not in grants):
        raise bad("grant_types must be authorization_code, and optionally refresh_token.")
    responses = meta.get("response_types", ["code"])
    if not isinstance(responses, list) or responses != ["code"] * len(responses) or not responses:
        raise bad("response_types must be [\"code\"].")
    scope = meta.get("scope")
    if scope is not None:
        scope = scope_text(parse_scope(scope, "invalid_client_metadata"))

    housekeeping(conn, now)
    unapproved = ~exists().where(OAuthGrant.client_id == OAuthClient.id)
    for limit, cond in ((MAX_UNCONSENTED, OAuthClient.created < now - CONSENT_TTL), (MAX_UNCONSENTED_ALL, true())):
        conn.execute(delete(OAuthClient).where(OAuthClient.id.in_(
            select(OAuthClient.id).where(unapproved, cond).order_by(OAuthClient.created.desc(), OAuthClient.id)
            .offset(limit - 1))))
    client_id = "wpc_" + secrets.token_urlsafe(24)
    secret = secrets.token_urlsafe(32) if method != "none" else None
    conn.execute(insert(OAuthClient).values(id=client_id, name=name, redirect_uris=json.dumps(uris), auth_method=method,
                                            secret_hash=_hash(secret) if secret else None, kind="dcr", created=now))
    out: dict[str, Any] = {"client_id": client_id, "client_id_issued_at": int(now), "redirect_uris": uris,
                           "token_endpoint_auth_method": method, "grant_types": list(dict.fromkeys(grants)),
                           "response_types": ["code"]}
    if name:
        out["client_name"] = name
    if scope:
        out["scope"] = scope
    if secret:
        out.update(client_secret=secret, client_secret_expires_at=0)
    return out


def get_client(conn, client_id: Any):
    if not isinstance(client_id, str) or not client_id.startswith("wpc_"):
        return None
    row = conn.execute(select(OAuthClient).where(OAuthClient.id == client_id)).fetchone()
    return row if row is not None and _same(row["id"], client_id) else None


def _basic(authorization: str | None) -> tuple[str, str] | None:
    """HTTP Basic credentials (RFC 6749 §2.3.1: each part form-encoded first), or None if there's no Basic header."""
    value = (authorization or "").strip()
    if value[:6].lower() != "basic ":
        return None
    try:
        user, sep, password = binascii.a2b_base64(value[6:].strip(), strict_mode=True).decode().partition(":")
    except (ValueError, binascii.Error):   # not base64, or not UTF-8
        sep = ""
    if not sep:
        raise OAuthError("invalid_client", "The Basic credentials couldn't be read.", 401)
    return urllib.parse.unquote_plus(user), urllib.parse.unquote_plus(password)


def authenticate_client(conn, form: dict[str, str], authorization: str | None):
    """The app making a token or revocation request, checked the way it registered: client_id alone ("none"), or with
    its secret in the form or a Basic header. OAuthError invalid_client (401) otherwise."""
    basic = _basic(authorization)
    form_id, form_secret = form.get("client_id"), form.get("client_secret")
    if basic and form_secret is not None:
        raise OAuthError("invalid_request", "Send the client secret one way only.")
    if basic and form_id is not None and form_id != basic[0]:
        raise OAuthError("invalid_client", "The client_id doesn't match the credentials.", 401)
    client = get_client(conn, basic[0] if basic else form_id)
    if client is None:
        raise OAuthError("invalid_client", "Waypoint doesn't know this client. Register it again.", 401)
    method = client["auth_method"]
    secret = basic[1] if basic else form_secret
    if method == "none":
        if secret:
            raise OAuthError("invalid_client", "This client was registered without a secret.", 401)
        return client
    sent_as = "client_secret_basic" if basic else "client_secret_post" if form_secret is not None else None
    if sent_as != method or not secret or not _same(client["secret_hash"], _hash(secret)):
        raise OAuthError("invalid_client", "The client's credentials are wrong.", 401)
    return client


# ------------------------------------------------------------------------------------------------ authorizing

@dataclass(frozen=True)
class AuthRequest:
    client_id: str
    client_name: str | None
    redirect_uri: str
    scope: frozenset[str]
    state: str | None
    code_challenge: str
    resource: str

    def params(self) -> dict:
        return {"client_id": self.client_id, "redirect_uri": self.redirect_uri, "scope": scope_text(self.scope),
                "state": self.state, "code_challenge": self.code_challenge, "resource": self.resource}


def check_authorize(conn, query: dict[str, list[str]], iss: str) -> AuthRequest:
    """An authorization request (the query of GET /oauth/authorize). PageError when the app or its redirect_uri can't
    be trusted; RedirectError for anything else, to send back to that redirect_uri."""
    if any(len(v) > 1 for v in query.values()):
        raise PageError("The request to connect has a parameter more than once. Try connecting again from the app.")
    q = {k: v[0] for k, v in query.items()}
    client = get_client(conn, q.get("client_id"))
    if client is None:
        raise PageError(UNKNOWN_APP)
    redirect = q.get("redirect_uri")
    if not isinstance(redirect, str) or not redirect_matches(json.loads(client["redirect_uris"]), redirect):
        raise PageError("The app asked to return to an address it didn't register, so Waypoint won't send you there.")
    state = q.get("state")

    def back(error: str, why: str) -> RedirectError:
        return RedirectError(error, why, redirect, state)
    if q.get("response_type") != "code":
        raise back("unsupported_response_type", "Waypoint supports response_type=code only.")
    if q.get("code_challenge_method") != "S256":
        raise back("invalid_request", "PKCE with code_challenge_method=S256 is required.")
    challenge = q.get("code_challenge") or ""
    if not _CHALLENGE.fullmatch(challenge):
        raise back("invalid_request", "code_challenge must be an S256 challenge (43 base64url characters).")
    try:
        scope = parse_scope(q.get("scope"))
    except OAuthError as e:
        raise back(e.error, e.description) from None
    canonical = resource(iss)
    check_resource(q.get("resource"), canonical, RedirectError, redirect_uri=redirect, state=state)
    return AuthRequest(client["id"], client["name"], redirect, scope, state, challenge, canonical)


def start_consent(conn, params: dict, now: float | None = None) -> str:
    """Keep a checked authorization request (and who was signed in) for the consent form: returns the form's token."""
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    conn.execute(insert(OAuthConsent).values(token_hash=_hash(token), params=json.dumps(params), created=now))
    return token


def take_consent(conn, token: str | None, now: float | None = None) -> dict | None:
    """The request a consent form was shown for, once (it's gone after this), and only within CONSENT_TTL."""
    now = time.time() if now is None else now
    if not token:
        return None
    h = _hash(token)
    row = conn.execute(select(OAuthConsent).where(OAuthConsent.token_hash == h)).fetchone()
    if row is None or not _same(row["token_hash"], h):
        return None
    if conn.execute(delete(OAuthConsent).where(OAuthConsent.token_hash == h)).rowcount != 1:
        return None   # answered at the same moment by another request
    if now - row["created"] > CONSENT_TTL:
        return None
    return json.loads(row["params"])


def approve(conn, params: dict, scope: frozenset[str], sub: str | None, email: str | None, now: float | None = None) -> str:
    """The person allowed the app: a grant for `scope`, and a code for it (returned) that the app trades for tokens."""
    now = time.time() if now is None else now
    grant_id = conn.execute(insert(OAuthGrant).values(client_id=params["client_id"], sub=sub, email=email,
                                                      scope=scope_text(scope), resource=params["resource"],
                                                      created=now)).lastrowid
    code = "wpo_" + secrets.token_urlsafe(32)
    conn.execute(insert(OAuthCode).values(code_hash=_hash(code), client_id=params["client_id"], grant_id=grant_id,
                                          redirect_uri=params["redirect_uri"], code_challenge=params["code_challenge"],
                                          resource=params["resource"], created=now))
    return code


# ------------------------------------------------------------------------------------------------ tokens

def cut_off_reason(conn, grant, now: float) -> str | None:
    """Why a grant must end because of who approved it, or None. An approval lasts only as long as its approver may
    sign in, judged the way their browser sessions are (oidc.still_allowed): taken off OIDC_ALLOWED_EMAILS, it ends at
    once ("user_removed"). With OIDC_ALLOWED_GROUPS, where that can be known only at sign-in, it ends WAYPOINT_SESSION_DAYS
    after the approver last signed in, as a session would ("sign_in_lapsed"). Without sign-in (OIDC off) nothing ends."""
    return oidc.access_lapsed(conn, grant["sub"], grant["email"], now)


def _cut_off(conn, grant, now: float) -> bool:
    """Revoke the grant if its approver may no longer sign in (see cut_off_reason). True if it was."""
    why = cut_off_reason(conn, grant, now)
    if why:
        revoke_grant(conn, grant["id"], why, now)
    return why is not None


def _grant(conn, grant_id: int):
    return conn.execute(select(OAuthGrant).where(OAuthGrant.id == grant_id)).fetchone()


def _issue(conn, grant, now: float) -> tuple[dict, str]:
    access, refresh = "wpa_" + secrets.token_urlsafe(32), "wpr_" + secrets.token_urlsafe(32)
    conn.execute(insert(OAuthToken), [
        {"token_hash": _hash(access), "kind": "access", "grant_id": grant["id"], "created": now, "expires": now + ACCESS_TTL},
        {"token_hash": _hash(refresh), "kind": "refresh", "grant_id": grant["id"], "created": now, "expires": now + REFRESH_TTL}])
    return ({"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL, "refresh_token": refresh,
             "scope": grant["scope"]}, _hash(refresh))


def token(conn, client, form: dict[str, str], iss: str, now: float | None = None) -> dict:
    """POST /oauth/token for an authenticated client: an authorization code or a refresh token for new tokens."""
    now = time.time() if now is None else now
    housekeeping(conn, now)
    canonical = resource(iss)
    grant_type = form.get("grant_type")
    if grant_type not in GRANT_TYPES:
        raise OAuthError("unsupported_grant_type", "grant_type must be authorization_code or refresh_token.")
    check_resource(form.get("resource"), canonical)
    if grant_type == "authorization_code":
        return _exchange_code(conn, client, form, canonical, now)
    return _refresh(conn, client, form, canonical, now)


def _exchange_code(conn, client, form: dict[str, str], canonical: str, now: float) -> dict:
    code, verifier = form.get("code"), form.get("code_verifier")
    if not code or not form.get("redirect_uri"):
        raise OAuthError("invalid_request", "code and redirect_uri are required.")
    if not verifier:
        raise OAuthError("invalid_request", "code_verifier is required (PKCE).")
    h = _hash(code)
    row = conn.execute(select(OAuthCode).where(OAuthCode.code_hash == h)).fetchone()
    if row is None or not _same(row["code_hash"], h):
        raise OAuthError("invalid_grant", "That code isn't valid.")
    # One use only, even two requests at once: a code sent again means it leaked, so its grant is revoked.
    if conn.execute(update(OAuthCode).where(OAuthCode.code_hash == h, OAuthCode.used.is_(None)).values(used=now)).rowcount != 1:
        revoke_grant(conn, row["grant_id"], "code_reuse", now)
        raise OAuthError("invalid_grant", "That code was already used.")
    if now - row["created"] > CODE_TTL:
        raise OAuthError("invalid_grant", "That code has expired.")
    if row["client_id"] != client["id"] or row["redirect_uri"] != form["redirect_uri"]:
        raise OAuthError("invalid_grant", "That code was issued to another client or redirect_uri.")
    if not pkce_ok(verifier, row["code_challenge"]):
        raise OAuthError("invalid_grant", "code_verifier doesn't match the code_challenge.")
    grant = _grant(conn, row["grant_id"])
    if (grant is None or grant["revoked"] is not None or row["resource"] != canonical or grant["resource"] != canonical
            or _cut_off(conn, grant, now)):
        raise OAuthError("invalid_grant", "That code is no longer valid.")
    return _issue(conn, grant, now)[0]


def _refresh(conn, client, form: dict[str, str], canonical: str, now: float) -> dict:
    presented = form.get("refresh_token")
    if not presented:
        raise OAuthError("invalid_request", "refresh_token is required.")
    h = _hash(presented)
    row = conn.execute(select(OAuthToken).where(OAuthToken.token_hash == h, OAuthToken.kind == "refresh")).fetchone()
    grant = _grant(conn, row["grant_id"]) if row is not None and _same(row["token_hash"], h) else None
    if row is None or grant is None or grant["client_id"] != client["id"]:
        raise OAuthError("invalid_grant", "That refresh token isn't valid.")
    if grant["revoked"] is None and _cut_off(conn, grant, now):   # its approver may no longer sign in: no new tokens
        raise OAuthError("invalid_grant", "The person who approved this connection can no longer sign in to Waypoint.")
    # Rotation: each refresh token works once. One used again means two parties have it, so the grant is revoked.
    if row["consumed"] is not None:
        revoke_grant(conn, grant["id"], "refresh_reuse", now)
        raise OAuthError("invalid_grant", "That refresh token was already used; the connection has been revoked.")
    if grant["revoked"] is not None or row["expires"] <= now or grant["resource"] != canonical:
        raise OAuthError("invalid_grant", "That refresh token is no longer valid.")
    if form.get("scope") and not parse_scope(form.get("scope")) <= set(grant["scope"].split()):
        raise OAuthError("invalid_scope", "A refresh can't add scopes the person didn't approve.")
    if conn.execute(update(OAuthToken).where(OAuthToken.token_hash == h, OAuthToken.consumed.is_(None))
                    .values(consumed=now)).rowcount != 1:   # another request used it at the same moment
        revoke_grant(conn, grant["id"], "refresh_reuse", now)
        raise OAuthError("invalid_grant", "That refresh token was already used; the connection has been revoked.")
    out, new_hash = _issue(conn, grant, now)
    conn.execute(update(OAuthToken).where(OAuthToken.token_hash == h).values(replaced_by=new_hash))
    return out


def revoke(conn, client, presented: str | None, now: float | None = None) -> None:
    """RFC 7009: revoke the grant an access or refresh token belongs to, if it's this client's. Anything else (an
    unknown or spent token) is quietly ignored."""
    if not presented:
        return
    h = _hash(presented)
    row = conn.execute(select(OAuthToken.token_hash, OAuthToken.grant_id).where(OAuthToken.token_hash == h)).fetchone()
    if row is None or not _same(row["token_hash"], h):
        return
    grant = _grant(conn, row["grant_id"])
    if grant is not None and grant["client_id"] == client["id"]:
        revoke_grant(conn, grant["id"], "revoked_by_client", now)


def revoke_grant(conn, grant_id: int, reason: str, now: float | None = None) -> bool:
    """End a grant and everything under it at once: its codes and tokens are deleted and it's marked revoked. The
    one way anything is revoked (Settings, /oauth/revoke, a replayed code or refresh token). True if it was live."""
    now = time.time() if now is None else now
    done = conn.execute(update(OAuthGrant).where(OAuthGrant.id == grant_id, OAuthGrant.revoked.is_(None))
                        .values(revoked=now, revoked_reason=reason)).rowcount == 1
    conn.execute(delete(OAuthCode).where(OAuthCode.grant_id == grant_id))
    conn.execute(delete(OAuthToken).where(OAuthToken.grant_id == grant_id))
    return done


def access_grant(conn, presented: str, canonical: str, now: float | None = None):
    """The grant a live access token for `canonical` belongs to (and note it was used), or None."""
    now = time.time() if now is None else now
    if not presented.startswith("wpa_"):
        return None
    h = _hash(presented)
    row = conn.execute(select(OAuthToken.token_hash, OAuthToken.expires, OAuthGrant.id, OAuthGrant.client_id, OAuthGrant.scope,
                              OAuthGrant.resource, OAuthGrant.revoked, OAuthGrant.sub, OAuthGrant.email, OAuthGrant.last_used)
                       .join(OAuthGrant, OAuthGrant.id == OAuthToken.grant_id)
                       .where(OAuthToken.token_hash == h, OAuthToken.kind == "access")).fetchone()
    if (row is None or not _same(row["token_hash"], h) or row["expires"] <= now or row["revoked"] is not None
            or row["resource"] != canonical):
        return None
    if _cut_off(conn, row, now):   # checked on every request, so taking someone off the sign-in list ends it at once
        return None
    if row["last_used"] is None or now - row["last_used"] > TOUCH_EVERY:
        conn.execute(update(OAuthGrant).where(OAuthGrant.id == row["id"]).values(last_used=now))
        conn.execute(update(OAuthClient).where(OAuthClient.id == row["client_id"]).values(last_used=now))
    return row


# ------------------------------------------------------------------------------------------------ Settings, and tidying

def connections(conn, now: float | None = None) -> list[dict]:
    """The live grants, newest first: what Settings lists as connected assistants (after ending any whose approver may
    no longer sign in, so none is listed that no longer works)."""
    cut_off_removed(conn, now)
    has_tokens = exists().where(OAuthToken.grant_id == OAuthGrant.id)
    rows = conn.execute(select(OAuthGrant.id, OAuthClient.name, OAuthGrant.sub, OAuthGrant.email, OAuthGrant.scope,
                               OAuthGrant.created, OAuthGrant.last_used)
                        .join(OAuthClient, OAuthClient.id == OAuthGrant.client_id)
                        .where(OAuthGrant.revoked.is_(None), has_tokens)
                        .order_by(OAuthGrant.created.desc(), OAuthGrant.id.desc())).fetchall()
    return [{"id": r["id"], "client": r["name"], "who": r["email"] or r["sub"], "scope": r["scope"].split(),
             "created": r["created"], "last_used": r["last_used"]} for r in rows]


def cut_off_removed(conn, now: float | None = None) -> None:
    """Revoke every live grant whose approver may no longer sign in (cut_off_reason). Every use of a grant checks this
    anyway (a token, a refresh, a code); this is so Settings doesn't list one that no longer works."""
    now = time.time() if now is None else now
    if not oidc.enabled():
        return
    for grant in conn.execute(select(OAuthGrant.id, OAuthGrant.sub, OAuthGrant.email).where(OAuthGrant.revoked.is_(None))).fetchall():
        _cut_off(conn, grant, now)


def housekeeping(conn, now: float | None = None) -> None:
    """Delete what's no longer needed: expired codes and consent forms, tokens spent or expired over KEEP ago, grants
    never traded for tokens (or whose tokens are all gone), grants revoked over KEEP ago, and apps registered over
    UNCONSENTED_TTL ago that have no grant."""
    now = time.time() if now is None else now
    conn.execute(delete(OAuthCode).where(OAuthCode.created < now - CODE_TTL))
    conn.execute(delete(OAuthConsent).where(OAuthConsent.created < now - CONSENT_TTL))
    conn.execute(delete(OAuthToken).where(or_(OAuthToken.expires < now - KEEP, OAuthToken.consumed < now - KEEP)))
    has_tokens = exists().where(OAuthToken.grant_id == OAuthGrant.id)
    has_codes = exists().where(OAuthCode.grant_id == OAuthGrant.id)
    conn.execute(delete(OAuthGrant).where(OAuthGrant.revoked.is_(None), OAuthGrant.created < now - CODE_TTL,
                                          ~has_tokens, ~has_codes))
    conn.execute(delete(OAuthGrant).where(OAuthGrant.revoked < now - KEEP))
    conn.execute(delete(OAuthClient).where(OAuthClient.created < now - UNCONSENTED_TTL,
                                           ~exists().where(OAuthGrant.client_id == OAuthClient.id)))

