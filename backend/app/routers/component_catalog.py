from __future__ import annotations

import re
from collections import Counter
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
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


def normalize_term(value: str | None) -> str:
    """Normaliza referencias para que fc011, -FC011 y =DV2-FC011 coincidan."""
    text = (value or "").upper().strip()
    text = re.sub(r"\s+", "", text)
    # Conserva letras y números; elimina separadores de plano.
    return re.sub(r"[^A-Z0-9]", "", text)


def _base_query(
    db: Session,
    organization_id: int | None,
    plant_id: int | None,
    sector_id: int | None,
):
    query = (
        db.query(
            models.ComponentReference,
            models.DocumentPage,
            models.Document,
            models.Sector,
            models.Plant,
            models.Organization,
        )
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
    return query


def _row_to_item(row: tuple[Any, ...], search_normalized: str = "") -> dict[str, Any]:
    ref, page, doc, sector, plant, org = row
    reference = ref.reference or ""
    model = ref.model or ""
    row_text = ref.row_text or ""
    normalized_reference = normalize_term(reference)
    normalized_model = normalize_term(model)

    match_rank = 99
    match_reason = ""
    if search_normalized:
        if normalized_reference == search_normalized:
            match_rank, match_reason = 0, "Coincidencia exacta en referencia"
        elif normalized_model == search_normalized:
            match_rank, match_reason = 1, "Coincidencia exacta en modelo"
        elif search_normalized and search_normalized in normalized_reference:
            match_rank, match_reason = 2, "Coincidencia parcial en referencia"
        elif search_normalized and search_normalized in normalized_model:
            match_rank, match_reason = 3, "Coincidencia parcial en modelo"
        elif search_normalized and search_normalized in normalize_term(row_text):
            match_rank, match_reason = 4, "Mencionado en la descripción"

    return {
        "id": ref.id,
        "reference": reference,
        "component_type": infer_type(reference, ref.detected_type, ref.component_type),
        "model": model,
        "manufacturer": getattr(ref, "manufacturer", None) or "",
        "source_kind": getattr(ref, "source_kind", None) or "",
        "catalog_confidence": getattr(ref, "catalog_confidence", 0) or 0,
        "description": ref.description or row_text,
        "document_id": doc.id,
        "document_title": doc.title,
        "page_number": page.page_number,
        "page_id": page.id,
        "x": ref.x, "y": ref.y, "width": ref.width, "height": ref.height,
        "organization_id": org.id, "organization_name": org.name,
        "plant_id": plant.id, "plant_name": plant.name,
        "sector_id": sector.id, "sector_name": sector.name,
        "match_rank": match_rank,
        "match_reason": match_reason,
    }


def _filtered_items(
    db: Session,
    organization_id: int | None,
    plant_id: int | None,
    sector_id: int | None,
    component_type: str | None,
    q: str | None,
    hard_limit: int,
) -> list[dict[str, Any]]:
    query = _base_query(db, organization_id, plant_id, sector_id)
    search_normalized = normalize_term(q)

    # Reduce candidatos en SQL, pero la prioridad final se calcula normalizada en Python.
    if q and q.strip():
        raw = q.strip()
        term = f"%{raw}%"
        normalized_term = f"%{search_normalized}%"
        query = query.filter(
            models.ComponentReference.reference.ilike(term)
            | models.ComponentReference.reference.ilike(normalized_term)
            | models.ComponentReference.model.ilike(term)
            | models.ComponentReference.model.ilike(normalized_term)
            | models.ComponentReference.row_text.ilike(term)
            | models.ComponentReference.normalized_reference.ilike(normalized_term)
        )

    rows = query.order_by(
        models.ComponentReference.reference.asc(),
        models.DocumentPage.page_number.asc(),
    ).limit(hard_limit).all()

    items = [_row_to_item(row, search_normalized) for row in rows]
    if component_type:
        wanted = component_type.strip().lower()
        items = [item for item in items if item["component_type"].lower() == wanted]

    if search_normalized:
        # Si existen coincidencias en referencia/modelo, se eliminan menciones secundarias.
        best_rank = min((item["match_rank"] for item in items), default=99)
        if best_rank <= 3:
            items = [item for item in items if item["match_rank"] <= 3]
        items.sort(key=lambda item: (
            item["match_rank"],
            normalize_term(item["reference"]),
            item["page_number"],
        ))
    return items


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
    items = _filtered_items(
        db, organization_id, plant_id, sector_id, component_type, q, hard_limit=10000
    )[:limit]
    counts = Counter(item["component_type"] for item in items)
    return {"items": items, "counts": dict(sorted(counts.items())), "total": len(items)}


@router.get("/export.xlsx")
def export_components_excel(
    organization_id: int | None = Query(default=None),
    plant_id: int | None = Query(default=None),
    sector_id: int | None = Query(default=None),
    component_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Exporta el catálogo respetando exactamente los filtros visibles."""
    items = _filtered_items(
        db, organization_id, plant_id, sector_id, component_type, q, hard_limit=50000
    )

    # Una fila por referencia/modelo/página/sector para evitar duplicados visuales.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = (
            normalize_term(item["reference"]),
            normalize_term(item["model"]),
            item["sector_id"],
            item["document_id"],
            item["page_number"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Componentes"
    headers = [
        "Referencia", "Tipo", "Fabricante", "Modelo", "Empresa", "Planta",
        "Sector", "Documento", "Página", "Confianza", "Origen", "Descripción",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for item in unique:
        sheet.append([
            item["reference"], item["component_type"], item["manufacturer"],
            item["model"], item["organization_name"], item["plant_name"],
            item["sector_name"], item["document_title"], item["page_number"],
            item["catalog_confidence"], item["source_kind"], item["description"],
        ])

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = [20, 22, 20, 28, 22, 22, 24, 34, 10, 12, 18, 60]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        row[-1].alignment = Alignment(wrap_text=True, vertical="top")

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = "diagramiq-componentes.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
