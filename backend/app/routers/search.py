from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

router = APIRouter(
    prefix="/search",
    tags=["Búsqueda"],
)


@router.get("")
def search_text(
    q: str,
    db: Session = Depends(get_db),
):
    pages = (
        db.query(models.DocumentPage)
        .filter(
            models.DocumentPage.text_content.ilike(f"%{q}%")
        )
        .all()
    )

    results = []

    for page in pages:

        document = (
            db.query(models.Document)
            .filter(
                models.Document.id == page.document_id
            )
            .first()
        )

        text = page.text_content or ""

        pos = text.lower().find(q.lower())

        if pos >= 0:
            start = max(0, pos - 80)
            end = min(len(text), pos + 120)
            fragment = text[start:end]
        else:
            fragment = text[:200]

        results.append(
            {
                "document_id": document.id,
                "title": document.title,
                "page": page.page_number,
                "fragment": fragment,
            }
        )

    return results
