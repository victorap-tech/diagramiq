import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app import models
from app.database import get_db
from app.services.pdf_service import (
    REFERENCE_PATTERN,
    find_text_coordinates,
    extract_match_context,
    normalize_reference,
)


router = APIRouter(
    prefix="/search",
    tags=["Búsqueda"],
)


def extract_search_references(query: str) -> list[str]:
    """
    Extrae TAGs desde una búsqueda simple o una alarma completa.

    Ejemplos:
        570U4
        Error variador 570U4
        Error variador de frecuencia -570U4+V07=SGZ
    """
    if not query:
        return []

    matches = REFERENCE_PATTERN.findall(
        query.upper()
    )

    references = {
        normalize_reference(match)
        for match in matches
        if normalize_reference(match)
    }

    return sorted(references)


def build_fragment(
    text: str | None,
    query: str,
    reference: str | None = None,
    before: int = 100,
    after: int = 160,
) -> str:
    """
    Genera un fragmento de texto alrededor del término encontrado.
    """
    if not text:
        return ""

    search_terms = []

    if reference:
        search_terms.append(reference)

    if query:
        search_terms.append(query)

    lower_text = text.lower()
    position = -1
    selected_term = ""

    for term in search_terms:
        current_position = lower_text.find(
            term.lower()
        )

        if current_position >= 0:
            position = current_position
            selected_term = term
            break

    if position < 0:
        return text[: before + after].strip()

    start = max(
        0,
        position - before,
    )

    end = min(
        len(text),
        position + len(selected_term) + after,
    )

    return text[start:end].strip()


def serialize_reference_result(
    component_reference: models.ComponentReference,
    query: str,
) -> dict:
    page = component_reference.document_page
    document = page.document
    sector = document.sector
    plant = sector.plant if sector else None
    context = extract_match_context(
        pdf_path=document.file_path,
        page_number=page.page_number,
        search_text=component_reference.reference,
    )

    return {
        "match_type": "reference",
        "query": query,
        "reference": component_reference.reference,
        "normalized_reference": (
            component_reference.normalized_reference
            or normalize_reference(
                component_reference.reference
            )
        ),
        "component_type": (
            component_reference.component_type
        ),
        "document_id": document.id,
        "title": document.title,
        "filename": document.filename,
        "document_type": document.document_type,
        "processing_status": (
            document.processing_status
        ),
        "sector_id": document.sector_id,
        "sector_name": (
            sector.name if sector else None
        ),
        "plant_id": (
            plant.id if plant else None
        ),
        "plant_name": (
            plant.name if plant else None
        ),
        "page_id": page.id,
        "page_number": page.page_number,
        "page": page.page_number,
        "image_path": f"/documents/{document.id}/pages/{page.page_number}/image",
        "fragment": build_fragment(
            text=page.text_content,
            query=query,
            reference=component_reference.reference,
        ),
        "coordinates": {
            "x": component_reference.x,
            "y": component_reference.y,
            "width": component_reference.width,
            "height": component_reference.height,
        },
        "context": context,
    }


