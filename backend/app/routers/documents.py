import shutil
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.pdf_service import process_pdf_document


router = APIRouter(
    prefix="/documents",
    tags=["Documentos"],
)


UPLOAD_DIR = Path("uploads/documents")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post(
    "/upload",
    response_model=schemas.DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    equipment_id: int = Form(...),
    title: str = Form(...),
    document_type: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    equipment = (
        db.query(models.Equipment)
        .filter(models.Equipment.id == equipment_id)
        .first()
    )

    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Equipo no encontrado",
        )

    clean_title = title.strip()

    if not clean_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El título es obligatorio",
        )

    original_filename = file.filename or "document.pdf"
    extension = Path(original_filename).suffix.lower()

    if extension != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Solo se permiten archivos PDF",
        )

    stored_filename = f"{uuid4().hex}.pdf"
    file_path = UPLOAD_DIR / stored_filename

    try:
        with file_path.open("wb") as destination:
            shutil.copyfileobj(
                file.file,
                destination,
            )

        pdf = fitz.open(file_path)
        page_count = pdf.page_count
        pdf.close()

    except Exception as exc:
        if file_path.exists():
            file_path.unlink()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PDF inválido: {str(exc)}",
        )

    new_document = models.Document(
        title=clean_title,
        filename=original_filename,
        file_path=str(file_path),
        document_type=document_type,
        page_count=page_count,
        processing_status="uploaded",
        equipment_id=equipment_id,
    )

    db.add(new_document)
    db.commit()
    db.refresh(new_document)

    return new_document


@router.post(
    "/{document_id}/process",
    response_model=schemas.DocumentProcessResponse,
)
def process_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    document = (
        db.query(models.Document)
        .filter(models.Document.id == document_id)
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado",
        )

    try:
        processed_pages = process_pdf_document(
            document=document,
            db=db,
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando el PDF: {str(exc)}",
        )

    return schemas.DocumentProcessResponse(
        document_id=document.id,
        processing_status=document.processing_status,
        processed_pages=processed_pages,
        message="Documento procesado correctamente",
    )


@router.get(
    "",
    response_model=list[schemas.DocumentResponse],
)
def list_documents(
    equipment_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Document)

    if equipment_id is not None:
        query = query.filter(
            models.Document.equipment_id == equipment_id
        )

    return (
        query
        .order_by(models.Document.id.desc())
        .all()
    )


@router.get(
    "/{document_id}/pages",
    response_model=list[schemas.DocumentPageResponse],
)
def list_document_pages(
    document_id: int,
    db: Session = Depends(get_db),
):
    document = (
        db.query(models.Document)
        .filter(models.Document.id == document_id)
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado",
        )

    return (
        db.query(models.DocumentPage)
        .filter(
            models.DocumentPage.document_id == document_id
        )
        .order_by(models.DocumentPage.page_number.asc())
        .all()
    )


@router.get(
    "/{document_id}/pages/{page_number}",
    response_model=schemas.DocumentPageResponse,
)
def get_document_page(
    document_id: int,
    page_number: int,
    db: Session = Depends(get_db),
):
    page = (
        db.query(models.DocumentPage)
        .filter(
            models.DocumentPage.document_id == document_id,
            models.DocumentPage.page_number == page_number,
        )
        .first()
    )

    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Página no encontrada",
        )

    return page


@router.get(
    "/{document_id}",
    response_model=schemas.DocumentResponse,
)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    document = (
        db.query(models.Document)
        .filter(models.Document.id == document_id)
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado",
        )

    return document


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    document = (
        db.query(models.Document)
        .filter(models.Document.id == document_id)
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado",
        )

    for page in document.pages:
        if page.image_path:
            image_path = Path(page.image_path)

            if image_path.exists():
                image_path.unlink()

    file_path = Path(document.file_path)

    db.delete(document)
    db.commit()

    if file_path.exists():
        file_path.unlink()

    return None
