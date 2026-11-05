"""Single-administrator, server-side sessions for the local prototype."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

COOKIE_NAME = "seltactor_session"
SESSION_TTL = 8 * 60 * 60
LOGIN_WINDOW = 10 * 60
MAX_FAILURES = 5
ALLOWED_ORIGINS = {
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8000", "http://127.0.0.1:8000",
}
router = APIRouter(prefix="/api/auth", tags=["admin authentication"])
sessions: dict[str, dict] = {}
failures: dict[str, list[float]] = defaultdict(list)
lock = threading.RLock()


def _now() -> float:
    return time.time()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1") or len(salt) != 32 or len(expected) != 64:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def allowed_origins() -> list[str]:
    configured = os.environ.get("ALLOWED_ORIGINS")
    return [origin.strip() for origin in configured.split(",") if origin.strip()] if configured is not None else sorted(ALLOWED_ORIGINS)


def check_origin(request: Request) -> None:
    # CLI clients may omit Origin. Browser mutations must originate from our local UI.
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins():
        raise HTTPException(403, "Запрос с этого сайта запрещён.")


def current_admin(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 100:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with lock:
        session = sessions.get(digest)
        if not session:
            return None
        if session["expires"] <= _now():
            sessions.pop(digest, None)
            return None
        # Changing admin credentials invalidates all previously issued sessions.
        fingerprint = hashlib.sha256(os.environ.get("ADMIN_PASSWORD_HASH", "").encode()).hexdigest()
        if session["credential"] != fingerprint:
            sessions.pop(digest, None)
            return None
        return session["username"]


def require_admin(request: Request) -> str:
    username = current_admin(request)
    if username is None:
        raise HTTPException(401, "Для загрузки своих материалов и ИИ-анализа войдите как администратор.")
    return username


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


@router.get("/me")
def me(request: Request):
    username = current_admin(request)
    return {"is_admin": username is not None, "username": username}


@router.post("/login")
def login(payload: LoginInput, request: Request, response: Response):
    check_origin(request)
    host = request.client.host if request.client else "unknown"
    now = _now()
    with lock:
        failures[host] = [stamp for stamp in failures[host] if stamp > now - LOGIN_WINDOW]
        if len(failures[host]) >= MAX_FAILURES:
            raise HTTPException(429, "Слишком много попыток входа. Повторите через 10 минут.", headers={"Retry-After": str(LOGIN_WINDOW)})
        # Reserve a slot before the expensive hash check, including concurrent attempts.
        failures[host].append(now)
    expected_user = os.environ.get("ADMIN_USERNAME", "admin")
    encoded = os.environ.get("ADMIN_PASSWORD_HASH", "")
    password_ok = verify_password(payload.password, encoded or _DUMMY_HASH)
    username_ok = hmac.compare_digest(payload.username.encode(), expected_user.encode())
    if not (encoded and password_ok and username_ok):
        raise HTTPException(401, "Неверный логин или пароль.")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with lock:
        failures.pop(host, None)
        for expired in [key for key, value in sessions.items() if value["expires"] <= now]:
            sessions.pop(expired, None)
        if len(sessions) >= 100:
            sessions.pop(min(sessions, key=lambda key: sessions[key]["expires"]), None)
        # Do not retain a previous cookie/session after logging in again.
        previous = request.cookies.get(COOKIE_NAME)
        if previous:
            sessions.pop(hashlib.sha256(previous.encode()).hexdigest(), None)
        sessions[digest] = {"username": expected_user, "expires": now + SESSION_TTL,
                            "credential": hashlib.sha256(encoded.encode()).hexdigest()}
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True,
                        secure=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
                        samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"is_admin": True, "username": expected_user}


@router.post("/logout")
def logout(request: Request, response: Response):
    check_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with lock:
            sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"is_admin": False, "username": None}
