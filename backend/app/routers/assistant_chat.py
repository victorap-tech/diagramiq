from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services.pdf_service import extract_references, normalize_reference
from app.services.vision_provider import ask_text

router = APIRouter(prefix="/assistant", tags=["Asistente IA"])


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    organization_id: Optional[int] = None
    plant_id: Optional[int] = None
    sector_id: Optional[int] = None
    continue_response: bool = False
    previous_answer: Optional[str] = Field(default=None, max_length=16000)


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
    snippets: list[dict] = []
    seen_pages: set[int] = set()

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
                models.ComponentReference.normalized_reference.in_(references),
                models.ComponentReference.reference.in_(references),
            )
        )
        for ref, page, doc, sector, plant, org in ref_query.limit(12).all():
            if page.id in seen_pages:
                continue
            seen_pages.add(page.id)
            snippets.append({
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
            })

    terms = _keywords(payload.question)
    if terms and len(snippets) < 8:
        filters = [models.DocumentPage.text_content.ilike(f"%{term}%") for term in terms]
        page_query = _base_page_query(db, payload.organization_id, payload.plant_id, payload.sector_id)
        page_query = page_query.filter(or_(*filters))
        for page, doc, sector, plant, org in page_query.limit(12).all():
            if page.id in seen_pages:
                continue
            seen_pages.add(page.id)
            snippets.append({
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
            })
            if len(snippets) >= 8:
                break

    return snippets, references


@router.post("/ask")
def ask_diagramiq(payload: AssistantQuestion, db: Session = Depends(get_db)):
    question = payload.question.strip()
    if not question:
        raise HTTPException(400, "Escribí una pregunta.")

    snippets, references = _collect_context(payload, db)
    if not snippets:
        raise HTTPException(
            404,
            "No encontré contexto suficiente en los documentos seleccionados. Probá incluir una referencia exacta, modelo o alarma.",
        )

    context_blocks: list[str] = []
    sources: list[dict] = []
    for index, item in enumerate(snippets, start=1):
        header = (
            f"FUENTE {index} | Empresa: {item['organization']} | Planta: {item['plant']} | "
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

    component_candidates = [
        item for item in snippets
        if item.get("reference") and (
            item.get("type") or item.get("model") or item.get("manufacturer")
        )
    ]
    component_candidates.sort(
        key=lambda item: (
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
        component_card = {
            "reference": primary.get("reference") or "",
            "type": primary.get("type") or "",
            "manufacturer": primary.get("manufacturer") or "",
            "model": primary.get("model") or "",
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
    }
