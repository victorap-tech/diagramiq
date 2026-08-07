import io
import ast
import json
import re
import logging
from difflib import SequenceMatcher

from PIL import Image, ImageOps, UnidentifiedImageError

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app import models
from app.database import get_db

from app.services.vision_provider import analyze_image as analyze_with_provider

logger = logging.getLogger("diagramiq.vision")

router = APIRouter(prefix="/vision", tags=["DiagramIQ Vision"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


VISION_BLOCKED_TERMS = {
    "PE", "N", "M", "L", "L1", "L2", "L3", "24V", "0V", "+24V",
    "BN", "BK", "BU", "GY", "RD", "WH", "GN", "YE", "SH",
}

def _norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())

def _similarity(left: object, right: object) -> float:
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.88
    return SequenceMatcher(None, a, b).ratio()

def _vision_match_score(result: dict, item: models.ComponentReference) -> tuple[int, list[str]]:
    reasons: list[str] = []
    reference = result.get("reference") or result.get("cable_tag") or ""
    model = result.get("model") or ""
    brand = result.get("brand") or ""
    component_type = result.get("component_type") or ""
    visible = result.get("visible_text") or []

    ref_score = _similarity(reference, item.reference)
    model_score = _similarity(model, item.model)
    brand_score = _similarity(brand, item.manufacturer)
    type_score = _similarity(component_type, item.detected_type or item.component_type)

    if ref_score >= 0.99:
        reasons.append("TAG exacto")
    elif ref_score >= 0.72:
        reasons.append("TAG similar")
    if model_score >= 0.99:
        reasons.append("modelo exacto")
    elif model_score >= 0.72:
        reasons.append("modelo similar")
    if brand_score >= 0.78:
        reasons.append("fabricante")
    if type_score >= 0.70:
        reasons.append("tipo")

    context = " ".join(filter(None, [item.row_text, item.description, item.model, item.manufacturer, item.detected_type]))
    visible_scores = []
    for text in visible[:12]:
        if _norm(text) in VISION_BLOCKED_TERMS:
            continue
        visible_scores.append(_similarity(text, context))
    text_score = max(visible_scores, default=0.0)
    if text_score >= 0.66:
        reasons.append("texto visible")

    weighted = (ref_score * 52) + (model_score * 25) + (brand_score * 8) + (type_score * 8) + (text_score * 7)
    if not reference:
        weighted = (model_score * 48) + (brand_score * 14) + (type_score * 18) + (text_score * 20)
    if item.x is not None and item.y is not None:
        weighted += 2
    return max(0, min(100, round(weighted))), reasons

def _serialize_vision_match(item: models.ComponentReference, score: int, reasons: list[str]) -> dict:
    page = item.document_page
    document = page.document
    sector = document.sector
    plant = sector.plant if sector else None
    organization = plant.organization if plant else None
    return {
        "similarity": score,
        "reasons": reasons,
        "reference": item.reference,
        "component_type": item.detected_type or item.component_type,
        "model": item.model,
        "manufacturer": item.manufacturer,
        "description": item.description or item.row_text,
        "document_id": document.id,
        "title": document.title,
        "filename": document.filename,
        "document_type": document.document_type,
        "page_id": page.id,
        "page_number": page.page_number,
        "page": page.page_number,
        "image_path": f"/documents/{document.id}/pages/{page.page_number}/image",
        "coordinates": {"x": item.x, "y": item.y, "width": item.width, "height": item.height},
        "sector_id": sector.id if sector else None,
        "sector_name": sector.name if sector else None,
        "plant_id": plant.id if plant else None,
        "plant_name": plant.name if plant else None,
        "organization_id": organization.id if organization else None,
        "organization_name": organization.name if organization else None,
        "match_type": "vision_component",
        "context": {
            "row_text": item.row_text, "description": item.description,
            "detected_type": item.detected_type, "model": item.model,
            "manufacturer": item.manufacturer,
        },
    }

def _find_plan_matches(db: Session, result: dict, organization_id: int | None, plant_id: int | None, sector_id: int | None) -> list[dict]:
    terms = []
    for value in [result.get("reference"), result.get("cable_tag"), result.get("model"), result.get("brand"), result.get("component_type"), *(result.get("visible_text") or [])]:
        value = str(value or "").strip()
        if not value or _norm(value) in VISION_BLOCKED_TERMS or len(_norm(value)) < 3:
            continue
        if value.lower() not in {term.lower() for term in terms}:
            terms.append(value)
    if not terms:
        return []

    query = (
        db.query(models.ComponentReference)
        .options(
            joinedload(models.ComponentReference.document_page)
            .joinedload(models.DocumentPage.document)
            .joinedload(models.Document.sector)
            .joinedload(models.Sector.plant)
            .joinedload(models.Plant.organization)
        )
        .join(models.DocumentPage)
        .join(models.Document)
        .join(models.Sector)
        .join(models.Plant)
    )
    if sector_id is not None:
        query = query.filter(models.Document.sector_id == sector_id)
    elif plant_id is not None:
        query = query.filter(models.Sector.plant_id == plant_id)
    elif organization_id is not None:
        query = query.filter(models.Plant.organization_id == organization_id)

    filters = []
    for term in terms[:10]:
        like = f"%{term}%"
        filters.extend([
            models.ComponentReference.reference.ilike(like),
            models.ComponentReference.model.ilike(like),
            models.ComponentReference.manufacturer.ilike(like),
            models.ComponentReference.detected_type.ilike(like),
            models.ComponentReference.row_text.ilike(like),
            models.ComponentReference.description.ilike(like),
        ])
    items = query.filter(or_(*filters)).limit(250).all() if filters else []

    ranked = []
    seen = set()
    for item in items:
        key = (item.document_page.document_id, item.document_page.page_number, _norm(item.reference))
        if key in seen:
            continue
        seen.add(key)
        score, reasons = _vision_match_score(result, item)
        if score < 35:
            continue
        ranked.append((score, item, reasons))
    ranked.sort(key=lambda row: (-row[0], row[1].document_page.page_number, row[1].id))
    return [_serialize_vision_match(item, score, reasons) for score, item, reasons in ranked[:8]]




def _normalize_image(image_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    """Corrige orientación, reduce fotos enormes y entrega JPEG compatible."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError):
        if content_type in {"image/jpeg", "image/png", "image/webp"}:
            return image_bytes, content_type
        raise HTTPException(415, "No se pudo interpretar la foto. Usá JPG, PNG o WEBP.")


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


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json|javascript|js)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def _balanced_json_object(text: str) -> str:
    """Devuelve el primer objeto JSON balanceado, ignorando llaves dentro de strings."""
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ""


def _sanitize_json_candidate(candidate: str) -> str:
    # Claude ocasionalmente introduce saltos/control sin escapar dentro de strings.
    output: list[str] = []
    in_string = False
    escaped = False
    for char in candidate:
        if in_string:
            if escaped:
                output.append(char)
                escaped = False
                continue
            if char == "\\":
                output.append(char)
                escaped = True
                continue
            if char == '"':
                in_string = False
                output.append(char)
                continue
            if char == "\n":
                output.append("\\n")
                continue
            if char == "\r":
                output.append("\\r")
                continue
            if char == "\t":
                output.append("\\t")
                continue
            if ord(char) < 32:
                continue
            output.append(char)
            continue
        if char == '"':
            in_string = True
        output.append(char)
    return "".join(output)


def _fallback_fields(text: str) -> dict:
    """Recupera campos útiles incluso si Claude corta o deforma el JSON."""
    def string_field(*names: str) -> str:
        for name in names:
            pattern = rf'["\']?{re.escape(name)}["\']?\s*:\s*["\']([^"\']*)'
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    confidence_match = re.search(r'["\']?confidence["\']?\s*:\s*([01](?:\.\d+)?)', text, flags=re.IGNORECASE)
    confidence = float(confidence_match.group(1)) if confidence_match else 0.0

    visible: list[str] = []
    array_match = re.search(r'["\']?visible_text["\']?\s*:\s*\[(.*?)\]', text, flags=re.IGNORECASE | re.DOTALL)
    if array_match:
        visible = [
            value.strip()
            for value in re.findall(r'["\']([^"\']+)["\']', array_match.group(1))
            if value.strip()
        ][:12]

    return {
        "detected_kind": string_field("detected_kind", "kind") or "unknown",
        "component_type": string_field("component_type", "type"),
        "reference": string_field("reference", "tag"),
        "cable_tag": string_field("cable_tag"),
        "brand": string_field("brand", "manufacturer", "marca"),
        "model": string_field("model", "modelo"),
        "visible_text": visible,
        "confidence": confidence,
        "description": string_field("description", "descripcion"),
    }


def _parse_json(text: str) -> dict:
    cleaned = _strip_code_fences(text)
    candidates = [cleaned]
    balanced = _balanced_json_object(cleaned)
    if balanced and balanced != cleaned:
        candidates.append(balanced)

    raw = None
    parse_errors: list[str] = []
    for candidate in candidates:
        for variant in (candidate, _sanitize_json_candidate(candidate)):
            try:
                parsed = json.loads(variant)
                if isinstance(parsed, dict):
                    raw = parsed
                    break
            except json.JSONDecodeError as exc:
                parse_errors.append(str(exc))
        if raw is not None:
            break

    if raw is None:
        # Última oportunidad para respuestas estilo diccionario Python.
        for candidate in candidates:
            try:
                parsed = ast.literal_eval(candidate)
                if isinstance(parsed, dict):
                    raw = parsed
                    break
            except (ValueError, SyntaxError):
                pass

    recovered = False
    if raw is None:
        raw = _fallback_fields(cleaned)
        recovered = True
        logger.warning(
            "[VISION JSON RECOVERED] parser_errors=%s response_preview=%r",
            parse_errors[-2:],
            cleaned[:1200],
        )

    def as_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0

    aliases = {
        "tag": "reference",
        "manufacturer": "brand",
        "marca": "brand",
        "modelo": "model",
        "type": "component_type",
        "kind": "detected_kind",
    }
    for source, destination in aliases.items():
        if not raw.get(destination) and raw.get(source):
            raw[destination] = raw[source]

    detected_kind = as_text(raw.get("detected_kind") or "unknown").lower()
    if detected_kind not in {"cable_tag", "component", "document", "unknown"}:
        detected_kind = "unknown"

    reference = as_text(raw.get("reference")).upper()
    cable_tag = as_text(raw.get("cable_tag")).upper()
    model = as_text(raw.get("model"))
    brand = as_text(raw.get("brand"))
    component_type = as_text(raw.get("component_type")).lower()

    visible_raw = raw.get("visible_text") or []
    if isinstance(visible_raw, str):
        visible_raw = [line.strip() for line in visible_raw.splitlines() if line.strip()]
    elif not isinstance(visible_raw, list):
        visible_raw = [visible_raw]
    visible_text = [as_text(value)[:240] for value in visible_raw if as_text(value)][:12]

    candidates_out: list[str] = []
    blocked = {"PE", "N", "L1", "L2", "L3", "24V", "0V"}
    for candidate in [cable_tag, reference, model, *visible_text]:
        normalized = as_text(candidate)
        if not normalized or normalized.upper() in blocked:
            continue
        if normalized.lower() not in {value.lower() for value in candidates_out}:
            candidates_out.append(normalized)

    search_query = candidates_out[0] if candidates_out else " ".join(
        value for value in [brand, model, component_type] if value
    ).strip()

    return {
        "detected_kind": detected_kind,
        "component_type": component_type,
        "reference": reference,
        "cable_tag": cable_tag,
        "brand": brand,
        "model": model,
        "visible_text": visible_text,
        "confidence": confidence,
        "description": as_text(raw.get("description"))[:1200],
        "search_query": search_query,
        "search_candidates": candidates_out[:8],
        "response_recovered": recovered,
    }


@router.get("/status")
def vision_status():
    from app.services.vision_provider import provider_status
    return provider_status()


@router.post("/analyze")
async def analyze_image(
    image: UploadFile = File(...),
    organization_id: int | None = Form(None),
    plant_id: int | None = Form(None),
    sector_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """Modo automático tipo Lens: detecta TAG, componente o texto de una hoja y prepara la búsqueda."""
    content_type = (image.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Usá una imagen JPG, PNG o WEBP.")

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(422, "La imagen está vacía.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "La imagen supera el límite de 8 MB.")

    image_bytes, content_type = _normalize_image(image_bytes, content_type)

    prompt = (
        "Actuá como DiagramIQ Vision, un Google Lens industrial. Analizá solamente lo visible en la foto y no inventes. "
        "Primero decidí detected_kind: cable_tag si predomina una etiqueta o identificación de cable; component si se ve un "
        "equipo industrial; document si se ve una hoja, esquema o plano; unknown si no se puede determinar. "
        "Para componentes reconocé, cuando sea posible: interruptor, disyuntor, seccionador, guardamotor, contactor, relé, "
        "relé térmico, fusible, variador, arrancador suave, PLC, módulo de entradas, módulo de salidas, fuente, sensor, bornera, "
        "motor, pulsador, piloto, transformador, HMI u otro. Leé códigos exactamente como aparecen: tags, referencias del plano, "
        "marca, modelo y textos visibles. Elegí como reference la referencia funcional (QF12, KM3, U4, PLC1) y como cable_tag el "
        "código de cable si existe. Respondé EXCLUSIVAMENTE JSON válido con: detected_kind, component_type, reference, cable_tag, "
        "brand, model, visible_text (máximo 10 textos breves, sin copiar listas completas de alarmas), confidence entre 0 y 1 y description de máximo 3 oraciones. Usá cadenas vacías si no se lee. Cerrá siempre correctamente el objeto JSON."
    )
    logger.info("[VISION ANALYZE] image_bytes=%s content_type=%s", len(image_bytes), content_type)
    try:
        ai_response = analyze_with_provider(prompt, image_bytes, content_type, max_tokens=1200)
    except HTTPException as exc:
        logger.error("[VISION ANALYZE FAILED] status=%s detail=%s", exc.status_code, exc.detail)
        raise
    except Exception as exc:
        logger.exception("[VISION ANALYZE UNEXPECTED]")
        raise HTTPException(502, f"Vision falló: {type(exc).__name__}: {exc}") from exc

    logger.info("[VISION RESPONSE] provider=%s model=%s chars=%s preview=%r", ai_response.provider, ai_response.model, len(ai_response.text), ai_response.text[:180])
    try:
        result = _parse_json(ai_response.text)
    except HTTPException:
        logger.error("[VISION JSON PARSE ERROR] provider=%s model=%s response=%r", ai_response.provider, ai_response.model, ai_response.text[:1000])
        raise
    result["matches"] = _find_plan_matches(db, result, organization_id, plant_id, sector_id)
    result["match_count"] = len(result["matches"])
    result["best_similarity"] = result["matches"][0]["similarity"] if result["matches"] else 0
    result["model_used"] = ai_response.model
    result["ai_provider"] = ai_response.provider
    if not result["search_query"]:
        result["message"] = "No se pudo leer una referencia. Acercá la cámara a la etiqueta o placa frontal."
    return result
