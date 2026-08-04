import json
import re

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.vision_provider import analyze_image as analyze_with_provider

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
    content_type = (image.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Usá una imagen JPG, PNG o WEBP.")

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=422, detail="La imagen está vacía.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="La imagen supera el límite de 8 MB.")

    prompt = (
        "Analizá la foto de un tablero o componente industrial. Identificá únicamente lo visible, sin inventar. "
        "Clasificá el equipo en uno de estos tipos cuando corresponda: interruptor, guardamotor, contactor, "
        "relé, relé térmico, fusible, variador, arrancador suave, PLC, módulo de entradas, módulo de salidas, "
        "fuente, sensor, bornera, motor, pulsador, piloto, transformador u otro. "
        "Leé la referencia del plano o etiqueta (por ejemplo QF12, KM3, VFD1), marca, modelo y textos visibles. "
        "Respondé exclusivamente JSON válido con las claves: component_type, reference, brand, model, "
        "visible_text (lista), confidence entre 0 y 1, description breve. Usá cadenas vacías cuando no sea legible."
    )
    ai_response = analyze_with_provider(prompt, image_bytes, content_type, max_tokens=400)

    result = _clean_json(ai_response.text)
    result["model_used"] = ai_response.model
    result["ai_provider"] = ai_response.provider
    if not result["search_query"]:
        result["message"] = "No se pudo identificar texto suficiente. Sacá otra foto enfocando la etiqueta frontal."
    return result
