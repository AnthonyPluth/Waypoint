"""The names of the rows in the settings table, in one place.

Settings are plain key/value rows (db.get_setting / db.set_setting), so a mistyped key isn't an error: it just reads
as never set. Every key the app uses is named here, and tests/test_settings_keys.py fails if code passes a string
literal instead. Renaming a value here orphans what's already saved, so a rename needs a migration too.
"""
from __future__ import annotations

# General preferences
LAST_BACKUP = "last_backup"   # when a backup was last downloaded from Settings (ISO, the machine's local time)

DISTANCE_UNIT = "distance_unit"   # the household's unit for distances in the stats: "mi" (the default) or "km"

# Flight status (waypoint/domain/flightstatus.py): the calls made this month (the month is "YYYY-MM", local time), and
# when fetching is paused (a JSON object: until, as seconds since the epoch, and why)
FLIGHT_STATUS_MONTH = "flight_status_month"
FLIGHT_STATUS_CALLS = "flight_status_calls"
FLIGHT_STATUS_PAUSED = "flight_status_paused"

# The optional AI fallback for the "Couldn't read" queue (waypoint/domain/mail/ai.py): off, local (Ollama) or openrouter, with
# where and which model; the OpenRouter key may instead come from the environment (OPENROUTER_API_KEY)
AI_MODE = "ai_mode"
AI_OLLAMA_URL = "ai_ollama_url"
AI_OLLAMA_MODEL = "ai_ollama_model"
AI_OPENROUTER_MODEL = "ai_openrouter_model"
AI_OPENROUTER_KEY = "ai_openrouter_key"

# AI assistants (waypoint/server/mcp_access.py): the household's switch, off until turned on ("1" is on)
MCP_ALLOW_WRITES = "mcp_allow_writes"   # "Let assistants change trips"

# Brand logos (waypoint/domain/logos.py): Logo.dev's publishable key (pk_..., to fetch a logo) and optional secret key (sk_...,
# Brand Search, for better matches on hotel names), and why the last lookup failed (fixed text, never a name)
LOGODEV_TOKEN = "logodev_token"
LOGODEV_SECRET = "logodev_secret"
LOGODEV_LAST_ERROR = "logodev_last_error"

VAPID_PRIVATE_KEY = "vapid_private_key"   # web push signing key, made on first use

# Rows that hold secrets: stored encrypted (waypoint/storage/secretbox.py), and encrypted in backups too
# (waypoint/storage/backup.py).
SECRETS = frozenset({VAPID_PRIVATE_KEY, AI_OPENROUTER_KEY, LOGODEV_TOKEN, LOGODEV_SECRET})
