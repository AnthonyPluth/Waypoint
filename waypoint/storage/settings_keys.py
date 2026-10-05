"""The names of the rows in the settings table, in one place.

Settings are plain key/value rows (db.get_setting / db.set_setting), so a mistyped key isn't an error: it just reads
as never set. Every key the app uses is named here, and tests/test_settings_keys.py fails if code passes a string
literal instead. Renaming a value here orphans what's already saved, so a rename needs a migration too.
"""
from __future__ import annotations

# General preferences
LAST_BACKUP = "last_backup"   # when a backup was last downloaded from Settings (ISO, the machine's local time)

VAPID_PRIVATE_KEY = "vapid_private_key"   # web push signing key, made on first use

# Rows that hold secrets: stored encrypted (waypoint/storage/secretbox.py), and encrypted in backups too
# (waypoint/storage/backup.py).
SECRETS = frozenset({VAPID_PRIVATE_KEY})
