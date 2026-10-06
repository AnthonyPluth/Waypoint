from __future__ import annotations

import base64
import ipaddress
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt
from sqlalchemy import delete, insert, select, update

from .domain import people
from .storage import db, secretbox
from . import tls
from .storage.models import AuthPending, AuthSession, User


LOGIN_TTL = 600
MAX_PENDING = 10000
SESSION_RENEW_AFTER = 86400
SESSION_MAX_DAYS = 90
_discovery: dict = {}
_jwks: dict = {}


class OIDCError(Exception):
    pass


class NotAllowed(OIDCError):

    def __init__(self, who: str):
        super().__init__(f"{who} isn’t allowed to use this Waypoint.")
        self.who = who


def config() -> dict:
    e = os.environ.get
    split = lambda v: {x.strip().lower() for x in (v or "").split(",") if x.strip()}
    public = (e("WAYPOINT_PUBLIC_URL") or "").rstrip("/")
    return {
        "issuer": (e("OIDC_ISSUER") or "").strip(),
        "client_id": (e("OIDC_CLIENT_ID") or "").strip(),
        "client_secret": e("OIDC_CLIENT_SECRET") or "",
        "public_url": public,
        "redirect_uri": f"{public}/auth/callback" if public else "",
        "scopes": e("OIDC_SCOPES") or "openid email profile",
        "emails": split(e("OIDC_ALLOWED_EMAILS")),
        "groups": split(e("OIDC_ALLOWED_GROUPS")),
        "any_user": e("OIDC_ALLOW_ANY_USER") == "1",
        "trust_unverified_email": e("OIDC_TRUST_UNVERIFIED_EMAIL") == "1",
        "session_days": int(e("WAYPOINT_SESSION_DAYS") or 14),
        "secure_cookie": public.startswith("https://"),
    }


def local_host(host: str) -> bool:
    host = host.strip("[]").lower()
    if host == "localhost" or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return host.endswith((".local", ".lan", ".home.arpa", ".internal", ".ts.net"))


def enabled() -> bool:
    return bool(os.environ.get("OIDC_ISSUER"))


def check_config() -> list[str]:
    c = config()
    problems = []
    for key, env in (("issuer", "OIDC_ISSUER"), ("client_id", "OIDC_CLIENT_ID"), ("public_url", "WAYPOINT_PUBLIC_URL")):
        if not c[key]:
            problems.append(f"{env} is not set")
    if c["public_url"] and not c["public_url"].startswith(("http://", "https://")):
        problems.append("WAYPOINT_PUBLIC_URL must start with http:// or https://")
    elif (c["public_url"].startswith("http://") and not local_host(urllib.parse.urlsplit(c["public_url"]).hostname or "")
          and os.environ.get("WAYPOINT_ALLOW_INSECURE_HTTP") != "1"):
        problems.append("WAYPOINT_PUBLIC_URL must use https:// for an address reachable from the internet (put Waypoint behind "
                        "a reverse proxy with a certificate), or set WAYPOINT_ALLOW_INSECURE_HTTP=1 if you really mean it")
    if not (c["emails"] or c["groups"] or c["any_user"]):
        problems.append("set OIDC_ALLOWED_EMAILS and/or OIDC_ALLOWED_GROUPS (or OIDC_ALLOW_ANY_USER=1) so only you get in")
    return problems


def _get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Waypoint/0.1", **(headers or {})})
    with tls.urlopen(req, timeout=15, allow_http=True) as r:
        return json.loads(r.read().decode())


