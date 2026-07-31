import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app import models
from app.database import get_db
from app.services.pdf_service import (
    REFERENCE_PATTERN, analyze_context_text, extract_references,
    normalize_reference, normalize_search_term,
)

router = APIRouter(prefix="/search", tags=["Búsqueda"])


def extract_search_references(query: str) -> list[str]:
    matches = REFERENCE_PATTERN.findall((query or "").upper())
    return sorted({normalize_reference(m) for m in matches if normalize_reference(m)})


def build_fragment(text: str | None, query: str, before: int = 100, after: int = 180) -> str:
    if not text:
        return ""
    lower = text.lower()
    pos = lower.find(query.lower())
    if pos < 0:
        return text[: before + after].strip()
    return text[max(0, pos-before): min(len(text), pos+len(query)+after)].strip()


def base_result(page: models.DocumentPage, query: str) -> dict:
    document = page.document
    sector = document.sector
    plant = sector.plant if sector else None
    return {
        "query": query,
        "document_id": document.id,
        "title": document.title,
        "filename": document.filename,
        "document_type": document.document_type,
        "processing_status": document.processing_status,
        "sector_id": document.sector_id,
        "sector_name": sector.name if sector else None,
        "plant_id": plant.id if plant else None,
        "plant_name": plant.name if plant else None,
        "page_id": page.id,
        "page_number": page.page_number,
        "page": page.page_number,
        "image_path": f"/documents/{document.id}/pages/{page.page_number}/image",
    }


def serialize_reference(item: models.ComponentReference, query: str) -> dict:
    page = item.document_page
    result = base_result(page, query)
    context = {
        "row_text": item.row_text,
        "description": item.description,
        "detected_type": item.detected_type,
        "model": item.model,
    }
    related = [
        ref for ref in extract_references(item.row_text or "")
        if normalize_reference(ref) != normalize_reference(item.reference)
    ]
    result.update({
        "match_type": "reference",
        "reference": item.reference,
        "normalized_reference": item.normalized_reference or normalize_reference(item.reference),
        "component_type": item.detected_type or item.component_type,
        "fragment": item.row_text or build_fragment(page.text_content, item.reference),
        "coordinates": {"x": item.x, "y": item.y, "width": item.width, "height": item.height},
        "context": context,
        "related_references": related[:12],
    })
    return result


def serialize_term(item: models.PageSearchTerm, query: str) -> dict:
    page = item.document_page
    result = base_result(page, query)
    context = analyze_context_text(item.row_text, item.display_text)
    result.update({
        "match_type": "text",
        "reference": None,
        "normalized_reference": None,
        "component_type": context.get("detected_type"),
        "fragment": item.row_text or build_fragment(page.text_content, query),
        "coordinates": {"x": item.x, "y": item.y, "width": item.width, "height": item.height},
        "context": context,
    })
    return result


def with_relations(query):
    return query.options(
        joinedload(models.PageSearchTerm.document_page)
        .joinedload(models.DocumentPage.document)
        .joinedload(models.Document.sector)
        .joinedload(models.Sector.plant)
    )


@router.get("")
def search_documents(
    q: str,
    sector_id: int | None = None,
    document_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Busca exclusivamente en el índice persistente; nunca abre el PDF."""
    clean_query = q.strip()
    if not clean_query:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debe ingresar un término de búsqueda")

    extracted_references = extract_search_references(clean_query)
    results: list[dict] = []
    total = 0

    if extracted_references:
        query = (
            db.query(models.ComponentReference)
            .options(
                joinedload(models.ComponentReference.document_page)
                .joinedload(models.DocumentPage.document)
                .joinedload(models.Document.sector)
                .joinedload(models.Sector.plant)
            )
            .join(models.DocumentPage)
            .join(models.Document)
        )
        filters = []
        for reference in extracted_references:
            filters.extend([
                models.ComponentReference.normalized_reference == reference,
                models.ComponentReference.reference.ilike(reference),
            ])
        query = query.filter(or_(*filters))
        if sector_id is not None:
            query = query.filter(models.Document.sector_id == sector_id)
        if document_id is not None:
            query = query.filter(models.Document.id == document_id)
        total = query.count()
        items = query.order_by(models.Document.id, models.DocumentPage.page_number, models.ComponentReference.id).offset(offset).limit(limit).all()
        results = [serialize_reference(item, clean_query) for item in items]
    else:
        # Para frases se usa la palabra más específica/larga como acceso al índice.
        tokens = [normalize_search_term(x) for x in re.split(r"\s+", clean_query)]
        tokens = [x for x in tokens if len(x) >= 2]
        if not tokens:
            return {"query": clean_query, "detected_references": extracted_references, "results": [], "count": 0, "total": 0, "limit": limit, "offset": offset, "has_more": False, "search_mode": "index"}
        indexed_term = max(tokens, key=len)
        query = (
            db.query(models.PageSearchTerm)
            .options(
                joinedload(models.PageSearchTerm.document_page)
                .joinedload(models.DocumentPage.document)
                .joinedload(models.Document.sector)
                .joinedload(models.Sector.plant)
            )
            .join(models.DocumentPage)
            .join(models.Document)
            .filter(models.PageSearchTerm.term == indexed_term)
        )
        if sector_id is not None:
            query = query.filter(models.Document.sector_id == sector_id)
        if document_id is not None:
            query = query.filter(models.Document.id == document_id)
        total = query.count()
        items = query.order_by(models.Document.id, models.DocumentPage.page_number, models.PageSearchTerm.id).offset(offset).limit(limit).all()
        results = [serialize_term(item, clean_query) for item in items]

    return {
        "query": clean_query,
        "detected_references": extracted_references,
        "sector_id": sector_id,
        "document_id": document_id,
        "results": results,
        "count": len(results),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(results) < total,
        "search_mode": "persistent_database_index",
    }
