from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services.pdf_service import extract_references, normalize_reference
from app.services.vision_provider import ask_text
from app.routers.component_catalog import (
    official_component_links, infer_manufacturer, infer_type, inventory_snapshot,
)

router = APIRouter(prefix="/assistant", tags=["Asistente IA"])


AMBIGUOUS_COMPONENT_REFERENCES = {
    "N", "PE", "M", "L", "L1", "L2", "L3", "A", "B", "C",
    "BN", "BK", "BU", "GY", "RD", "WH", "GN", "YE", "SH",
    "0V", "24V", "+24V", "L+", "M0", "U", "V", "W"
}


def _is_ambiguous_component_reference(value: str | None) -> bool:
    normalized = normalize_reference(value or "")
    if not normalized:
        return True
    if normalized in AMBIGUOUS_COMPONENT_REFERENCES:
        return True
    if re.fullmatch(r"\d{1,2}", normalized):
        return True
    return len(normalized) < 3




INVENTORY_QUERY_TYPES = {
    "variador": ("variador", "variadores", "vfd", "variadores de frecuencia"),
    "motor": ("motor", "motores"),
    "contactor": ("contactor", "contactores"),
    "guardamotor": ("guardamotor", "guardamotores"),
    "sensor": ("sensor", "sensores"),
    "válvula": ("válvula", "valvula", "válvulas", "valvulas", "electroválvula", "electrovalvula"),
    "relé": ("relé", "rele", "relés", "reles"),
    "PLC / módulo": ("plc", "módulo plc", "modulo plc", "módulos plc", "modulos plc"),
    "transformador": ("transformador", "transformadores"),
    "interruptor": ("interruptor", "interruptores", "seccionador", "seccionadores"),
}

def _inventory_intent(question: str) -> tuple[bool, str | None, bool]:
    q = question.lower()
    is_count = bool(re.search(r"\b(cu[aá]ntos?|cantidad|total|n[uú]mero)\b", q))
    wants_list = bool(re.search(r"\b(cu[aá]les|lista|listado|mostrar|mostrame|detalle)\b", q))
    if not is_count and not wants_list:
        return False, None, False
    for canonical, aliases in INVENTORY_QUERY_TYPES.items():
        if any(alias in q for alias in aliases):
            return True, canonical, wants_list
    if any(word in q for word in ("equipos", "componentes", "dispositivos")):
        return True, None, wants_list
    return False, None, False