def discovery() -> dict:
    c = config()
    cached = _discovery.get(c["issuer"])
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    url = c["issuer"].rstrip("/") + "/.well-known/openid-configuration"
    try:
        d = _get_json(url)
    except (urllib.error.URLError, ValueError, OSError) as e:
        raise OIDCError(f"Couldn't read the provider's settings at {url}: {e}") from e
    if d.get("issuer", "").rstrip("/") != c["issuer"].rstrip("/"):
        raise OIDCError(f"The provider says its issuer is {d.get('issuer')!r}, not {c['issuer']!r}. Check OIDC_ISSUER.")
    _discovery[c["issuer"]] = (time.time(), d)
    return d


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_login(conn, next_path: str = "/", choose_account: bool = False) -> tuple[str, str]:
    c, d = config(), discovery()
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64e(hashlib.sha256(verifier.encode()).digest())
    next_path = safe_next(next_path)
    conn.execute(delete(AuthPending).where(AuthPending.created < time.time() - LOGIN_TTL))
    conn.execute(delete(AuthPending).where(AuthPending.state.in_(
        select(AuthPending.state).order_by(AuthPending.created.desc()).offset(MAX_PENDING - 1))))
    conn.execute(insert(AuthPending).values(state=state, nonce=nonce, verifier=verifier, next=next_path, created=time.time()))
    params = {"response_type": "code", "client_id": c["client_id"], "redirect_uri": c["redirect_uri"],
              "scope": c["scopes"], "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    if choose_account and (prompt := _choose_account_prompt(d)):
        params["prompt"] = prompt
    return d["authorization_endpoint"] + ("&" if "?" in d["authorization_endpoint"] else "?") + urllib.parse.urlencode(params), state


def _choose_account_prompt(d: dict) -> str | None:
    supported = d.get("prompt_values_supported")
    if not isinstance(supported, list):
        return "select_account"
    return next((p for p in ("select_account", "login") if p in supported), None)


def safe_next(next_path: str | None) -> str:
    p = next_path or "/"
    if (not p.startswith("/") or p.startswith("//") or "\\" in p or any(ord(ch) < 32 or ord(ch) == 127 for ch in p)
            or len(p) > 2000):
        return "/"
    return p


def finish_login(conn, params: dict, login_cookie: str | None) -> tuple[str, str]:
    if params.get("error"):
        raise OIDCError(f"The provider said: {params.get('error_description') or params['error']}")
    state, code = params.get("state") or "", params.get("code") or ""
    if not state or not code:
        raise OIDCError("The sign-in response was missing its code. Please try again.")
    if not login_cookie or not secrets.compare_digest(login_cookie, state):
        raise OIDCError("This sign-in didn't start in this browser (or took too long). Please try again.")
    row = conn.execute(select(AuthPending).where(AuthPending.state == state)).fetchone()
    conn.execute(delete(AuthPending).where(AuthPending.state == state))
    if not row or time.time() - row["created"] > LOGIN_TTL:
        raise OIDCError("That sign-in link has expired. Please try again.")
    conn.commit()

    c, d = config(), discovery()
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": c["redirect_uri"], "code_verifier": row["verifier"]}
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": "Waypoint/0.1"}
    methods = d.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    if c["client_secret"] and "client_secret_basic" in methods:
        headers["Authorization"] = "Basic " + base64.b64encode(
            f"{urllib.parse.quote(c['client_id'], safe='')}:{urllib.parse.quote(c['client_secret'], safe='')}".encode()).decode()
    else:
        form["client_id"] = c["client_id"]
        if c["client_secret"]:
            form["client_secret"] = c["client_secret"]
    req = urllib.request.Request(d["token_endpoint"], data=urllib.parse.urlencode(form).encode(), headers=headers, method="POST")
    try:
        with tls.urlopen(req, timeout=15, allow_http=True) as r:
            tokens = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise OIDCError(f"The provider refused the sign-in ({e.code}: {detail}). Check the client ID, secret and redirect URI.") from e
    except (urllib.error.URLError, OSError) as e:
        raise OIDCError(f"Couldn't reach the provider: {e}") from e

    claims = verify_id_token(tokens.get("id_token") or "", row["nonce"], d)
    info = dict(claims)
    if tokens.get("access_token") and d.get("userinfo_endpoint") and not (claims.get("email") and "groups" in claims):
        try:
            ui = _get_json(d["userinfo_endpoint"], {"Authorization": f"Bearer {tokens['access_token']}"})
            if ui.get("sub") == claims.get("sub"):
                info = {**ui, **claims, "groups": claims.get("groups", ui.get("groups"))}
        except (urllib.error.URLError, ValueError, OSError):
            pass
    who = authorize(info)
    token = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute(insert(AuthSession).values(
        token_hash=_hash(token), sub=who["sub"], email=who["email"], name=who["name"], created=now,
        expires=now + c["session_days"] * 86400,
        id_token=secretbox.encrypt(tokens.get("id_token"))))
    remember_user(conn, who["sub"], who["email"], who["name"], info.get("given_name"), now)
    return token, safe_next(row["next"])


def first_name(name: str | None, email: str | None, given: str | None = None) -> str:
    if given and given.strip():
        return given.strip().split()[0]
    if name and name.strip() and "@" not in name:
        return name.strip().split()[0]
    local = (email or "").split("@")[0]
    return (local.split(".")[0].split("_")[0] or "Someone").capitalize()


def remember_user(conn, sub, email, name, given=None, when=None) -> None:
    if not sub:
        return
    first = first_name(name, email, given)
    db.upsert(conn, User, {"sub": sub, "email": email, "name": name, "first_name": first,
                           "last_seen": when or time.time()}, key=["sub"])
    people.ensure_member(conn, sub, name or email or sub, first)


def authorize(info: dict) -> dict:
    c = config()
    email = (info.get("email") or "").strip().lower()
    groups = info.get("groups") or []
    if isinstance(groups, str):
        groups = [groups]
    groups = {str(g).strip().lower() for g in groups}
    verified = info.get("email_verified") is True or str(info.get("email_verified")).lower() == "true"
    email_ok = bool(email) and email in c["emails"] and (verified or c["trust_unverified_email"])
    ok = c["any_user"] or email_ok or bool(groups & c["groups"])
    if not ok and email and email in c["emails"]:
        raise OIDCError(f"The provider hasn't said {email} is verified, so Waypoint can't let it in. If your provider never "
                        "sends email_verified and nobody can change their own email there, set OIDC_TRUST_UNVERIFIED_EMAIL=1.")
    if not ok:
        raise NotAllowed(email or str(info.get("sub")))
    return {"sub": str(info.get("sub")), "email": email or None,
            "name": info.get("name") or info.get("preferred_username") or email or str(info.get("sub"))}


ASYMMETRIC = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
SYMMETRIC = {"HS256", "HS384", "HS512"}


def _signing_key(kid: str | None, alg: str, d: dict):
    uri = d.get("jwks_uri")
    if not uri:
        raise OIDCError("The provider doesn't publish its signing keys (no jwks_uri).")
    for refresh in (False, True):
        if uri not in _jwks or refresh:
            try:
                _jwks[uri] = jwt.PyJWKSet.from_dict(_get_json(uri))
            except (jwt.PyJWKSetError, urllib.error.URLError, ValueError, OSError) as e:
                raise OIDCError(f"Couldn't read the provider's signing keys: {e}") from e
        keys = [k for k in _jwks[uri].keys if (not kid or k.key_id == kid) and k.public_key_use in (None, "sig")]
        if keys:
            return keys[0].key
    raise OIDCError("The ID token was signed with a key the provider doesn't publish.")


def verify_id_token(id_token: str, nonce: str, d: dict) -> dict:
    c = config()
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.DecodeError as e:
        raise OIDCError("The provider didn't return a readable ID token.") from e
    alg = header.get("alg")
    if alg in ASYMMETRIC:
        key = _signing_key(header.get("kid"), alg, d)
    elif alg in SYMMETRIC and c["client_secret"]:
        key = c["client_secret"]
    else:
        raise OIDCError(f"Unsupported ID token signature ({alg}).")
    try:
        claims = jwt.decode(id_token, key, algorithms=[alg], audience=c["client_id"], leeway=60,
                            options={"require": ["iss", "sub", "aud", "exp", "iat"], "verify_iss": False})
    except jwt.ExpiredSignatureError as e:
        raise OIDCError("The ID token has expired. Check this machine's clock.") from e
    except jwt.ImmatureSignatureError as e:
        raise OIDCError("The ID token is dated in the future. Check this machine's clock.") from e
    except (jwt.InvalidAudienceError, jwt.MissingRequiredClaimError) as e:
        raise OIDCError(f"The ID token is meant for a different app, or is missing details ({e}).") from e
    except jwt.InvalidSignatureError as e:
        raise OIDCError("The ID token's signature didn't check out.") from e
    except jwt.InvalidTokenError as e:
        raise OIDCError(f"The ID token isn't valid: {e}") from e
    if str(claims.get("iss", "")).rstrip("/") != c["issuer"].rstrip("/"):
        raise OIDCError("The ID token is from a different issuer.")
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") not in (None, c["client_id"]):
        raise OIDCError("The ID token is meant for a different app.")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OIDCError("The ID token doesn't belong to this sign-in.")
    return claims


def session_user(conn, token: str | None) -> dict | None:
    if not token:
        return None
    row = conn.execute(select(AuthSession).where(AuthSession.token_hash == _hash(token))).fetchone()
    if not row:
        return None
    if row["expires"] < time.time() or not still_allowed(row["email"]):
        conn.execute(delete(AuthSession).where(AuthSession.token_hash == row["token_hash"]))
        return None
    return {"sub": row["sub"], "email": row["email"], "name": row["name"]}


def renew_session(conn, token: str | None) -> int | None:
    if not token:
        return None
    c = config()
    row = conn.execute(select(AuthSession.expires, AuthSession.created, AuthSession.email)
                       .where(AuthSession.token_hash == _hash(token))).fetchone()
    now, life = time.time(), c["session_days"] * 86400
    if not row or row["expires"] < now or row["expires"] > now + life - SESSION_RENEW_AFTER:
        return None
    if not (c["any_user"] or (row["email"] or "").lower() in c["emails"]):
        return None
    expires = min(now + life, (row["created"] or now) + max(SESSION_MAX_DAYS * 86400, life))
    if expires <= row["expires"]:
        return None
    conn.execute(update(AuthSession).where(AuthSession.token_hash == _hash(token)).values(expires=expires))
    return int(expires - now)


def known_only_at_sign_in() -> bool:
    c = config()
    return bool(c["groups"]) and not c["any_user"]


def still_allowed(email: str | None) -> bool:
    c = config()
    if c["any_user"] or c["groups"]:
        return True
    return bool(email and email.lower() in c["emails"])


def access_lapsed(conn, sub: str | None, email: str | None, now: float | None = None) -> str | None:
    if not enabled():
        return None
    if not still_allowed(email):
        return "user_removed"
    if known_only_at_sign_in():
        now = time.time() if now is None else now
        seen = conn.execute(select(User.last_seen).where(User.sub == sub)).scalar() if sub else None
        if seen is None or now - seen > config()["session_days"] * 86400:
            return "sign_in_lapsed"
    return None


def provider_sign_out(c: dict | None = None) -> str | None:
    c = c or config()
    try:
        end = discovery().get("end_session_endpoint")
    except OIDCError:
        return None
    if not end:
        return None
    q = {"client_id": c["client_id"], "post_logout_redirect_uri": c["public_url"] + "/auth/signed-out"}
    return end + ("&" if "?" in end else "?") + urllib.parse.urlencode(q)


def logout(conn, token: str | None) -> str:
    id_token = None
    if token:
        row = conn.execute(select(AuthSession.id_token).where(AuthSession.token_hash == _hash(token))).fetchone()
        try:
            id_token = secretbox.decrypt(row["id_token"]) if row else None
        except secretbox.SecretError:
            id_token = None
        conn.execute(delete(AuthSession).where(AuthSession.token_hash == _hash(token)))
    conn.execute(delete(AuthSession).where(AuthSession.expires < time.time()))
    end = provider_sign_out()
    if end and id_token:
        end += "&" + urllib.parse.urlencode({"id_token_hint": id_token})
    return end or "/auth/signed-out"
