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
from sqlalchemy import func
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


def get_or_create_sector(
    db: Session,
    sector_id: int | None,
    plant_id: int | None,
    sector_name: str | None,
) -> models.Sector:
    """
    Obtiene un sector existente mediante sector_id o busca/crea
    un sector mediante plant_id + sector_name.
    """

    if sector_id is not None:
        sector = (
            db.query(models.Sector)
            .filter(models.Sector.id == sector_id)
            .first()
        )

        if sector is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sector no encontrado",
            )

        return sector

    if plant_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Debe indicar sector_id o utilizar "
                "plant_id junto con sector_name"
            ),
        )

    clean_sector_name = (sector_name or "").strip()

    if not clean_sector_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "sector_name es obligatorio cuando no se indica sector_id"
            ),
        )

    plant = (
        db.query(models.Plant)
        .filter(models.Plant.id == plant_id)
        .first()
    )

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Planta no encontrada",
        )

    sector = (
        db.query(models.Sector)
        .filter(
            models.Sector.plant_id == plant_id,
            func.lower(models.Sector.name)
            == clean_sector_name.lower(),
        )
        .first()
    )

    if sector is not None:
        return sector

    sector = models.Sector(
        name=clean_sector_name,
        plant_id=plant_id,
    )

    db.add(sector)
    db.flush()

    return sector


@router.post(
    "/upload",
    response_model=schemas.DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    title: str = Form(...),
    file: UploadFile = File(...),

    sector_id: int | None = Form(None),
    plant_id: int | None = Form(None),
    sector_name: str | None = Form(None),

    equipment_id: int | None = Form(None),
    description: str | None = Form(None),
    document_type: str | None = Form(None),

    db: Session = Depends(get_db),
):
    clean_title = title.strip()

    if not clean_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El título es obligatorio",
        )

    sector = get_or_create_sector(
        db=db,
        sector_id=sector_id,
        plant_id=plant_id,
        sector_name=sector_name,
    )

    equipment = None

    if equipment_id is not None:
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

        if equipment.sector_id != sector.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "El equipo seleccionado no pertenece "
                    "al sector indicado"
                ),
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

        with fitz.open(file_path) as pdf:
            page_count = pdf.page_count

            if page_count <= 0:
                raise ValueError("El PDF no contiene páginas")

    except Exception as exc:
        db.rollback()

        if file_path.exists():
            file_path.unlink()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PDF inválido: {str(exc)}",
        )

    finally:
        file.file.close()

    clean_description = (
        description.strip()
        if description and description.strip()
        else None
    )

    clean_document_type = (
        document_type.strip()
        if document_type and document_type.strip()
        else None
    )

    new_document = models.Document(
        title=clean_title,
        filename=original_filename,
        file_path=str(file_path),
        description=clean_description,
        document_type=clean_document_type,
        page_count=page_count,
        processing_status="uploaded",
        sector_id=sector.id,
        equipment_id=equipment.id if equipment else None,
    )

    try:
        db.add(new_document)
        db.commit()
        db.refresh(new_document)

    except Exception as exc:
        db.rollback()

        if file_path.exists():
            file_path.unlink()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo guardar el documento: {str(exc)}",
        )

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
        db.rollback()

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
    sector_id: int | None = None,
    equipment_id: int | None = None,
    processing_status: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Document)

    if sector_id is not None:
        query = query.filter(
            models.Document.sector_id == sector_id
        )

    if equipment_id is not None:
        query = query.filter(
            models.Document.equipment_id == equipment_id
        )

    if processing_status is not None:
        query = query.filter(
            models.Document.processing_status
            == processing_status
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

    page_image_paths = [
        Path(page.image_path)
        for page in document.pages
        if page.image_path
    ]

    pdf_file_path = Path(document.file_path)

    try:
        db.delete(document)
        db.commit()

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo eliminar el documento: {str(exc)}",
        )

    for image_path in page_image_paths:
        if image_path.exists():
            image_path.unlink()

    if pdf_file_path.exists():
        pdf_file_path.unlink()

    return None
