import base64
import json
import os
import re
import urllib.error
import urllib.request

from fastapi import APIRouter, File, HTTPException, UploadFile, status

router = APIRouter(prefix="/vision", tags=["DiagramIQ Vision"])

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
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "La IA respondió en un formato inesperado. Probá nuevamente.") from exc

    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0

    detected_kind = str(raw.get("detected_kind") or "unknown").strip().lower()
    if detected_kind not in {"cable_tag", "component", "document", "unknown"}:
        detected_kind = "unknown"

    reference = str(raw.get("reference") or "").strip().upper()
    cable_tag = str(raw.get("cable_tag") or "").strip().upper()
    model = str(raw.get("model") or "").strip()
    brand = str(raw.get("brand") or "").strip()
    component_type = str(raw.get("component_type") or "").strip().lower()
    visible_text = [str(v).strip() for v in (raw.get("visible_text") or []) if str(v).strip()][:15]

    candidates: list[str] = []
    for candidate in [cable_tag, reference, model, *visible_text]:
        normalized = str(candidate or "").strip()
        if normalized and normalized.lower() not in {v.lower() for v in candidates}:
            candidates.append(normalized)

    search_query = candidates[0] if candidates else " ".join(v for v in [brand, model, component_type] if v).strip()

    return {
        "detected_kind": detected_kind,
        "component_type": component_type,
        "reference": reference,
        "cable_tag": cable_tag,
        "brand": brand,
        "model": model,
        "visible_text": visible_text,
        "confidence": confidence,
        "description": str(raw.get("description") or "").strip(),
        "search_query": search_query,
        "search_candidates": candidates[:8],
    }


@router.post("/analyze")
async def analyze_image(image: UploadFile = File(...)):
    """Modo automático tipo Lens: detecta TAG, componente o texto de una hoja y prepara la búsqueda."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Falta configurar OPENAI_API_KEY en Railway.",
        )

    content_type = (image.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Usá una imagen JPG, PNG o WEBP.")

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(422, "La imagen está vacía.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "La imagen supera el límite de 8 MB.")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    prompt = (
        "Actuá como DiagramIQ Vision, un Google Lens industrial. Analizá solamente lo visible en la foto y no inventes. "
        "Primero decidí detected_kind: cable_tag si predomina una etiqueta o identificación de cable; component si se ve un "
        "equipo industrial; document si se ve una hoja, esquema o plano; unknown si no se puede determinar. "
        "Para componentes reconocé, cuando sea posible: interruptor, disyuntor, seccionador, guardamotor, contactor, relé, "
        "relé térmico, fusible, variador, arrancador suave, PLC, módulo de entradas, módulo de salidas, fuente, sensor, bornera, "
        "motor, pulsador, piloto, transformador, HMI u otro. Leé códigos exactamente como aparecen: tags, referencias del plano, "
        "marca, modelo y textos visibles. Elegí como reference la referencia funcional (QF12, KM3, U4, PLC1) y como cable_tag el "
        "código de cable si existe. Respondé EXCLUSIVAMENTE JSON válido con: detected_kind, component_type, reference, cable_tag, "
        "brand, model, visible_text (lista), confidence entre 0 y 1 y description breve. Usá cadenas vacías si no se lee."
    )
    body = json.dumps({
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:{content_type};base64,{encoded}"},
            ],
        }],
        "max_output_tokens": 500,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(error_body).get("error", {}).get("message")
        except json.JSONDecodeError:
            detail = None
        raise HTTPException(502, f"DiagramIQ Vision no pudo analizar la foto: {detail or 'error de API'}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(504, "DiagramIQ Vision tardó demasiado o no respondió.") from exc

    result = _parse_json(_extract_output_text(payload))
    result["model_used"] = model
    if not result["search_query"]:
        result["message"] = "No se pudo leer una referencia. Acercá la cámara a la etiqueta o placa frontal."
    return result
