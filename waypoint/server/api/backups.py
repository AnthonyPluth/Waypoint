"""Backups: downloading one, seeing what a backup file holds, and restoring one (Settings → Data)."""
from __future__ import annotations

from datetime import date, datetime

from ...storage import backup, db
from ...storage import settings_keys as sk
from ..common import ApiError, Response, download, own_session, upload
from ..contract import BackupContents, Restored

MAX_RESTORE_BODY = 200 * 1024 * 1024   # a backup file, uploaded to see what it holds or to restore it
NO_FILE = "Choose a backup file (up to 200 MB)."


def api_backup(conn, _q, _b) -> Response:
    """Everything, as a file to keep. Once it's been sent, it's "Last backup" in Settings → Data."""
    def downloaded():
        with db.session() as c:
            db.set_setting(c, sk.LAST_BACKUP, datetime.now().isoformat(timespec="seconds"))
    return download(backup.dump(conn), "application/gzip", f"waypoint-backup-{date.today().isoformat()}.json.gz", downloaded)


@own_session
@upload(MAX_RESTORE_BODY)
def api_backup_inspect(_conn, _q, raw: bytes) -> BackupContents:
    """What a backup file holds, and what's here now, shown before you restore it. The file goes up as for a restore."""
    if not raw:
        raise ApiError(NO_FILE)
    try:
        held_in = backup.preview(backup.load(raw))
    except ValueError as e:   # not a backup Waypoint can read: it says why
        raise ApiError(str(e)) from e
    with db.session() as conn:
        here = backup.counts(conn)
    return {"created": held_in["created"], "source": held_in["source"], "counts": held_in["counts"], "current": here,
            "database": "postgres" if db.using_postgres() else "sqlite"}


@own_session
@upload(MAX_RESTORE_BODY)
def api_restore(_conn, _q, raw: bytes) -> Restored:
    """Replace everything with a backup's, after saving a copy of what's here (the safety copy)."""
    if not raw:
        raise ApiError(NO_FILE)
    try:
        restored = backup.load(raw)
    except ValueError as e:
        raise ApiError(str(e)) from e
    # Once there are background jobs (a mail scan), their locks go here: nothing may write while the data is replaced,
    # or its rows would be mixed into the restored ones.
    try:
        done = backup.restore_all(restored)
    except backup.Busy as e:
        raise ApiError(str(e), 409) from e
    except ValueError as e:
        raise ApiError(str(e)) from e
    except OSError as e:
        raise ApiError(f"Couldn’t save a copy of what’s here first ({e.strerror or e}), so nothing was restored.", 500) from e
    except Exception as e:
        if db.is_busy(e):
            raise ApiError("Waypoint is busy saving something else. Try the restore again in a few seconds.", 503) from e
        raise
    return {"ok": True, "created": restored.get("created"), "source": restored.get("source"), "counts": done["counts"],
            "safety_copy": done["safety_copy"], "unreadable_secrets": done["unreadable_secrets"]}
