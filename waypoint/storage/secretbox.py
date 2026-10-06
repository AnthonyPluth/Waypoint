"""Encrypting the secrets Waypoint keeps: mailbox access, travel IDs, API keys and the push-notification signing key. A copy of the database on its own (a Postgres dump, a stolen disk image of just the
database, a misplaced file) doesn't give those away.

The key comes from WAYPOINT_SECRET_KEY (a long random string; best, since it lives apart from the data), or else from
a key file Waypoint creates next to the database (WAYPOINT_DATA/secret.key). Values are stored as "enc:v1:<Fernet token>";
anything without that prefix is plaintext from an earlier version and is encrypted at the next start (see
encrypt_stored). Backups hold the secrets encrypted too (waypoint/storage/backup.py): restoring one elsewhere needs the same
key, or the secrets are entered again.

Changing keys: set the new WAYPOINT_SECRET_KEY and keep the old one in WAYPOINT_SECRET_KEY_OLD (or keep secret.key) for
one start; Waypoint re-encrypts everything with the new key. Keep the old key as long as you keep backups made with
it: a backup's secrets are under the key of the time, and restoring one later needs that key in WAYPOINT_SECRET_KEY_OLD
for a start (encrypt_stored then moves them to the current key).
"""
from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import os
import threading
from typing import Literal, TypeGuard, overload

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select, update

from .. import monitoring
from . import settings_keys
from .models import LoyaltyId, Mailbox, Setting, StoredMessage

PREFIX = "enc:v1:"
KEY_FILE = "secret.key"
MIN_KEY_LENGTH = 32

# settings rows that hold secrets (the rest of the settings table is ordinary preferences)
SECRET_SETTINGS = settings_keys.SECRETS
# columns that hold secrets: table -> columns (a mailbox's refresh token, a loyalty or Known Traveler number, a kept message and its
# subject on its own, so a list of subjects doesn't open whole messages)
SECRET_COLUMNS = {"mailboxes": ("token",), "loyalty_ids": ("number",), "stored_messages": ("content", "subject")}

_lock = threading.Lock()
_cache: dict[tuple, MultiFernet] = {}


class SecretError(Exception):
    """A stored secret can't be decrypted with the keys Waypoint has (the key changed or was lost)."""


@functools.lru_cache(maxsize=8)
def _from_passphrase(text: str) -> bytes:
    # WAYPOINT_SECRET_KEY should be a long random string, but may be a passphrase: scrypt makes guessing it slow.
    return base64.urlsafe_b64encode(hashlib.scrypt(text.encode(), salt=b"waypoint-secretbox", n=2 ** 15, r=8, p=1,
                                                   maxmem=64 * 1024 * 1024, dklen=32))


def _from_passphrase_v1(text: str) -> bytes:
    """How earlier versions made the key (one SHA-256), still read so secrets saved then are re-encrypted at start."""
    return base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest())


def _data_dir() -> str:
    from . import db   # db imports this module
    return db.data_dir()


def key_file_path() -> str:
    return os.path.join(_data_dir(), KEY_FILE)


@overload
def _read_or_make_key_file(create: Literal[True]) -> bytes: ...
@overload
def _read_or_make_key_file(create: bool) -> bytes | None: ...
def _read_or_make_key_file(create: bool) -> bytes | None:
    path = key_file_path()
    try:
        with open(path, "rb") as f:
            return f.read().strip()
    except FileNotFoundError:
        if not create:
            return None
    key = Fernet.generate_key()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:   # another process made it first
        with open(path, "rb") as f:
            return f.read().strip()
    with os.fdopen(fd, "wb") as f:
        f.write(key + b"\n")
    return key


def check_config() -> list[str]:
    """Problems that should stop Waypoint from starting."""
    k = os.environ.get("WAYPOINT_SECRET_KEY") or ""
    if k and len(k) < MIN_KEY_LENGTH:
        return [f"WAYPOINT_SECRET_KEY must be at least {MIN_KEY_LENGTH} characters (try: openssl rand -base64 32)"]
    return []