def _inventory_answer(payload: AssistantQuestion, db: Session) -> dict | None:
    matched, requested_type, wants_list = _inventory_intent(payload.question)
    if not matched:
        return None
    items = inventory_snapshot(db, payload.organization_id, payload.plant_id, payload.sector_id)
    def canonical_type(value: str) -> str:
        v = (value or "").strip().lower()
        for canonical, aliases in INVENTORY_QUERY_TYPES.items():
            if v == canonical.lower() or any(alias in v for alias in aliases):
                return canonical
        return value or "otro"
    for item in items:
        item["inventory_type"] = canonical_type(item.get("component_type") or "")
    selected = [i for i in items if i["inventory_type"] == requested_type] if requested_type else items
    scope=[]
    if payload.organization_id: scope.append("la empresa seleccionada")
    if payload.plant_id: scope.append("la planta seleccionada")
    if payload.sector_id: scope.append("el sector seleccionado")
    scope_text = " en " + ", ".join(scope) if scope else " en el catálogo indexado"
    if requested_type:
        label = requested_type if len(selected)==1 else ({"motor":"motores","variador":"variadores","contactor":"contactores","guardamotor":"guardamotores","sensor":"sensores","válvula":"válvulas","relé":"relés","transformador":"transformadores","interruptor":"interruptores"}.get(requested_type, requested_type))
        lines=[f"## Inventario técnico", f"Se detectaron **{len(selected)} {label}**{scope_text}."]
        manufacturers=Counter((i.get("manufacturer") or "Sin fabricante identificado") for i in selected)
        if manufacturers:
            lines.append("\n**Por fabricante:**")
            lines.extend(f"- {name}: {count}" for name,count in manufacturers.most_common())
        if wants_list and selected:
            lines.append("\n**Equipos:**")
            for i in sorted(selected, key=lambda x:(x.get("reference") or ""))[:100]:
                model=f" — {i.get('model')}" if i.get('model') else ""
                sector=f" — {i.get('sector_name')}" if i.get('sector_name') else ""
                lines.append(f"- **{i.get('reference') or 'Sin TAG'}**{model}{sector}")
    else:
        counts=Counter(i["inventory_type"] for i in selected)
        lines=["## Inventario técnico", f"Se detectaron **{len(selected)} equipos físicos**{scope_text}.", "\n**Por tipo:**"]
        lines.extend(f"- {name}: {count}" for name,count in counts.most_common())
    return {
        "answer":"\n".join(lines), "provider":"DiagramIQ Catalog", "model":"structured-inventory",
        "sources":[], "component_card":None, "detected_references":[], "context_count":0,
        "incomplete":False, "continued":False, "context_applied":False,
        "context_page_id":payload.context_page_id,
        "inventory_summary":{"total":len(selected),"type":requested_type},
    }


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    organization_id: Optional[int] = None
    plant_id: Optional[int] = None
    sector_id: Optional[int] = None
    continue_response: bool = False
    previous_answer: Optional[str] = Field(default=None, max_length=16000)
    context_page_id: Optional[int] = None
    context_document_id: Optional[int] = None
    context_reference: Optional[str] = Field(default=None, max_length=200)


def _keywords(question: str) -> list[str]:
    stop = {
        "como", "cómo", "cual", "cuál", "donde", "dónde", "para", "porque", "porqué",
        "que", "qué", "este", "esta", "esto", "desde", "hasta", "tiene", "puede",
        "del", "las", "los", "una", "uno", "con", "sin", "sobre", "entre", "motor",
    }
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_.:+-]{3,}", question)
    result: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered in stop or lowered in result:
            continue
        result.append(lowered)
    return result[:8]


def _reference_aliases(value: str) -> set[str]:
    """Equivale guion medio, bajo, punto y slash en TAGs de plano/HMI."""
    normalized = normalize_reference(value or "")
    if not normalized:
        return set()
    parts = [part for part in re.split(r"[_.\-/]+", normalized) if part]
    aliases = {normalized}
    if len(parts) >= 2:
        aliases.update({sep.join(parts) for sep in ("-", "_", ".", "/")})
        aliases.add("".join(parts))
    return aliases