@router.get("")
def search_documents(
    q: str,
    sector_id: int | None = None,
    document_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    clean_query = q.strip()

    if not clean_query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe ingresar un término de búsqueda",
        )

    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit debe estar entre 1 y 500",
        )

    if sector_id is not None:
        sector_exists = (
            db.query(models.Sector.id)
            .filter(models.Sector.id == sector_id)
            .first()
        )

        if sector_exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sector no encontrado",
            )

    if document_id is not None:
        document_exists = (
            db.query(models.Document.id)
            .filter(
                models.Document.id == document_id
            )
            .first()
        )

        if document_exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Documento no encontrado",
            )

    extracted_references = extract_search_references(
        clean_query
    )

    reference_results = []

    if extracted_references:
        reference_query = (
            db.query(models.ComponentReference)
            .options(
                joinedload(
                    models.ComponentReference.document_page
                )
                .joinedload(
                    models.DocumentPage.document
                )
                .joinedload(
                    models.Document.sector
                )
                .joinedload(
                    models.Sector.plant
                )
            )
            .join(
                models.DocumentPage,
                models.ComponentReference.document_page_id
                == models.DocumentPage.id,
            )
            .join(
                models.Document,
                models.DocumentPage.document_id
                == models.Document.id,
            )
        )

        if sector_id is not None:
            reference_query = reference_query.filter(
                models.Document.sector_id == sector_id
            )

        if document_id is not None:
            reference_query = reference_query.filter(
                models.Document.id == document_id
            )

        reference_filters = []

        for reference in extracted_references:
            reference_filters.append(
                models.ComponentReference.normalized_reference
                == reference
            )

            reference_filters.append(
                models.ComponentReference.reference.ilike(
                    reference
                )
            )

        component_references = (
            reference_query
            .filter(
                or_(*reference_filters)
            )
            .order_by(
                models.Document.id.asc(),
                models.DocumentPage.page_number.asc(),
                models.ComponentReference.id.asc(),
            )
            .limit(limit)
            .all()
        )

        reference_results = [
            serialize_reference_result(
                component_reference=item,
                query=clean_query,
            )
            for item in component_references
        ]

    remaining_limit = max(
        0,
        limit - len(reference_results),
    )

    text_results = []

    if remaining_limit > 0:
        text_query = (
            db.query(models.DocumentPage)
            .options(
                joinedload(
                    models.DocumentPage.document
                )
                .joinedload(
                    models.Document.sector
                )
                .joinedload(
                    models.Sector.plant
                )
            )
            .join(
                models.Document,
                models.DocumentPage.document_id
                == models.Document.id,
            )
            .filter(
                models.DocumentPage.text_content.ilike(
                    f"%{clean_query}%"
                )
            )
        )

        if sector_id is not None:
            text_query = text_query.filter(
                models.Document.sector_id == sector_id
            )

        if document_id is not None:
            text_query = text_query.filter(
                models.Document.id == document_id
            )

        pages = (
            text_query
            .order_by(
                models.Document.id.asc(),
                models.DocumentPage.page_number.asc(),
            )
            .limit(remaining_limit)
            .all()
        )

        reference_page_keys = {
            (
                result["document_id"],
                result["page_number"],
            )
            for result in reference_results
        }

        for page in pages:
            document = page.document
            sector = document.sector
            plant = sector.plant if sector else None

            page_key = (
                document.id,
                page.page_number,
            )

            if page_key in reference_page_keys:
                continue

            text_results.append(
                {
                    "match_type": "text",
                    "query": clean_query,
                    "reference": None,
                    "normalized_reference": None,
                    "component_type": None,
                    "document_id": document.id,
                    "title": document.title,
                    "filename": document.filename,
                    "document_type": (
                        document.document_type
                    ),
                    "processing_status": (
                        document.processing_status
                    ),
                    "sector_id": document.sector_id,
                    "sector_name": (
                        sector.name if sector else None
                    ),
                    "plant_id": (
                        plant.id if plant else None
                    ),
                    "plant_name": (
                        plant.name if plant else None
                    ),
                    "page_id": page.id,
                    "page_number": page.page_number,
                    "page": page.page_number,
                    "image_path": f"/documents/{document.id}/pages/{page.page_number}/image",
                    "fragment": build_fragment(
                        text=page.text_content,
                        query=clean_query,
                    ),
                    "coordinates": find_text_coordinates(
                        pdf_path=document.file_path,
                        page_number=page.page_number,
                        search_text=clean_query,
                    ),
                    "context": extract_match_context(
                        pdf_path=document.file_path,
                        page_number=page.page_number,
                        search_text=clean_query,
                    ),
                }
            )

    results = (
        reference_results + text_results
    )[:limit]

    return {
        "query": clean_query,
        "sector_id": sector_id,
        "document_id": document_id,
        "detected_references": extracted_references,
        "total_results": len(results),
        "results": results,
    }
