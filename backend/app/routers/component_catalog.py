from __future__ import annotations

import re
from collections import Counter
from io import BytesIO
from typing import Any
from urllib.parse import quote_plus, urlencode

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
    "vfd": "variador", "uf": "variador", "atv": "variador",
    "plc": "PLC", "di": "módulo de entradas", "do": "módulo de salidas",
    "ai": "módulo analógico", "ao": "módulo analógico", "m": "motor",
    "b": "sensor", "x": "bornera", "xt": "bornera", "h": "piloto",
    "s": "pulsador", "t": "transformador",
}


MODEL_TYPE_RULES = (
    (re.compile(r"^3RV", re.IGNORECASE), "guardamotor"),
    (re.compile(r"^3RT", re.IGNORECASE), "contactor"),
    (re.compile(r"^(ATV|ALTIVAR)", re.IGNORECASE), "variador"),
    (re.compile(r"^(FC-|FC\s)?\d{2,4}", re.IGNORECASE), "variador"),
    (re.compile(r"^6ES7", re.IGNORECASE), "módulo PLC"),
)

MODEL_MANUFACTURER_RULES = (
    (re.compile(r"^(3RV|3RT|6ES7|6SL)", re.IGNORECASE), "Siemens"),
    (re.compile(r"^(ATV|LC1D|GV2|TM3|BMX)", re.IGNORECASE), "Schneider Electric"),
    (re.compile(r"^(FC-|VLT)", re.IGNORECASE), "Danfoss"),
    (re.compile(r"^(ACS|AF|MS116)", re.IGNORECASE), "ABB"),
)

MANUFACTURER_DOMAINS = {
    "siemens": "siemens.com",
    "schneider": "se.com",
    "schneider electric": "se.com",
    "danfoss": "danfoss.com",
    "abb": "abb.com",
    "sew": "sew-eurodrive.com",
    "sew-eurodrive": "sew-eurodrive.com",
    "rockwell": "rockwellautomation.com",
    "allen-bradley": "rockwellautomation.com",
    "omron": "omron.com",
    "sick": "sick.com",
    "ifm": "ifm.com",
    "festo": "festo.com",
    "wago": "wago.com",
    "phoenix": "phoenixcontact.com",
    "weidmuller": "weidmueller.com",
    "weidmüller": "weidmueller.com",
    "eaton": "eaton.com",
}


def infer_manufacturer(model: str | None, manufacturer: str | None) -> str:
    current = (manufacturer or "").strip()
    if current:
        return current
    clean_model = (model or "").strip()
    for pattern, name in MODEL_MANUFACTURER_RULES:
        if pattern.search(clean_model):
            return name
    return ""


def _model_type(model: str | None) -> str:
    clean_model = (model or "").strip()
    for pattern, component_type in MODEL_TYPE_RULES:
        if pattern.search(clean_model):
            return component_type
    return ""


def official_component_links(manufacturer: str | None, model: str | None) -> dict[str, str]:
    """Genera búsquedas acotadas al sitio oficial sin inventar una URL de producto."""
    maker = (manufacturer or "").strip()
    part = (model or "").strip()
    if not part:
        return {"product_url": "", "manual_url": ""}
    domain = MANUFACTURER_DOMAINS.get(maker.lower())
    if not domain:
        return {"product_url": "", "manual_url": ""}
    product_query = quote_plus(f"site:{domain} {part}")
    manual_query = quote_plus(f"site:{domain} {part} manual OR datasheet PDF")
    return {
        "product_url": f"https://www.google.com/search?q={product_query}",
        "manual_url": f"https://www.google.com/search?q={manual_query}",
    }


