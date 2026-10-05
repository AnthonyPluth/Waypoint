"""OAuth for /mcp over HTTP (waypoint/server/mcp_oauth.py does the work): the endpoints an app calls itself (metadata,
registration, tokens, revocation), which need no sign-in and no same-site checks, and the consent page, /oauth/authorize,
where you approve an assistant: the one OAuth page that needs you signed in. The handler (server/handler.py) decides
who reaches which; these answer them."""
from __future__ import annotations

import html
import json
import secrets
import urllib.parse
from typing import TYPE_CHECKING

from ..storage import db
from . import mcp_access, mcp_oauth
from .common import NOT_READ, BadJson

if TYPE_CHECKING:
    from .handler import Handler

# What an app calls itself, without a Waypoint session. The consent page, /oauth/authorize, is the one OAuth path that
# needs you signed in.
OAUTH_PUBLIC = {"/oauth/register", "/oauth/token", "/oauth/revoke"}
OAUTH_METADATA = {"/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp",
                  "/.well-known/oauth-authorization-server"}


def _answer(h: Handler, status: int, obj: dict | mcp_oauth.OAuthError, www: str | None = None) -> None:
    """An OAuth answer: never cached (RFC 6749 §5.1), errors as {"error", "error_description"}."""
    if isinstance(obj, mcp_oauth.OAuthError):
        status, obj = obj.status, obj.body()
    extra = {"Pragma": "no-cache", **({"WWW-Authenticate": www} if status == 401 and www else {})}
    h._send(status, json.dumps(obj).encode(), extra=extra)


def _body(h: Handler) -> bytes | None:
    n = h._body_length(mcp_oauth.MAX_BODY)
    return None if n is None else h._read_body(n) if n else b""


def _form(raw: bytes) -> dict[str, str] | None:
    """An application/x-www-form-urlencoded body, or None if it can't be read or names a parameter twice."""
    try:
        pairs = urllib.parse.parse_qsl(raw.decode(), keep_blank_values=True, strict_parsing=bool(raw), max_num_fields=50)
    except (UnicodeDecodeError, ValueError):
        return None
    form = dict(pairs)
    return form if len(form) == len(pairs) else None


