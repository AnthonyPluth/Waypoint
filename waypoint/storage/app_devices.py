from __future__ import annotations

from . import secretbox
from .models import AppDevice


def seal(secret: str) -> str:
    return secretbox.encrypt(secret) or ""


def secret_of(device: AppDevice) -> str:
    return secretbox.decrypt(device.secret) or ""
