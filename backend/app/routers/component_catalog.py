from collections import Counter
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app import models
from app.database import get_db

router = APIRouter(prefix="/component-catalog", tags=["Catálogo de componentes"])

TYPE_MAP = {
    "qf": "interruptor", "qs": "seccionador", "gv": "guardamotor",
    "km": "contactor", "ka": "relé", "fr": "relé térmico", "fu": "fusible",
    "vfd": "variador", "uf": "variador", "atv": "variador", "fc": "variador",
    "plc": "PLC", "di": "módulo de entradas", "do": "módulo de salidas",
    "ai": "módulo analógico", "ao": "módulo analógico", "m": "motor",
    "b": "sensor", "x": "bornera", "xt": "bornera", "h": "piloto",
    "s": "pulsador", "t": "transformador",
}

def infer_type(reference: str, detected: str | None, component_type: str | None) -> str:
    for value in (detected, component_type):
        if value and value.strip():
            return value.strip().lower()
    ref = (reference or "").strip().lower()
    prefix = "".join(ch for ch in ref if ch.isalpha())
    for key in sorted(TYPE_MAP, key=len, reverse=True):
        if prefix.startswith(key):
            return TYPE_MAP[key]
    return "otro"

@router.get("")
def list_components(
    organization_id: int | None = Query(default=None),
    plant_id: int | None = Query(default=None),
    sector_id: int | None = Query(default=None),
    component_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    query = (
        db.query(models.ComponentReference, models.DocumentPage, models.Document, models.Sector, models.Plant, models.Organization)
        .join(models.DocumentPage, models.ComponentReference.document_page_id == models.DocumentPage.id)
        .join(models.Document, models.DocumentPage.document_id == models.Document.id)
        .join(models.Sector, models.Document.sector_id == models.Sector.id)
        .join(models.Plant, models.Sector.plant_id == models.Plant.id)
        .join(models.Organization, models.Plant.organization_id == models.Organization.id)
    )
    if organization_id is not None:
        query = query.filter(models.Organization.id == organization_id)
    if plant_id is not None:
        query = query.filter(models.Plant.id == plant_id)
    if sector_id is not None:
        query = query.filter(models.Sector.id == sector_id)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            models.ComponentReference.reference.ilike(term) |
            models.ComponentReference.model.ilike(term) |
            models.ComponentReference.row_text.ilike(term)
        )

    rows = query.order_by(models.ComponentReference.reference.asc(), models.DocumentPage.page_number.asc()).limit(limit).all()
    items = []
    counts = Counter()
    for ref, page, doc, sector, plant, org in rows:
        ctype = infer_type(ref.reference, ref.detected_type, ref.component_type)
        if component_type and ctype != component_type.strip().lower():
            continue
        counts[ctype] += 1
        items.append({
            "id": ref.id,
            "reference": ref.reference,
            "component_type": ctype,
            "model": ref.model or "",
            "manufacturer": getattr(ref, "manufacturer", None) or "",
            "source_kind": getattr(ref, "source_kind", None) or "",
            "catalog_confidence": getattr(ref, "catalog_confidence", 0) or 0,
            "description": ref.description or ref.row_text or "",
            "document_id": doc.id,
            "document_title": doc.title,
            "page_number": page.page_number,
            "page_id": page.id,
            "x": ref.x, "y": ref.y, "width": ref.width, "height": ref.height,
            "organization_id": org.id, "organization_name": org.name,
            "plant_id": plant.id, "plant_name": plant.name,
            "sector_id": sector.id, "sector_name": sector.name,
        })
    return {"items": items, "counts": dict(sorted(counts.items())), "total": len(items)}
