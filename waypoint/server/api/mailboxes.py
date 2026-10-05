"""Gmail connections (Settings → Gmail): each member sees and connects only their own."""
from __future__ import annotations

from datetime import UTC, datetime

from ... import oidc
from ...domain.mail import scan
from ...providers import gmail
from .. import jobs
from ..common import ApiError, Response, _current, row_id
from ..contract import Disconnected, MailboxList, ScanStarted, Started

# What Settings says about how a return from Google went (?gmail=<code>), as codes so nothing Google said is in an address.
BACK = {gmail.Declined: "denied", gmail.Refused: "refused", gmail.WrongScope: "scope"}


def owner() -> str:
    """Who the signed-in person is, for the connections that belong to them (without sign-in, everyone is `local`)."""
    return str((getattr(_current, "user", None) or {}).get("sub") or "local")


def redirect_uri() -> str:
    """Where Google sends the browser back: <WAYPOINT_PUBLIC_URL>/api/mailboxes/callback (the address the Google client
    allows), or this request's own address when none is set (on your own machine)."""
    base = oidc.config()["public_url"]
    if not base:
        if oidc.enabled():   # a client-chosen Host header isn't an address to send a sign-in's mailbox back to
            raise ApiError("Gmail needs WAYPOINT_PUBLIC_URL to be set.")
        base = f"http://{getattr(_current, 'host', None) or 'localhost'}"   # on your own machine, without sign-in
    return base + "/api/mailboxes/callback"


def _when(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds") if t else None


def api_mailboxes(conn, _q, _b) -> MailboxList:
    """The signed-in member's own connected mailboxes, and whether Google's client is set up for connecting more."""
    gmail.end_lapsed(conn)   # anyone's that lost access: they can't open Settings to disconnect it
    return {"configured": gmail.configured(),
            "mailboxes": [{"id": m["id"], "address": m["address"], "status": m["status"], "last_error": m["last_error"],
                           "last_scan": _when(m["last_scan"]), "scan_error": m["scan_error"], "scanning": scan.running(m["id"]),
                           "scan_notice": scan.notice(m["id"])}
                          for m in gmail.listing(conn, owner())]}


def api_mailbox_connect(conn, _q, _b) -> Started:
    """Where to send the browser to connect a Gmail (Google's consent screen, for read-only access)."""
    try:
        return {"url": gmail.start(conn, owner(), redirect_uri())}
    except gmail.NotConfigured as e:
        raise ApiError(str(e)) from e


def api_mailbox_callback(conn, q, _b) -> Response:
    """Google's return: keep the connection, then back to Settings with how it went (?gmail=connected, denied, ...)."""
    params = {k: v[0] for k, v in q.items() if v}
    try:
        gmail.finish(conn, owner(), params, redirect_uri())
        outcome = "connected"
    except gmail.GmailError as e:
        outcome = next((code for kind, code in BACK.items() if isinstance(e, kind)), "failed")
    return Response(b"", "text/plain", status=302, headers={"Location": f"/?gmail={outcome}#settings"})


def api_mailbox_disconnect(conn, _q, _b, mailbox_id: str) -> Disconnected:
    """Revoke the mailbox's access at Google and delete the connection. Someone else's is a 404, as one that isn't there."""
    try:
        n = int(mailbox_id) if mailbox_id.isdigit() and len(mailbox_id) < 19 else -1
        revoked = gmail.disconnect(conn, n, owner())
    except KeyError:
        raise ApiError("Not found", 404) from None
    except gmail.GmailError as e:
        raise ApiError(str(e), 502) from e
    scan.forget(n)
    return {"ok": True, "revoked": revoked}




def api_mailbox_scan(conn, _q, _b, mailbox_id: str) -> ScanStarted:
    """Scan the mailbox now (Scan now): it runs in the background, and Settings shows how it went. Someone else's mailbox is
    a 404, as one that isn't there."""
    n = row_id(mailbox_id)
    if not any(m["id"] == n for m in gmail.listing(conn, owner())):
        raise ApiError("Not found", 404)
    return {"started": jobs.scan_now(n)}
