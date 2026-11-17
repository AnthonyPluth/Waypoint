from __future__ import annotations

from ... import validate
from ...domain.mail import ai
from ...storage import db
from ...storage import settings_keys as sk
from ..common import ApiError
from ..contract import AiBody, AiSettings

_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")


def _settings(conn) -> AiSettings:
    key_source = ai.saved_key(conn)[1]
    stored = db.get_settings(conn, [sk.AI_OLLAMA_URL, sk.AI_OLLAMA_MODEL, sk.AI_OPENROUTER_MODEL])
    return {"mode": ai.mode(conn), "ollama_url": stored[sk.AI_OLLAMA_URL] or "", "ollama_model": stored[sk.AI_OLLAMA_MODEL] or "",
            "openrouter_model": stored[sk.AI_OPENROUTER_MODEL] or "", "key": key_source}


def api_ai(conn, _q, _b) -> AiSettings:
    return _settings(conn)


def api_ai_save(conn, _q, body: AiBody) -> AiSettings:
    mode = body.get("mode")
    if mode not in ai.MODES:
        raise ApiError("Choose Off, Local or OpenRouter")
    url, model_l = body.get("ollama_url"), body.get("ollama_model")
    model_o, key = body.get("openrouter_model"), body.get("openrouter_key")
    for name, value in (("ollama_url", url), ("ollama_model", model_l), ("openrouter_model", model_o), ("openrouter_key", key)):
        if value is not None and not isinstance(value, str):
            raise ApiError(f"Send “{name}” as text")
    if url is not None:
        text = _v.text(url, "Ollama address", 200)
        cleaned = ai.clean_url(text) if text else ""
        if cleaned is None:
            raise ApiError("The Ollama address must be a web address, such as http://ollama.local:1234, with no sign-in in it")
        url = cleaned
    if model_l is not None:
        text = _v.text(model_l, "Ollama model", 100)
        if text and not ai.clean_model(text):
            raise ApiError("The Ollama model’s name can’t hold spaces or that kind of character")
        model_l = text or ""
    if model_o is not None:
        text = _v.text(model_o, "OpenRouter model", 100)
        if text and not ai.clean_model(text):
            raise ApiError("The OpenRouter model’s name can’t hold spaces or that kind of character")
        model_o = text or ""
    if key is not None:
        key = _v.text(key, "OpenRouter key", 200) or ""
    have_url = url if url is not None else db.get_setting(conn, sk.AI_OLLAMA_URL)
    have_l = model_l if model_l is not None else db.get_setting(conn, sk.AI_OLLAMA_MODEL)
    have_o = model_o if model_o is not None else db.get_setting(conn, sk.AI_OPENROUTER_MODEL)
    if mode == ai.LOCAL and not (have_url and have_l):
        raise ApiError("Enter the Ollama address and the model to use")
    if mode == ai.OPENROUTER:
        if not have_o:
            raise ApiError("Enter the OpenRouter model to use")
        if not (key or (key is None and ai.saved_key(conn)[0])):
            raise ApiError(f"Enter an OpenRouter key (or set {ai.KEY_ENV} where Waypoint runs)")
    db.set_setting(conn, sk.AI_MODE, mode)
    for setting, value in ((sk.AI_OLLAMA_URL, url), (sk.AI_OLLAMA_MODEL, model_l), (sk.AI_OPENROUTER_MODEL, model_o),
                           (sk.AI_OPENROUTER_KEY, key)):
        if value is not None:
            db.set_setting(conn, setting, value or None)
    return _settings(conn)
