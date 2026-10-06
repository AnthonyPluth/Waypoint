from __future__ import annotations

from datetime import UTC, datetime

from ... import oidc, validate
from ...domain.mail import scan
from ...providers import gmail
from .. import jobs
from ..common import ApiError, Response, _current, row_id
from ..contract import Disconnected, MailboxList, Ok, ScanStarted, ShareBody, Started

BACK = {gmail.Declined: "denied", gmail.Refused: "refused", gmail.WrongScope: "scope"}


def owner() -> str:
    return str((getattr(_current, "user", None) or {}).get("sub") or "local")


def public_base(needed_by: str) -> str:
    base = oidc.config()["public_url"]
    if not base:
        if oidc.enabled():
            raise ApiError(f"{needed_by} needs WAYPOINT_PUBLIC_URL to be set.")
        base = f"http://{getattr(_current, 'host', None) or 'localhost'}"
    return str(base)


def redirect_uri() -> str:
    return public_base("Gmail") + "/api/mailboxes/callback"


def _when(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds") if t else None


def api_mailboxes(conn, _q, _b) -> MailboxList:
    gmail.end_lapsed(conn)
    return {"configured": gmail.configured(),
            "mailboxes": [{"id": m["id"], "address": m["address"], "status": m["status"], "last_error": m["last_error"],
                           "last_scan": _when(m["last_scan"]), "scan_error": m["scan_error"], "scanning": scan.running(m["id"]),
                           "scan_notice": scan.notice(m["id"]), "share_review": bool(m["share_review"])}
                          for m in gmail.listing(conn, owner())]}


def api_mailbox_connect(conn, _q, _b) -> Started:
    try:
        return {"url": gmail.start(conn, owner(), redirect_uri())}
    except gmail.NotConfigured as e:
        raise ApiError(str(e)) from e


def api_mailbox_callback(conn, q, _b) -> Response:
    params = {k: v[0] for k, v in q.items() if v}
    try:
        address = gmail.finish(conn, owner(), params, redirect_uri())
        for m in gmail.listing(conn, owner()):
            if m["address"] == address:
                scan.forget(m["id"])
        outcome = "connected"
    except gmail.GmailError as e:
        outcome = next((code for kind, code in BACK.items() if isinstance(e, kind)), "failed")
    return Response(b"", "text/plain", status=302, headers={"Location": f"/?gmail={outcome}#settings"})


def api_mailbox_disconnect(conn, _q, _b, mailbox_id: str) -> Disconnected:
    try:
        n = int(mailbox_id) if mailbox_id.isdigit() and len(mailbox_id) < 19 else -1
        revoked = gmail.disconnect(conn, n, owner())
    except KeyError:
        raise ApiError("Not found", 404) from None
    except gmail.GmailError as e:
        raise ApiError(str(e), 502) from e
    scan.forget(n)
    return {"ok": True, "revoked": revoked}


def api_mailbox_share(conn, _q, body: ShareBody, mailbox_id: str) -> Ok:
    if not gmail.set_share_review(conn, row_id(mailbox_id), owner(), validate.on(body.get("share"))):
        raise ApiError("Not found", 404)
    return {"ok": True}


def api_mailbox_scan(conn, _q, _b, mailbox_id: str) -> ScanStarted:
    n = row_id(mailbox_id)
    if not any(m["id"] == n for m in gmail.listing(conn, owner())):
        raise ApiError("Not found", 404)
    return {"started": jobs.scan_now(n)}


def api_mailbox_reread(conn, _q, _b, mailbox_id: str) -> ScanStarted:
    n = row_id(mailbox_id)
    if not any(m["id"] == n for m in gmail.listing(conn, owner())):
        raise ApiError("Not found", 404)
    return {"started": jobs.scan_now(n, again=True)}
