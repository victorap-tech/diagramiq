import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import models
from app.database import get_db
from app.routers.component_catalog import infer_type

router = APIRouter(prefix="/component-relations", tags=["Relaciones entre componentes"])

PREFIX_ROLE = {
    "interruptor": "protección/alimentación",
    "seccionador": "aislamiento/alimentación",
    "guardamotor": "protección de motor",
    "contactor": "maniobra",
    "relé": "mando",
    "relé térmico": "protección térmica",
    "fusible": "protección",
    "variador": "control de motor",
    "PLC": "control lógico",
    "módulo de entradas": "entrada de control",
    "módulo de salidas": "salida de control",
    "módulo analógico": "señal analógica",
    "motor": "carga",
    "sensor": "señal de campo",
    "bornera": "interconexión",
    "pulsador": "mando manual",
    "piloto": "señalización",
    "transformador": "alimentación",
}


def _distance(a, b):
    if None in (a.x, a.y, b.x, b.y):
        return None
    ax = a.x + (a.width or 0) / 2
    ay = a.y + (a.height or 0) / 2
    bx = b.x + (b.width or 0) / 2
    by = b.y + (b.height or 0) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _relation_hint(source_type: str, target_type: str) -> str:
    pair = (source_type, target_type)
    known = {
        ("interruptor", "contactor"): "posible alimentación/protección",
        ("guardamotor", "motor"): "posible protección del motor",
        ("contactor", "motor"): "posible maniobra del motor",
        ("relé térmico", "motor"): "posible protección térmica",
        ("variador", "motor"): "posible control del motor",
        ("PLC", "módulo de salidas"): "posible vínculo de control",
        ("módulo de salidas", "contactor"): "posible salida hacia bobina",
        ("sensor", "módulo de entradas"): "posible señal de entrada",
        ("bornera", "motor"): "posible interconexión de campo",
    }
    return known.get(pair) or known.get((target_type, source_type)) or "posible relación por proximidad"


@router.get("/{reference_id}")
def get_component_relations(reference_id: int, db: Session = Depends(get_db)):
    source = db.query(models.ComponentReference).filter(models.ComponentReference.id == reference_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Componente no encontrado")

    page = source.document_page
    source_type = infer_type(source.reference, source.detected_type, source.component_type)
    refs = (
        db.query(models.ComponentReference)
        .filter(models.ComponentReference.document_page_id == source.document_page_id)
        .filter(models.ComponentReference.id != source.id)
        .all()
    )

    source_text = " ".join(filter(None, [source.row_text, source.description])).upper()
    relations = []
    for ref in refs:
        target_type = infer_type(ref.reference, ref.detected_type, ref.component_type)
        dist = _distance(source, ref)
        mentioned = bool(ref.reference and re.search(rf"(?<![A-Z0-9]){re.escape(ref.reference.upper())}(?![A-Z0-9])", source_text))
        reverse_text = " ".join(filter(None, [ref.row_text, ref.description])).upper()
        reverse_mentioned = bool(source.reference and re.search(rf"(?<![A-Z0-9]){re.escape(source.reference.upper())}(?![A-Z0-9])", reverse_text))

        score = 0
        reasons = []
        if mentioned or reverse_mentioned:
            score += 70
            reasons.append("referencia cruzada en el texto")
        if dist is not None:
            if dist <= 180:
                score += 35
                reasons.append("muy próximo en el plano")
            elif dist <= 400:
                score += 20
                reasons.append("próximo en el plano")
            elif dist <= 800:
                score += 8
        if source_type != "otro" and target_type != "otro":
            score += 5
        if score < 10:
            continue
        relations.append({
            "id": ref.id,
            "reference": ref.reference,
            "component_type": target_type,
            "model": ref.model or "",
            "description": ref.description or ref.row_text or "",
            "distance": round(dist, 1) if dist is not None else None,
            "confidence": min(score, 99),
            "relation": _relation_hint(source_type, target_type),
            "reason": ", ".join(reasons) or "misma página",
            "x": ref.x, "y": ref.y, "width": ref.width, "height": ref.height,
        })

    relations.sort(key=lambda item: (-item["confidence"], item["distance"] if item["distance"] is not None else 999999))
    doc = page.document
    return {
        "source": {
            "id": source.id,
            "reference": source.reference,
            "component_type": source_type,
            "model": source.model or "",
            "role": PREFIX_ROLE.get(source_type, "componente"),
            "document_id": doc.id,
            "document_title": doc.title,
            "page_number": page.page_number,
        },
        "relations": relations[:20],
        "note": "Relaciones preliminares inferidas por referencias cruzadas y proximidad en la misma página. Deben verificarse en el plano.",
    }
