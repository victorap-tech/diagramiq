from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db


router = APIRouter(
    prefix="/references",
    tags=["Referencias técnicas"],
)


@router.get(
    "",
    response_model=list[schemas.ComponentReferenceResponse],
)
def list_references(
    q: str | None = Query(default=None),
    document_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(models.ComponentReference)

    if q:
        query = query.filter(
            models.ComponentReference.reference.ilike(
                f"%{q.strip()}%"
            )
        )

    if document_id is not None:
        query = (
            query
            .join(models.DocumentPage)
            .filter(
                models.DocumentPage.document_id == document_id
            )
        )

    return (
        query
        .order_by(models.ComponentReference.reference.asc())
        .all()
    )


@router.get("/{reference}")
def find_reference(
    reference: str,
    db: Session = Depends(get_db),
):
    clean_reference = reference.strip().upper()

    results = (
        db.query(
            models.ComponentReference,
            models.DocumentPage,
            models.Document,
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
        .filter(
            models.ComponentReference.reference
            == clean_reference
        )
        .order_by(
            models.Document.id.asc(),
            models.DocumentPage.page_number.asc(),
        )
        .all()
    )

    if not results:
        raise HTTPException(
            status_code=404,
            detail="Referencia no encontrada",
        )

    return [
        {
            "reference": component.reference,
            "component_type": component.component_type,
            "document_id": document.id,
            "document_title": document.title,
            "page_number": page.page_number,
            "page_id": page.id,
            "image_path": page.image_path,
        }
        for component, page, document in results
    ]