def _box() -> MultiFernet:
    env, old = os.environ.get("WAYPOINT_SECRET_KEY") or "", os.environ.get("WAYPOINT_SECRET_KEY_OLD") or ""
    ident = (env, old, _data_dir())
    with _lock:
        if ident not in _cache:
            keys = []
            if env:
                keys += [Fernet(_from_passphrase(env)), Fernet(_from_passphrase_v1(env))]
                if old:
                    keys += [Fernet(_from_passphrase(old)), Fernet(_from_passphrase_v1(old))]
                file_key = _read_or_make_key_file(create=False)   # secrets encrypted before the env key was set
            else:
                file_key = _read_or_make_key_file(create=True)
            if file_key:
                keys.append(Fernet(file_key))
            _cache[ident] = MultiFernet(keys)
        return _cache[ident]


def _primary() -> Fernet:
    """The key new secrets are encrypted with (the first of _box's keys)."""
    env = os.environ.get("WAYPOINT_SECRET_KEY") or ""
    return Fernet(_from_passphrase(env) if env else _read_or_make_key_file(create=True))


def derived_key(purpose: str) -> bytes:
    """A key for something other than encrypting, from the current one: never that key itself, and a different one for
    each purpose (so what's made with it can't be checked against another's). It changes when the key does."""
    env = os.environ.get("WAYPOINT_SECRET_KEY") or ""
    base = _from_passphrase(env) if env else _read_or_make_key_file(create=True)
    return hmac.new(base, b"waypoint:" + purpose.encode(), hashlib.sha256).digest()


def is_encrypted(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value: str | None) -> str | None:
    if value is None or value == "" or is_encrypted(value):
        return value
    return PREFIX + _box().encrypt(str(value).encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not is_encrypted(value):
        return value
    try:
        return _box().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise SecretError("Waypoint can't unlock a saved secret with its current key (was WAYPOINT_SECRET_KEY changed, or "
                          f"{KEY_FILE} lost?). Put the old key back, or enter that key or connection again.") from e


def reencrypt(value: str | None) -> str | None:
    """Plaintext → encrypted; encrypted with an older key → encrypted with the current one."""
    if not is_encrypted(value):
        return encrypt(value)
    token = value[len(PREFIX):].encode()
    try:
        _primary().decrypt(token)
        return value   # already under the current key
    except InvalidToken:
        return PREFIX + _box().rotate(token).decode()


def encrypt_stored(conn) -> int:
    """Encrypt (or re-encrypt with the current key) every stored secret. Runs at start-up; returns how many changed."""
    changed = 0
    keys = sorted(SECRET_SETTINGS)
    for r in conn.execute(select(Setting.key, Setting.value).where(Setting.key.in_(keys))).fetchall():
        try:
            new = reencrypt(r["value"])
        except InvalidToken:
            monitoring.log(f"Warning: the saved {r['key']} can't be decrypted with the current key; enter it again in Settings.", "warning")
            continue
        if new != r["value"]:
            conn.execute(update(Setting).where(Setting.key == r["key"]).values(value=new))
            changed += 1
    for m in conn.execute(select(Mailbox.id, Mailbox.token)).fetchall():
        try:
            new = reencrypt(m["token"])
        except InvalidToken:
            monitoring.log("Warning: a saved Gmail connection can't be decrypted with the current key; connect it again in Settings.", "warning")
            continue
        if new != m["token"]:
            conn.execute(update(Mailbox).where(Mailbox.id == m["id"]).values(token=new))
            changed += 1
    for n in conn.execute(select(LoyaltyId.id, LoyaltyId.number)).fetchall():
        try:
            new = reencrypt(n["number"])
        except InvalidToken:
            monitoring.log("Warning: a saved loyalty number can't be decrypted with the current key; enter it again on People.", "warning")
            continue
        if new != n["number"]:
            conn.execute(update(LoyaltyId).where(LoyaltyId.id == n["id"]).values(number=new))
            changed += 1
    for s in conn.execute(select(StoredMessage.id, StoredMessage.content, StoredMessage.subject)).fetchall():
        try:
            new, new_subject = reencrypt(s["content"]), reencrypt(s["subject"])
        except InvalidToken:
            monitoring.log("Warning: a kept message can't be decrypted with the current key; it can't be read until that key is back.", "warning")
            continue
        if (new, new_subject) != (s["content"], s["subject"]):
            conn.execute(update(StoredMessage).where(StoredMessage.id == s["id"]).values(content=new, subject=new_subject))
            changed += 1
    return changed
