"""Proveedor de visión configurable para DiagramIQ.

Soporta OpenAI Responses API y Anthropic Messages API sin agregar SDKs,
para mantener el despliegue liviano en Railway.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from fastapi import HTTPException, status


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
    parts: list[str] = []
    for block in payload.get("content", []) or []:
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"].strip())
    return "\n".join(part for part in parts if part).strip()


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
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
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
        raise HTTPException(502, f"Anthropic no pudo responder: {_http_error_detail(exc)}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(504, "Anthropic tardó demasiado o no respondió.") from exc
    text = _extract_anthropic_text(payload)
    if not text:
        raise HTTPException(502, "Anthropic respondió sin texto utilizable.")
    truncated = payload.get("stop_reason") == "max_tokens"
    return VisionResponse(text=text, provider="anthropic", model=model, truncated=truncated)


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
