import base64
import json
import os
import re
import urllib.error
import urllib.request

from fastapi import APIRouter, File, HTTPException, UploadFile, status

router = APIRouter(prefix="/cable-tags", tags=["Reconocimiento de cables"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
TAG_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9._+:/-]{2,39}", re.IGNORECASE)


def _extract_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _parse_ai_result(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        candidates = TAG_PATTERN.findall(cleaned.upper())
        tag = candidates[0] if candidates else ""
        return {"tag": tag, "candidates": candidates[:5], "confidence": 0.45, "raw_text": cleaned}

    tag = str(data.get("tag") or "").strip().upper()
    candidates = [str(value).strip().upper() for value in data.get("candidates", []) if str(value).strip()]
    if tag and tag not in candidates:
        candidates.insert(0, tag)
    confidence = data.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "tag": tag,
        "candidates": candidates[:5],
        "confidence": confidence,
        "raw_text": str(data.get("raw_text") or tag).strip(),
    }


@router.post("/recognize")
async def recognize_cable_tag(image: UploadFile = File(...)):
    """Lee el TAG visible en una foto y devuelve candidatos para buscar en los planos."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Falta configurar OPENAI_API_KEY en Railway.",
        )

    content_type = (image.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Usá una imagen JPG, PNG o WEBP.")

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=422, detail="La imagen está vacía.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="La imagen supera el límite de 8 MB.")

    image_data = base64.b64encode(image_bytes).decode("ascii")
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    prompt = (
        "Leé únicamente la identificación impresa en la etiqueta industrial del cable. "
        "Conservá guiones, barras, puntos, dos puntos, signos + y mayúsculas. "
        "No inventes caracteres tapados. Respondé solo JSON válido con: "
        '{"tag":"texto principal","candidates":["alternativas"],"confidence":0.0,"raw_text":"todo lo legible"}. '
        "Si no hay un tag claro, tag debe ser una cadena vacía."
    )
    body = json.dumps({
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:{content_type};base64,{image_data}"},
            ],
        }],
        "max_output_tokens": 250,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(error_body).get("error", {}).get("message")
        except json.JSONDecodeError:
            detail = None
        raise HTTPException(status_code=502, detail=f"La IA no pudo leer la foto: {detail or 'error de API'}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="La IA tardó demasiado o no respondió.") from exc

    result = _parse_ai_result(_extract_output_text(payload))
    result["model"] = model
    if not result["tag"]:
        result["message"] = "No se pudo leer un TAG con suficiente claridad. Sacá otra foto más cerca y con buena luz."
    return result
