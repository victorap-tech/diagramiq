"""Autenticación simple y segura para DiagramIQ.

Configuración Railway:
- DIAGRAMIQ_USER: usuario (opcional, por defecto: admin)
- DIAGRAMIQ_PASSWORD: contraseña obligatoria
- DIAGRAMIQ_AUTH_SECRET: secreto de firma opcional (recomendado). Si no se define,
  se deriva de la contraseña para no guardar sesiones en la base.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(prefix="/auth", tags=["Autenticación"])

COOKIE_NAME = "diagramiq_session"
SESSION_SECONDS = int(os.getenv("DIAGRAMIQ_SESSION_HOURS", "12")) * 3600
LOGIN_WINDOW_SECONDS = 10 * 60
LOGIN_MAX_ATTEMPTS = 5

_login_attempts: Dict[str, Deque[float]] = defaultdict(deque)


def configured_username() -> str:
    return os.getenv("DIAGRAMIQ_USER", "admin").strip() or "admin"


def configured_password() -> str:
    return os.getenv("DIAGRAMIQ_PASSWORD", "")


def auth_configured() -> bool:
    return bool(configured_password())


def _signing_secret() -> bytes:
    explicit = os.getenv("DIAGRAMIQ_AUTH_SECRET", "")
    material = explicit or ("diagramiq-session:" + configured_password())
    return hashlib.sha256(material.encode("utf-8")).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_session_token(username: str) -> str:
    issued_at = int(time.time())
    nonce = secrets.token_urlsafe(18)
    payload = f"{username}|{issued_at}|{nonce}".encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(_signing_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def validate_session_token(token: str | None) -> bool:
    if not token or not auth_configured():
        return False
    try:
        encoded, supplied_sig = token.split(".", 1)
        expected_sig = hmac.new(_signing_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(supplied_sig), expected_sig):
            return False
        payload = _b64decode(encoded).decode("utf-8")
        username, issued_at_raw, _nonce = payload.split("|", 2)
        issued_at = int(issued_at_raw)
        now = int(time.time())
        if username != configured_username():
            return False
        if issued_at > now + 60 or now - issued_at > SESSION_SECONDS:
            return False
        return True
    except Exception:
        return False


def request_is_authenticated(request: Request) -> bool:
    return validate_session_token(request.cookies.get(COOKIE_NAME))


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _check_login_rate_limit(request: Request) -> None:
    now = time.time()
    key = _client_key(request)
    attempts = _login_attempts[key]
    while attempts and attempts[0] < now - LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Esperá unos minutos y volvé a intentar.",
        )
    attempts.append(now)


def _clear_login_attempts(request: Request) -> None:
    _login_attempts.pop(_client_key(request), None)


@router.get("/status")
def auth_status(request: Request):
    return {
        "configured": auth_configured(),
        "authenticated": request_is_authenticated(request),
        "username": configured_username() if request_is_authenticated(request) else None,
    }


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not auth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Falta configurar DIAGRAMIQ_PASSWORD en Railway.",
        )

    _check_login_rate_limit(request)
    valid_user = hmac.compare_digest(username.strip(), configured_username())
    valid_password = hmac.compare_digest(password, configured_password())
    if not (valid_user and valid_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos.")

    _clear_login_attempts(request)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_token(configured_username()),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=os.getenv("DIAGRAMIQ_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"},
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