def _base_page_query(db: Session, organization_id: int | None, plant_id: int | None, sector_id: int | None):
    query = (
        db.query(models.DocumentPage, models.Document, models.Sector, models.Plant, models.Organization)
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


def _collect_context(payload: AssistantQuestion, db: Session) -> tuple[list[dict], list[str]]:
    references = [normalize_reference(ref) for ref in extract_references(payload.question)]
    references = list(dict.fromkeys(ref for ref in references if ref))[:6]
    lookup_references = sorted({alias for ref in references for alias in _reference_aliases(ref)})
    snippets: list[dict] = []
    seen_pages: set[int] = set()

    # Si el técnico abrió una página del plano, esa página es el contexto principal.
    # Se incorpora primero para evitar elegir otra instancia de la misma referencia
    # que pertenezca a otro sector o subsistema.
    if payload.context_page_id is not None:
        current_query = _base_page_query(
            db, payload.organization_id, payload.plant_id, payload.sector_id
        ).filter(models.DocumentPage.id == payload.context_page_id)
        current_row = current_query.first()
        if current_row:
            page, doc, sector, plant, org = current_row
            current_ref = None
            ref_candidates = db.query(models.ComponentReference).filter(
                models.ComponentReference.document_page_id == page.id
            ).all()
            requested = set(references)
            context_ref = normalize_reference(payload.context_reference or "")
            if context_ref:
                requested.add(context_ref)
            for candidate in ref_candidates:
                candidate_norm = normalize_reference(
                    candidate.normalized_reference or candidate.reference or ""
                )
                if requested and candidate_norm in requested:
                    current_ref = candidate
                    break
            if current_ref is None and ref_candidates:
                current_ref = max(
                    ref_candidates,
                    key=lambda item: (
                        int(item.catalog_confidence or 0),
                        1 if (item.model or item.manufacturer or item.detected_type) else 0,
                    ),
                )
            seen_pages.add(page.id)
            snippets.append({
                "reference_id": current_ref.id if current_ref else None,
                "reference": current_ref.reference if current_ref else (payload.context_reference or ""),
                "type": (current_ref.detected_type or current_ref.component_type or "") if current_ref else "",
                "model": (current_ref.model or "") if current_ref else "",
                "manufacturer": (current_ref.manufacturer or "") if current_ref else "",
                "description": (current_ref.description or current_ref.row_text or "") if current_ref else "",
                "confidence": int(current_ref.catalog_confidence or 0) if current_ref else 0,
                "source_kind": (current_ref.source_kind if current_ref else None) or page.page_type or "plan",
                "page_number": page.page_number,
                "page_id": page.id,
                "document_id": doc.id,
                "document_title": doc.title,
                "organization": org.name,
                "plant": plant.name,
                "sector": sector.name,
                "image_url": f"/documents/pages/{page.id}/image",
                "x": current_ref.x if current_ref else None,
                "y": current_ref.y if current_ref else None,
                "width": current_ref.width if current_ref else None,
                "height": current_ref.height if current_ref else None,
                "text": (page.text_content or "")[:4200],
                "is_current_context": True,
            })

    if references:
        ref_query = (
            db.query(models.ComponentReference, models.DocumentPage, models.Document, models.Sector, models.Plant, models.Organization)
            .join(models.DocumentPage, models.ComponentReference.document_page_id == models.DocumentPage.id)
            .join(models.Document, models.DocumentPage.document_id == models.Document.id)
            .join(models.Sector, models.Document.sector_id == models.Sector.id)
            .join(models.Plant, models.Sector.plant_id == models.Plant.id)
            .join(models.Organization, models.Plant.organization_id == models.Organization.id)
        )
        if payload.organization_id is not None:
            ref_query = ref_query.filter(models.Organization.id == payload.organization_id)
        if payload.plant_id is not None:
            ref_query = ref_query.filter(models.Plant.id == payload.plant_id)
        if payload.sector_id is not None:
            ref_query = ref_query.filter(models.Sector.id == payload.sector_id)
        ref_query = ref_query.filter(
            or_(
                models.ComponentReference.normalized_reference.in_(lookup_references or references),
                models.ComponentReference.reference.in_(lookup_references or references),
            )
        )
        for ref, page, doc, sector, plant, org in ref_query.limit(12).all():
            if page.id in seen_pages:
                continue
            seen_pages.add(page.id)
            snippets.append({
                "reference_id": ref.id,
                "reference": ref.reference,
                "type": ref.detected_type or ref.component_type or "",
                "model": ref.model or "",
                "manufacturer": ref.manufacturer or "",
                "description": ref.description or ref.row_text or "",
                "confidence": int(ref.catalog_confidence or 0),
                "source_kind": ref.source_kind or page.page_type or "plan",
                "page_number": page.page_number,
                "page_id": page.id,
                "document_id": doc.id,
                "document_title": doc.title,
                "organization": org.name,
                "plant": plant.name,
                "sector": sector.name,
                "image_url": f"/documents/pages/{page.id}/image",
                "x": ref.x,
                "y": ref.y,
                "width": ref.width,
                "height": ref.height,
                "text": (page.text_content or "")[:2800],
                "is_current_context": False,
            })

    terms = _keywords(payload.question)
    if terms and len(snippets) < 8:
        search_terms = list(terms)
        for ref in references:
            search_terms.extend(sorted(_reference_aliases(ref)))
        search_terms = list(dict.fromkeys(term for term in search_terms if term))
        filters = [models.DocumentPage.text_content.ilike(f"%{term}%") for term in search_terms]
        page_query = _base_page_query(db, payload.organization_id, payload.plant_id, payload.sector_id)
        page_query = page_query.filter(or_(*filters))
        for page, doc, sector, plant, org in page_query.limit(12).all():
            if page.id in seen_pages:
                continue
            seen_pages.add(page.id)
            snippets.append({
                "reference_id": None,
                "reference": "",
                "type": "",
                "model": "",
                "manufacturer": "",
                "description": "",
                "confidence": 0,
                "source_kind": page.page_type or "unknown",
                "page_number": page.page_number,
                "page_id": page.id,
                "document_id": doc.id,
                "document_title": doc.title,
                "organization": org.name,
                "plant": plant.name,
                "sector": sector.name,
                "image_url": f"/documents/pages/{page.id}/image",
                "x": None,
                "y": None,
                "width": None,
                "height": None,
                "text": (page.text_content or "")[:2800],
                "is_current_context": False,
            })
            if len(snippets) >= 8:
                break

    return snippets, references


@router.post("/ask")
def ask_diagramiq(payload: AssistantQuestion, db: Session = Depends(get_db)):
    question = payload.question.strip()
    if not question:
        raise HTTPException(400, "Escribí una pregunta.")

    inventory_response = _inventory_answer(payload, db)
    if inventory_response is not None:
        return inventory_response

    snippets, references = _collect_context(payload, db)
    if not snippets:
        raise HTTPException(
            404,
            "No encontré contexto suficiente en los documentos seleccionados. Probá incluir una referencia exacta, modelo o alarma.",
        )

    context_blocks: list[str] = []
    sources: list[dict] = []
    for index, item in enumerate(snippets, start=1):
        context_mark = " | CONTEXTO ACTUAL ABIERTO POR EL USUARIO" if item.get("is_current_context") else ""
        header = (
            f"FUENTE {index}{context_mark} | Empresa: {item['organization']} | Planta: {item['plant']} | "
            f"Sector: {item['sector']} | Documento: {item['document_title']} | Página: {item['page_number']}"
        )
        details = " | ".join(
            value for value in [
                f"Referencia: {item['reference']}" if item['reference'] else "",
                f"Tipo: {item['type']}" if item['type'] else "",
                f"Fabricante: {item['manufacturer']}" if item['manufacturer'] else "",
                f"Modelo: {item['model']}" if item['model'] else "",
                f"Descripción: {item['description']}" if item['description'] else "",
            ] if value
        )
        context_blocks.append(f"{header}\n{details}\nTexto indexado:\n{item['text']}")
        sources.append({
            "component_id": item.get("reference_id"),
            "document_id": item["document_id"],
            "page_id": item["page_id"],
            "document_title": item["document_title"],
            "page_number": item["page_number"],
            "reference": item["reference"],
            "organization": item["organization"],
            "plant": item["plant"],
            "sector": item["sector"],
            "image_url": item["image_url"],
            "x": item["x"],
            "y": item["y"],
            "width": item["width"],
            "height": item["height"],
            "source_kind": item["source_kind"],
            "is_current_context": bool(item.get("is_current_context")),
        })

    continuation_instruction = ""
    if payload.continue_response and payload.previous_answer:
        continuation_instruction = f"""

RESPUESTA ANTERIOR (quedó incompleta):
{payload.previous_answer}

Continuá exactamente desde donde quedó. No repitas lo ya dicho. Terminá las frases y secciones pendientes.
"""

    prompt = f"""Sos DiagramIQ, un asistente técnico de mantenimiento industrial.
Respondé en español claro y práctico usando SOLO la información del contexto indexado.
No inventes conexiones, protecciones, parámetros ni causas que no estén respaldaldadas por el contexto.
Cuando algo no pueda confirmarse, decilo expresamente.
Citá las fuentes dentro de la respuesta como [Fuente 1], [Fuente 2], etc.
Priorizá el componente principal sobre listados o menciones secundarias.
Si una fuente está marcada como CONTEXTO ACTUAL ABIERTO POR EL USUARIO, respondé sobre esa instancia concreta y no sobre otra referencia homónima de otro sector.
Organizá la respuesta con este orden: resumen técnico, función, conexión/relaciones, advertencias y fuentes.
Sé completo pero evitá repeticiones. Cerrá todas las frases y no termines una sección a mitad.
No des por segura una condición eléctrica real: indicá siempre que debe verificarse en campo y aplicarse el procedimiento de seguridad de la planta.

PREGUNTA DEL USUARIO:
{question}

REFERENCIAS DETECTADAS:
{', '.join(references) if references else 'Ninguna'}

CONTEXTO INDEXADO:
{chr(10).join(chr(10) + block for block in context_blocks)}
{continuation_instruction}
"""
    response = ask_text(prompt)

    requested_references = {normalize_reference(ref) for ref in references if ref}
    context_reference = normalize_reference(payload.context_reference or "")
    if context_reference:
        requested_references.add(context_reference)

    component_candidates = [
        item for item in snippets
        if item.get("reference")
        and not _is_ambiguous_component_reference(item.get("reference"))
        and (item.get("type") or item.get("model") or item.get("manufacturer") or item.get("description"))
    ]
    component_candidates.sort(
        key=lambda item: (
            1 if normalize_reference(item.get("reference") or "") in requested_references else 0,
            1 if item.get("is_current_context") else 0,
            1 if item.get("source_kind") == "plan" else 0,
            int(item.get("confidence") or 0),
            1 if item.get("model") else 0,
            1 if item.get("manufacturer") else 0,
        ),
        reverse=True,
    )
    primary = component_candidates[0] if component_candidates else None
    component_card = None
    if primary:
        confidence = int(primary.get("confidence") or 0)
        if primary.get("source_kind") == "plan" and confidence >= 80:
            confidence_label = "Confirmado por lista y plano"
            confidence_level = "confirmed"
        elif primary.get("source_kind") == "plan":
            confidence_label = "Confirmado en plano"
            confidence_level = "plan"
        else:
            confidence_label = "Referencia documental"
            confidence_level = "document"
        resolved_manufacturer = infer_manufacturer(primary.get("model"), primary.get("manufacturer"))
        resolved_type = infer_type(
            primary.get("reference") or "", primary.get("type"), primary.get("type"),
            primary.get("model"), primary.get("description"),
        )
        official_links = official_component_links(resolved_manufacturer, primary.get("model"))
        component_card = {
            "component_id": primary.get("reference_id"),
            "reference": primary.get("reference") or "",
            "type": resolved_type,
            "manufacturer": resolved_manufacturer,
            "model": primary.get("model") or "",
            "product_url": official_links.get("product_url", ""),
            "manual_url": official_links.get("manual_url", ""),
            "description": primary.get("description") or "",
            "organization": primary.get("organization") or "",
            "plant": primary.get("plant") or "",
            "sector": primary.get("sector") or "",
            "document_title": primary.get("document_title") or "",
            "page_number": primary.get("page_number"),
            "confidence": confidence,
            "confidence_label": confidence_label,
            "confidence_level": confidence_level,
            "source_index": next((
                index for index, source in enumerate(sources)
                if source.get("page_id") == primary.get("page_id")
            ), 0),
        }

    return {
        "answer": response.text,
        "provider": response.provider,
        "model": response.model,
        "sources": sources,
        "component_card": component_card,
        "detected_references": references,
        "context_count": len(sources),
        "incomplete": bool(response.truncated),
        "continued": bool(payload.continue_response),
        "context_applied": any(item.get("is_current_context") for item in snippets),
        "context_page_id": payload.context_page_id,
    }
