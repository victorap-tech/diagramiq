import base64
import json
import os
import re
import urllib.error
import urllib.request

from fastapi import APIRouter, File, HTTPException, UploadFile, status

router = APIRouter(prefix="/components", tags=["Reconocimiento de componentes"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


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


def _clean_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="La IA respondió en un formato inesperado. Probá nuevamente.") from exc

    confidence = data.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0

    reference = str(data.get("reference") or "").strip().upper()
    model = str(data.get("model") or "").strip()
    brand = str(data.get("brand") or "").strip()
    component_type = str(data.get("component_type") or "componente").strip().lower()
    visible_text = [str(v).strip() for v in data.get("visible_text", []) if str(v).strip()][:12]

    search_query = reference or model
    if not search_query:
        search_query = " ".join([brand, component_type]).strip()

    return {
        "component_type": component_type,
        "reference": reference,
        "brand": brand,
        "model": model,
        "visible_text": visible_text,
        "confidence": confidence,
        "search_query": search_query,
        "description": str(data.get("description") or "").strip(),
    }


@router.post("/recognize")
async def recognize_component(image: UploadFile = File(...)):
    """Identifica visualmente un componente industrial y devuelve datos útiles para buscarlo en los planos."""
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
        "Analizá la foto de un tablero o componente industrial. Identificá únicamente lo visible, sin inventar. "
        "Clasificá el equipo en uno de estos tipos cuando corresponda: interruptor, guardamotor, contactor, "
        "relé, relé térmico, fusible, variador, arrancador suave, PLC, módulo de entradas, módulo de salidas, "
        "fuente, sensor, bornera, motor, pulsador, piloto, transformador u otro. "
        "Leé la referencia del plano o etiqueta (por ejemplo QF12, KM3, VFD1), marca, modelo y textos visibles. "
        "Respondé exclusivamente JSON válido con las claves: component_type, reference, brand, model, "
        "visible_text (lista), confidence entre 0 y 1, description breve. Usá cadenas vacías cuando no sea legible."
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
        "max_output_tokens": 400,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
        raise HTTPException(status_code=502, detail=f"La IA no pudo analizar la foto: {detail or 'error de API'}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="La IA tardó demasiado o no respondió.") from exc

    result = _clean_json(_extract_output_text(payload))
    result["model_used"] = model
    if not result["search_query"]:
        result["message"] = "No se pudo identificar texto suficiente. Sacá otra foto enfocando la etiqueta frontal."
    return result