def app_calls(h: Handler, method: str, url) -> None:
    """The OAuth endpoints an app calls itself (metadata, registration, tokens, revocation). No session and no CORS:
    an app isn't a web page."""
    iss = mcp_oauth.issuer(h.headers.get("Host"))
    if url.path in OAUTH_METADATA:
        if method != "GET":
            return h._send(405, b"", "text/plain", extra={"Allow": "GET"})
        if iss is None:
            return h._json(404, {"error": mcp_oauth.unavailable_reason()})
        if url.path == "/.well-known/oauth-authorization-server":
            return h._json(200, mcp_oauth.authorization_server_metadata(iss))
        return h._json(200, mcp_oauth.protected_resource_metadata(iss))
    if url.path not in OAUTH_PUBLIC:
        return h._json(404, {"error": "Not found"})
    if method != "POST":
        return h._send(405, b"", "text/plain", extra={"Allow": "POST"})
    if iss is None:
        return h._json(404, {"error": mcp_oauth.unavailable_reason()})
    ctype = (h.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    result: dict | mcp_oauth.OAuthError
    if url.path == "/oauth/register":
        # JSON only: a form on another site can't send it without CORS approval, which Waypoint never gives.
        try:
            meta, is_json = h._read_json(mcp_oauth.MAX_BODY), True
        except BadJson:
            meta, is_json = None, False
        if meta is NOT_READ:
            return None
        if ctype != "application/json" or not is_json:
            return _answer(h, 400, mcp_oauth.OAuthError("invalid_client_metadata", "Send the client metadata as JSON."))
        with db.session() as conn:
            try:
                result = mcp_oauth.register(conn, meta)
            except mcp_oauth.OAuthError as e:
                result = e
        return _answer(h, 201, result)
    raw = _body(h)
    if raw is None:
        return None
    form = _form(raw) if ctype == "application/x-www-form-urlencoded" else None
    if form is None:
        return _answer(h, 400, mcp_oauth.OAuthError(
            "invalid_request", "Send the parameters as application/x-www-form-urlencoded, each once."))
    authorization = h.headers.get("Authorization")
    www = 'Basic realm="Waypoint"' if authorization else None
    # Errors are caught inside the session, so what they wrote is kept (a replayed code or refresh token revokes its grant).
    with db.session() as conn:
        try:
            client = mcp_oauth.authenticate_client(conn, form, authorization)
            if url.path == "/oauth/token":
                result = mcp_oauth.token(conn, client, form, iss)
            else:
                mcp_oauth.revoke(conn, client, form.get("token"))
                result = {}
        except mcp_oauth.OAuthError as e:
            result = e
    return _answer(h, 200, result, www)


def authorize(h: Handler, method: str, url) -> None:
    """/oauth/authorize: GET checks an app's request and asks you (the consent page); POST is your answer. Reached
    only signed in (see Handler._route). A request that can't be trusted to go back to the app is shown here instead."""
    iss = mcp_oauth.issuer(h.headers.get("Host"))
    if iss is None:
        return h._page(404, "Assistants can't connect yet", mcp_oauth.unavailable_reason())
    if method == "GET":
        return _consent_ask(h, url, iss)
    if method == "POST":
        return _consent_answer(h, iss)
    return h._send(405, b"", "text/plain", extra={"Allow": "GET, POST"})


def _consent_ask(h: Handler, url, iss: str) -> None:
    user = getattr(h, "user", None) or {}
    with db.session() as conn:
        mcp_oauth.housekeeping(conn)
        try:
            req = mcp_oauth.check_authorize(conn, urllib.parse.parse_qs(url.query, keep_blank_values=True), iss)
        except mcp_oauth.PageError as e:
            return h._page(400, "Can't connect this app", str(e))
        except mcp_oauth.RedirectError as e:
            return h._redirect(mcp_oauth.with_params(e.redirect_uri, {
                "error": e.error, "error_description": e.description, "state": e.state, "iss": iss}))
        writes_on = mcp_access.allow_writes(conn)
        token = mcp_oauth.start_consent(conn, {**req.params(), "sub": user.get("sub")})
    target = urllib.parse.urlsplit(req.redirect_uri)
    name = req.client_name or "An app"
    # The form's answer redirects to the app, so the page may submit to Waypoint and on to the app's address.
    if target.scheme == "https":
        back = f"https://{target.netloc}"
    else:
        back = f"http://{target.hostname}:*" if target.hostname != "::1" else "http:"
    csp = ("default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; "
           f"form-action 'self' {back}; base-uri 'none'; frame-ancestors 'none'")
    cookie = h._cookie_header("waypoint_consent", token, mcp_oauth.CONSENT_TTL, "/oauth")
    page = h._page_html(f"{name} wants to connect to Waypoint",
                        consent_page(req.scope, target, token, user, writes_on), center=False)
    h._send(200, page, "text/html; charset=utf-8", extra={"Set-Cookie": cookie}, csp=csp)


def consent_page(scope, target, token: str, user: dict, writes_on: bool) -> str:
    """The consent page's form (inside the page's card): who's approving, where the answer goes, and a box for each
    scope the app asked for. A box can be ticked only while its switch is on, and is never ticked for you: allowing more
    than reading is a choice made here, each time."""
    who = user.get("email") or user.get("name") or user.get("sub")
    signed_in = (f"You're signed in as <b>{html.escape(who)}</b>. The assistant will see what you see: the trips you're on, nothing more."
                 if who else "This Waypoint has no sign-in of its own, so anyone who can open it can approve apps.")
    boxes = ""
    for name, field, on in (("write", "write", writes_on),):
        if name not in scope:
            continue
        label, note, off = mcp_oauth.CONSENT[name]
        state = f'name="{field}" value="1"' if on else "disabled"
        boxes += (f'<label class="choice"><input type="checkbox" {state}><span><b>{html.escape(label)}</b>'
                  f'<span class="help">{html.escape(note if on else off)}</span></span></label>\n')
    return f"""<p class="help">{signed_in} Approving sends you back to <b>{html.escape(target.netloc)}</b>{
        ' (this computer)' if target.scheme == 'http' else ''}.</p>
<form method="post" action="/oauth/authorize">
<input type="hidden" name="consent" value="{html.escape(token)}">
<label class="choice"><input type="checkbox" checked disabled><span><b>Read your travel</b><span class="help">Upcoming
flights and stays, trips, who is on them, people and guests, stats and live flight status. Never your email, mailboxes, loyalty numbers, backups or settings.</span></span></label>
{boxes}<div class="actions"><button class="btn primary" type="submit" name="decision" value="allow">Allow</button>
<button class="btn" type="submit" name="decision" value="deny">Deny</button></div>
</form>"""


def _consent_answer(h: Handler, iss: str) -> None:
    clear = [h._cookie_header("waypoint_consent", "", 0, "/oauth")]
    again = "Start connecting again from the app."
    if not h._same_site(form=True):
        return h._page(403, "Can't connect this app", "The approval didn't come from Waypoint's page. " + again, cookies=clear)
    raw = _body(h)
    if raw is None:
        return None
    form = _form(raw) or {}
    sent, cookie = form.get("consent") or "", h._cookie("waypoint_consent") or ""
    if not sent or not cookie or not secrets.compare_digest(sent, cookie):
        return h._page(403, "Can't connect this app", "The approval didn't come from this browser. " + again, cookies=clear)
    user = getattr(h, "user", None) or {}
    with db.session() as conn:
        params = mcp_oauth.take_consent(conn, sent)
        if params is None or params.get("sub") != user.get("sub"):
            return h._page(403, "Can't connect this app", "That approval page has expired or was already answered. " + again,
                           cookies=clear)
        client = mcp_oauth.get_client(conn, params["client_id"])
        if client is None or not mcp_oauth.redirect_matches(json.loads(client["redirect_uris"]), params["redirect_uri"]):
            return h._page(400, "Can't connect this app", mcp_oauth.UNKNOWN_APP, cookies=clear)
        decision = form.get("decision")
        if decision == "allow":
            scope = {"read"}
            asked = params["scope"].split()
            if "write" in asked and form.get("write") == "1" and mcp_access.allow_writes(conn):
                scope.add("write")
            code = mcp_oauth.approve(conn, params, frozenset(scope), user.get("sub"), user.get("email"))
            back = {"code": code}
        elif decision == "deny":
            back = {"error": "access_denied", "error_description": "The person using Waypoint said no."}
        else:
            return h._page(400, "Can't connect this app", "Choose Allow or Deny. " + again, cookies=clear)
    h._redirect(mcp_oauth.with_params(params["redirect_uri"], {**back, "state": params.get("state"), "iss": iss}), clear)
    return None