def infer_type(reference: str, detected: str | None, component_type: str | None, model: str | None = None, description: str | None = None) -> str:
    model_type = _model_type(model)
    if model_type:
        return model_type
    context = " ".join(filter(None, (detected, component_type, description))).strip().lower()
    for keyword, label in (
        ("guardamotor", "guardamotor"),
        ("protector de motor", "guardamotor"),
        ("contactor", "contactor"),
        ("relé térmico", "relé térmico"),
        ("rele termico", "relé térmico"),
        ("variador", "variador"),
        ("motor", "motor"),
        ("sensor", "sensor"),
        ("fin de carrera", "contacto o fin de carrera"),
    ):
        if keyword in context:
            return label
    for value in (detected, component_type):
        if value and value.strip() and value.strip().lower() not in {"referencia técnica", "referencia fc"}:
            return value.strip().lower()
    ref = (reference or "").strip().lower()
    prefix = "".join(ch for ch in ref if ch.isalpha())
    if prefix.startswith("fc"):
        return "referencia FC"
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

    manufacturer = infer_manufacturer(model, getattr(ref, "manufacturer", None))
    component_type = infer_type(reference, ref.detected_type, ref.component_type, model, ref.description or row_text)
    links = official_component_links(manufacturer, model)

    return {
        "id": ref.id,
        "reference": reference,
        "component_type": component_type,
        "model": model,
        "manufacturer": manufacturer,
        "product_url": links["product_url"],
        "manual_url": links["manual_url"],
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
    """Exporta una hoja técnica consolidada y otra con todas las apariciones."""
    items = _filtered_items(
        db, organization_id, plant_id, sector_id, component_type, q, hard_limit=50000
    )

    def quality(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
        model = (item.get("model") or "").upper()
        reliable_model = bool(re.match(r"^(3RV|3RT|6ES7|6SL|ATV|LC1D|GV2|FC-|VLT|ACS|AF|MS116)", model))
        source = (item.get("source_kind") or "").lower()
        component_type_value = (item.get("component_type") or "").lower()
        return (
            1 if reliable_model else 0,
            1 if source == "catalog+plan" else 0,
            1 if item.get("manufacturer") else 0,
            int(item.get("catalog_confidence") or 0),
            1 if component_type_value not in {"otro", "referencia técnica", "referencia fc"} else 0,
        )

    # Una ficha por referencia/modelo/sector. Si hay varias apariciones, conserva la más rica.
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        reliable_model = normalize_term(item.get("model"))
        key = (
            normalize_term(item.get("reference")),
            reliable_model if reliable_model else "SINMODELO",
            item.get("sector_id"),
        )
        previous = grouped.get(key)
        if previous is None or quality(item) > quality(previous):
            grouped[key] = item
    unique = sorted(grouped.values(), key=lambda x: (
        normalize_term(x.get("reference")), x.get("sector_name") or "", x.get("page_number") or 0
    ))

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Componentes únicos"
    headers = [
        "Referencia", "Tipo", "Fabricante", "Modelo completo", "Función / descripción",
        "Empresa", "Planta", "Sector", "Documento", "Página principal",
        "Confianza", "Origen", "Página oficial", "Manual / ficha técnica",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for item in unique:
        row = [
            item["reference"], item["component_type"], item["manufacturer"],
            item["model"], item["description"], item["organization_name"],
            item["plant_name"], item["sector_name"], item["document_title"],
            item["page_number"], item["catalog_confidence"], item["source_kind"],
            "Abrir producto oficial" if item.get("product_url") else "",
            "Buscar manual oficial" if item.get("manual_url") else "",
        ]
        sheet.append(row)
        row_index = sheet.max_row
        if item.get("product_url"):
            sheet.cell(row_index, 13).hyperlink = item["product_url"]
            sheet.cell(row_index, 13).style = "Hyperlink"
        if item.get("manual_url"):
            sheet.cell(row_index, 14).hyperlink = item["manual_url"]
            sheet.cell(row_index, 14).style = "Hyperlink"

    occurrences = workbook.create_sheet("Apariciones")
    occurrence_headers = [
        "Referencia", "Tipo", "Fabricante", "Modelo", "Empresa", "Planta", "Sector",
        "Documento", "Página", "Origen", "Descripción",
    ]
    occurrences.append(occurrence_headers)
    for cell in occurrences[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    seen_occurrences: set[tuple[Any, ...]] = set()
    for item in items:
        key = (item["id"], item["document_id"], item["page_number"])
        if key in seen_occurrences:
            continue
        seen_occurrences.add(key)
        occurrences.append([
            item["reference"], item["component_type"], item["manufacturer"], item["model"],
            item["organization_name"], item["plant_name"], item["sector_name"],
            item["document_title"], item["page_number"], item["source_kind"], item["description"],
        ])

    for current in (sheet, occurrences):
        current.freeze_panes = "A2"
        current.auto_filter.ref = current.dimensions
        for row in current.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    widths = [18, 24, 22, 30, 55, 22, 22, 25, 35, 14, 12, 18, 24, 28]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    occurrence_widths = [18, 24, 22, 30, 22, 22, 25, 35, 10, 18, 60]
    for index, width in enumerate(occurrence_widths, start=1):
        occurrences.column_dimensions[get_column_letter(index)].width = width

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="diagramiq-componentes.xlsx"'},
    )

