"""Proveedor de visión configurable para DiagramIQ.

Soporta OpenAI Responses API y Anthropic Messages API sin agregar SDKs,
para mantener el despliegue liviano en Railway.
"""
from __future__ import annotations

import base64
import json
import os
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from fastapi import HTTPException, status

logger = logging.getLogger("diagramiq.ai")


@dataclass(frozen=True)
class VisionResponse:
    text: str
    provider: str
    model: str
    truncated: bool = False


def _selected_provider() -> str:
    provider = os.getenv("AI_PROVIDER", "openai").strip().lower()
    aliases = {"claude": "anthropic", "open_ai": "openai"}
    provider = aliases.get(provider, provider)
    if provider not in {"openai", "anthropic"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI_PROVIDER debe ser 'openai' o 'anthropic'.",
        )
    return provider


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:300] or "error de API"
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "error de API")
    return str(payload.get("message") or error or "error de API")


def _extract_openai_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _extract_anthropic_text(payload: dict) -> str:
    """Extrae texto de respuestas Anthropic tolerando bloques adicionales.

    Claude puede devolver bloques de texto junto con bloques de pensamiento u otros
    tipos. Solo exponemos texto visible, pero aceptamos pequeñas variaciones del
    formato para evitar falsos 502 ante una respuesta válida.
    """
    parts: list[str] = []
    content = payload.get("content", [])
    if isinstance(content, str):
        return content.strip()
    for block in content or []:
        if isinstance(block, str):
            if block.strip():
                parts.append(block.strip())
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
            continue
        nested = block.get("content")
        if isinstance(nested, str) and nested.strip():
            parts.append(nested.strip())
    return "\n".join(parts).strip()


def _call_openai(prompt: str, image_bytes: bytes, content_type: str, max_tokens: int) -> VisionResponse:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "Falta configurar OPENAI_API_KEY en Railway.")
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    body = json.dumps({
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:{content_type};base64,{encoded}"},
            ],
        }],
        "max_output_tokens": max_tokens,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"OpenAI no pudo analizar la foto: {_http_error_detail(exc)}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(504, "OpenAI tardó demasiado o no respondió.") from exc
    text = _extract_openai_text(payload)
    if not text:
        raise HTTPException(502, "OpenAI respondió sin texto utilizable.")
    return VisionResponse(text=text, provider="openai", model=model)


def _call_anthropic(prompt: str, image_bytes: bytes, content_type: str, max_tokens: int) -> VisionResponse:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "Falta configurar ANTHROPIC_API_KEY en Railway.")
    model = os.getenv("ANTHROPIC_VISION_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": encoded,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"Anthropic no pudo analizar la foto: {_http_error_detail(exc)}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(504, "Anthropic tardó demasiado o no respondió.") from exc
    text = _extract_anthropic_text(payload)
    if not text:
        raise HTTPException(502, "Anthropic respondió sin texto utilizable.")
    return VisionResponse(text=text, provider="anthropic", model=model)


def analyze_image(prompt: str, image_bytes: bytes, content_type: str, max_tokens: int = 500) -> VisionResponse:
    provider = _selected_provider()
    if provider == "anthropic":
        return _call_anthropic(prompt, image_bytes, content_type, max_tokens)
    return _call_openai(prompt, image_bytes, content_type, max_tokens)


def provider_status() -> dict:
    provider = _selected_provider()
    configured = bool(
        os.getenv("ANTHROPIC_API_KEY", "").strip()
        if provider == "anthropic"
        else os.getenv("OPENAI_API_KEY", "").strip()
    )
    return {"provider": provider, "configured": configured}


def _call_openai_text(prompt: str, max_tokens: int) -> VisionResponse:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "Falta configurar OPENAI_API_KEY en Railway.")
    model = os.getenv("OPENAI_TEXT_MODEL", os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")).strip() or "gpt-4.1-mini"
    body = json.dumps({
        "model": model,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "max_output_tokens": max_tokens,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"OpenAI no pudo responder: {_http_error_detail(exc)}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(504, "OpenAI tardó demasiado o no respondió.") from exc
    text = _extract_openai_text(payload)
    if not text:
        raise HTTPException(502, "OpenAI respondió sin texto utilizable.")
    truncated = payload.get("status") == "incomplete" or bool(payload.get("incomplete_details"))
    return VisionResponse(text=text, provider="openai", model=model, truncated=truncated)


def _call_anthropic_text(prompt: str, max_tokens: int) -> VisionResponse:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "Falta configurar ANTHROPIC_API_KEY en Railway.")
    model = os.getenv("ANTHROPIC_TEXT_MODEL", os.getenv("ANTHROPIC_VISION_MODEL", "claude-sonnet-5")).strip() or "claude-sonnet-5"

    # Dos intentos: Anthropic puede devolver ocasionalmente una respuesta 200 sin
    # bloque de texto. El segundo intento pide una salida exclusivamente textual
    # y evita que una falla transitoria deje inutilizable el asistente.
    last_payload: dict = {}
    for attempt in range(2):
        effective_prompt = prompt
        effective_tokens = max_tokens
        if attempt == 1:
            effective_prompt = (
                prompt
                + "\n\nIMPORTANTE: respondé ahora únicamente con texto visible en español; "
                  "no devuelvas herramientas, JSON ni una respuesta vacía."
            )
            effective_tokens = max(700, min(max_tokens, 1800))

        body = json.dumps({
            "model": model,
            "max_tokens": effective_tokens,
            "messages": [{"role": "user", "content": [{"type": "text", "text": effective_prompt}]}],
        }).encode("utf-8")
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                raw = response.read().decode("utf-8", errors="replace")
                payload = json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = _http_error_detail(exc)
            logger.warning("Anthropic HTTP error attempt=%s model=%s detail=%s", attempt + 1, model, detail)
            if attempt == 0 and exc.code in {408, 409, 429, 500, 502, 503, 529}:
                time.sleep(1.0)
                continue
            raise HTTPException(502, f"Anthropic no pudo responder (HTTP {exc.code}): {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning("Anthropic network error attempt=%s model=%s error=%r", attempt + 1, model, exc)
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise HTTPException(504, "Anthropic tardó demasiado o no respondió.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Anthropic invalid JSON attempt=%s model=%s", attempt + 1, model)
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise HTTPException(502, "Anthropic devolvió una respuesta inválida.") from exc

        last_payload = payload if isinstance(payload, dict) else {}
        text = _extract_anthropic_text(last_payload)
        if text:
            truncated = last_payload.get("stop_reason") == "max_tokens"
            return VisionResponse(text=text, provider="anthropic", model=model, truncated=truncated)

        logger.warning(
            "Anthropic empty text attempt=%s model=%s stop_reason=%s response_type=%s content_types=%s",
            attempt + 1,
            model,
            last_payload.get("stop_reason"),
            last_payload.get("type"),
            [block.get("type") for block in last_payload.get("content", []) if isinstance(block, dict)],
        )
        if attempt == 0:
            time.sleep(0.5)

    stop_reason = last_payload.get("stop_reason") or "desconocido"
    raise HTTPException(502, f"Anthropic respondió sin texto utilizable (motivo: {stop_reason}).")


def ask_text(prompt: str, max_tokens: int | None = None) -> VisionResponse:
    if max_tokens is None:
        try:
            max_tokens = int(os.getenv("AI_TEXT_MAX_TOKENS", "1800"))
        except ValueError:
            max_tokens = 1800
        max_tokens = max(600, min(max_tokens, 4000))
    provider = _selected_provider()
    if provider == "anthropic":
        return _call_anthropic_text(prompt, max_tokens)
    return _call_openai_text(prompt, max_tokens)
