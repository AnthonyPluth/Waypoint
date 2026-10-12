from __future__ import annotations

import time
from datetime import UTC, datetime

from ... import oidc, validate
from ...domain.mail import glance, review, scan
from ...providers import gmail
from .. import jobs
from ..common import ApiError, Response, _current, row_id
from ..contract import Disconnected, IgnoredSenders, LabelsBody, MailboxLabels, MailboxList, Ok, ReviewGlance, ScanStarted, ScanSummary, ShareBody, Started, UnignoreBody

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


def _summary(text: str | None) -> ScanSummary | None:
    found = scan.decode(text)
    return None if found is None else {"found": found.found, "read": found.read, "bookings": found.bookings, "review": found.review,
                                      "skipped": found.skipped, "capped": found.capped, "labels_dropped": found.labels_dropped,
                                      "triaged": found.triaged, "total": found.total, "not_travel": found.not_travel,
                                      "followups": found.followups, "with_facts": found.with_facts, "attached": found.attached,
                                      "ai_asked": found.ai_asked}


def api_mailboxes(conn, _q, _b) -> MailboxList:
    gmail.end_lapsed(conn)
    return {"configured": gmail.configured(),
            "mailboxes": [{"id": m["id"], "address": m["address"], "status": m["status"], "last_error": m["last_error"],
                           "last_scan": _when(m["last_scan"]), "scan_error": m["scan_error"], "scanning": scan.running(m["id"]),
                           "scan_notice": scan.notice(m["id"]), "scan_summary": _summary(m["scan_summary"]),
                           "reading_again": scan.reading_again(m["id"]),
                           "labels_picked": len(scan.decode_labels(m["scan_labels"])), "share_review": bool(m["share_review"])}
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


def api_mailbox_backfill(conn, _q, _b, mailbox_id: str) -> ScanStarted:
    n = row_id(mailbox_id)
    if not any(m["id"] == n for m in gmail.listing(conn, owner())):
        raise ApiError("Not found", 404)
    return {"started": jobs.scan_now(n, backfill=True)}


def api_mailbox_ignored(conn, _q, _b, mailbox_id: str) -> IgnoredSenders:
    n = _owned(conn, mailbox_id)
    return {"domains": [d for d in review.ignored(conn, n) if d != review.UNKNOWN_SENDER]}


def api_mailbox_review_glance(conn, _q, _b, mailbox_id: str) -> ReviewGlance:
    found = glance.glance(conn, owner(), row_id(mailbox_id), time.time())
    if found is None:
        raise ApiError("Not found", 404)
    return found


def api_mailbox_unignore(conn, _q, body: UnignoreBody, mailbox_id: str) -> ScanStarted:
    n = _owned(conn, mailbox_id)
    domain = body.get("domain")
    if not isinstance(domain, str) or not domain or len(domain) > 255:
        raise ApiError('Send "domain" as the sender’s domain')
    if not review.stop_ignoring(conn, n, domain):
        return {"started": False}
    conn.commit()
    return {"started": jobs.scan_now(n, backfill=True, sender=domain)}


MAX_LABELS = 100
NO_LABEL = "One of those labels isn’t in this mailbox any more. Reload the list and choose again."


def _owned(conn, mailbox_id: str) -> int:
    n = row_id(mailbox_id)
    if not any(m["id"] == n for m in gmail.listing(conn, owner())):
        raise ApiError("Not found", 404)
    return n


def _live_labels(conn, n: int) -> list[dict]:
    try:
        return gmail.labels(gmail.access_token(conn, n))
    except gmail.GmailError as e:
        raise ApiError(str(e), 502) from e


def api_mailbox_labels(conn, _q, _b, mailbox_id: str) -> MailboxLabels:
    n = _owned(conn, mailbox_id)
    live = _live_labels(conn, n)
    picked = set(scan.decode_labels(gmail.stored_labels(conn, n, owner())))
    return {"labels": [{"id": x["id"], "name": x["name"], "count": x["count"], "picked": x["id"] in picked} for x in live]}


def api_mailbox_labels_save(conn, _q, body: LabelsBody, mailbox_id: str) -> Ok:
    n = _owned(conn, mailbox_id)
    raw = body.get("labels")
    if not isinstance(raw, list) or len(raw) > MAX_LABELS or not all(isinstance(x, str) and 0 < len(x) <= 200 for x in raw):
        raise ApiError('Send "labels" as a list of label ids')
    if raw and not set(raw) <= {x["id"] for x in _live_labels(conn, n)}:
        raise ApiError(NO_LABEL)
    gmail.set_labels(conn, n, owner(), scan.encode_labels(raw))
    return {"ok": True}
