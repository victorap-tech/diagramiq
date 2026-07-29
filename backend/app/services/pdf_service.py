from pathlib import Path

import fitz
from sqlalchemy.orm import Session

from app import models


PAGE_IMAGE_DIR = Path("uploads/pages")
PAGE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def process_pdf_document(
    document: models.Document,
    db: Session,
) -> int:
    """
    Procesa un PDF página por página.

    - Extrae texto.
    - Genera una imagen PNG.
    - Registra cada página en la base de datos.
    """

    pdf_path = Path(document.file_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo: {pdf_path}"
        )

    document.processing_status = "processing"
    db.commit()

    existing_pages = (
        db.query(models.DocumentPage)
        .filter(
            models.DocumentPage.document_id == document.id
        )
        .all()
    )

    for existing_page in existing_pages:
        if existing_page.image_path:
            image_path = Path(existing_page.image_path)

            if image_path.exists():
                image_path.unlink()

        db.delete(existing_page)

    db.commit()

    document_page_dir = PAGE_IMAGE_DIR / str(document.id)
    document_page_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    processed_pages = 0
    pdf = None

    try:
        pdf = fitz.open(pdf_path)

        for page_index in range(pdf.page_count):
            page = pdf.load_page(page_index)

            text_content = page.get_text("text").strip()

            image_filename = (
                f"page_{page_index + 1:04d}.png"
            )

            image_path = (
                document_page_dir / image_filename
            )

            matrix = fitz.Matrix(1.5, 1.5)

            pixmap = page.get_pixmap(
                matrix=matrix,
                alpha=False,
            )

            pixmap.save(str(image_path))

            new_page = models.DocumentPage(
                page_number=page_index + 1,
                text_content=text_content or None,
                image_path=str(image_path),
                document_id=document.id,
            )

            db.add(new_page)
            processed_pages += 1

            # Guardamos en bloques para no acumular
            # cientos de objetos en memoria.
            if processed_pages % 20 == 0:
                db.commit()

        db.commit()

        document.processing_status = "completed"
        document.page_count = pdf.page_count

        db.commit()
        db.refresh(document)

        return processed_pages

    except Exception:
        db.rollback()

        document.processing_status = "error"
        db.commit()

        raise

    finally:
        if pdf is not None:
            pdf.close()
