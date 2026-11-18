from __future__ import annotations

from ... import validate
from ...domain.mail import ai
from ...storage import db
from ...storage import settings_keys as sk
from ..common import ApiError
from ..contract import AiBody, AiSettings

_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")


def _settings(conn) -> AiSettings:
    stored = db.get_settings(conn, [sk.AI_OLLAMA_URL, sk.AI_OLLAMA_MODEL])
    return {"ollama_url": stored[sk.AI_OLLAMA_URL] or "", "ollama_model": stored[sk.AI_OLLAMA_MODEL] or ""}


def api_ai(conn, _q, _b) -> AiSettings:
    return _settings(conn)


def api_ai_save(conn, _q, body: AiBody) -> AiSettings:
    url, model = body.get("ollama_url"), body.get("ollama_model")
    for name, value in (("ollama_url", url), ("ollama_model", model)):
        if value is not None and not isinstance(value, str):
            raise ApiError(f"Send “{name}” as text")
    if url is not None:
        text = _v.text(url, "Ollama address", 200)
        cleaned = ai.clean_url(text) if text else ""
        if cleaned is None:
            raise ApiError("The Ollama address must be a web address, such as http://ollama.local:1234, with no sign-in in it")
        url = cleaned
    if model is not None:
        text = _v.text(model, "Ollama model", 100)
        if text and not ai.clean_model(text):
            raise ApiError("The Ollama model’s name can’t hold spaces or that kind of character")
        model = text or ""
    have_url = url if url is not None else db.get_setting(conn, sk.AI_OLLAMA_URL)
    have_model = model if model is not None else db.get_setting(conn, sk.AI_OLLAMA_MODEL)
    if have_url and not have_model:
        raise ApiError("Enter the model to use with the Ollama address")
    if have_model and not have_url:
        raise ApiError("Enter the Ollama address, or clear the model")
    for setting, value in ((sk.AI_OLLAMA_URL, url), (sk.AI_OLLAMA_MODEL, model)):
        if value is not None:
            db.set_setting(conn, setting, value or None)
    return _settings(conn)
