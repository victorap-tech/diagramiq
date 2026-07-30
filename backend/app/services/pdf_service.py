import re
from pathlib import Path

import fitz
from sqlalchemy.orm import Session

from app import models


PAGE_IMAGE_DIR = Path("uploads/pages")
PAGE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# Escala usada para generar la imagen PNG.
# Las coordenadas también se guardarán con esta escala,
# para poder dibujar el resaltado directamente sobre la imagen.
RENDER_SCALE = 1.5


REFERENCE_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:"
    r"KM\d+[A-Z0-9_-]*|"
    r"KA\d+[A-Z0-9_-]*|"
    r"QF\d+[A-Z0-9_-]*|"
    r"QS\d+[A-Z0-9_-]*|"
    r"FU\d+[A-Z0-9_-]*|"
    r"FR\d+[A-Z0-9_-]*|"
    r"PLC\d+[A-Z0-9_-]*|"
    r"DI\d+[A-Z0-9_-]*|"
    r"DO\d+[A-Z0-9_-]*|"
    r"AI\d+[A-Z0-9_-]*|"
    r"AO\d+[A-Z0-9_-]*|"
    r"KM\d+[A-Z0-9_-]*|"
    r"M\d+[A-Z0-9_-]*|"
    r"B\d+[A-Z0-9_-]*|"
    r"X\d+[A-Z0-9_-]*|"
    r"V\d+[A-Z0-9_-]*|"
    r"\d+[A-Z]\d+[A-Z0-9_-]*"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)


def normalize_reference(reference: str) -> str:
    """
    Normaliza una referencia para facilitar las búsquedas.

    Ejemplos:
        -570u4  -> 570U4
        KM-03   -> KM-03
        570u4   -> 570U4
    """
    value = reference.strip().upper()

    value = value.strip(
        " \t\r\n.,;:()[]{}<>+=/\\"
    )

    return value


def classify_reference(reference: str) -> str:
    value = normalize_reference(reference)

    if value.startswith("KM"):
        return "Contactor"

    if value.startswith("KA"):
        return "Relé auxiliar"

    if value.startswith("QF"):
        return "Interruptor automático"

    if value.startswith("QS"):
        return "Seccionador"

    if value.startswith("FU"):
        return "Fusible"

    if value.startswith("FR"):
        return "Relé térmico"

    if value.startswith("PLC"):
        return "PLC"

    if value.startswith(("DI", "DO", "AI", "AO")):
        return "Entrada o salida"

    if value.startswith("M"):
        return "Motor"

    if value.startswith("B"):
        return "Sensor"

    if value.startswith("X"):
        return "Bornera o conector"

    if value.startswith("V"):
        return "Variador o referencia V"

    return "Referencia técnica"


def extract_references(text: str) -> list[str]:
    """
    Extrae referencias únicas del texto de una página.
    """
    if not text:
        return []

    matches = REFERENCE_PATTERN.findall(
        text.upper()
    )

    normalized = {
        normalize_reference(match)
        for match in matches
        if normalize_reference(match)
    }

    return sorted(normalized)


def find_reference_rectangles(
    page: fitz.Page,
    reference: str,
) -> list[fitz.Rect]:
    """
    Busca todas las apariciones visuales de una referencia
    dentro de la página y devuelve sus rectángulos.
    """
    try:
        rectangles = page.search_for(
            reference,
            quads=False,
        )

        return rectangles

    except Exception:
        return []


def remove_existing_pages(
    document: models.Document,
    db: Session,
) -> None:
    """
    Elimina páginas y referencias generadas por un
    procesamiento anterior.
    """
    existing_pages = (
        db.query(models.DocumentPage)
        .filter(
            models.DocumentPage.document_id
            == document.id
        )
        .all()
    )

    for existing_page in existing_pages:
        if existing_page.image_path:
            image_path = Path(
                existing_page.image_path
            )

            if image_path.exists():
                image_path.unlink()

        db.delete(existing_page)

    db.flush()


def save_page_references(
    page: fitz.Page,
    text_content: str,
    document_page: models.DocumentPage,
    db: Session,
) -> int:
    """
    Extrae las referencias y guarda cada aparición con
    sus coordenadas sobre la imagen PNG renderizada.
    """
    references = extract_references(
        text_content
    )

    saved_references = 0

    for reference in references:
        rectangles = find_reference_rectangles(
            page=page,
            reference=reference,
        )

        if not rectangles:
            # Se conserva la referencia aunque PyMuPDF
            # no consiga localizar visualmente el texto.
            new_reference = models.ComponentReference(
                reference=reference,
                normalized_reference=reference,
                component_type=classify_reference(
                    reference
                ),
                x=None,
                y=None,
                width=None,
                height=None,
                document_page_id=document_page.id,
            )

            db.add(new_reference)
            saved_references += 1
            continue

        for rectangle in rectangles:
            # page.search_for devuelve coordenadas PDF.
            # Las multiplicamos por la escala de renderizado
            # para que coincidan con el PNG generado.
            x = round(
                rectangle.x0 * RENDER_SCALE
            )
            y = round(
                rectangle.y0 * RENDER_SCALE
            )
            width = round(
                rectangle.width * RENDER_SCALE
            )
            height = round(
                rectangle.height * RENDER_SCALE
            )

            new_reference = models.ComponentReference(
                reference=reference,
                normalized_reference=reference,
                component_type=classify_reference(
                    reference
                ),
                x=x,
                y=y,
                width=width,
                height=height,
                document_page_id=document_page.id,
            )

            db.add(new_reference)
            saved_references += 1

    return saved_references


def process_pdf_document(
    document: models.Document,
    db: Session,
) -> int:
    pdf_path = Path(document.file_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo: {pdf_path}"
        )

    document.processing_status = "processing"
    db.commit()

    pdf: fitz.Document | None = None
    processed_pages = 0

    document_page_dir = (
        PAGE_IMAGE_DIR / str(document.id)
    )

    document_page_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        remove_existing_pages(
            document=document,
            db=db,
        )

        pdf = fitz.open(pdf_path)

        if pdf.page_count <= 0:
            raise ValueError(
                "El documento PDF no contiene páginas"
            )

        matrix = fitz.Matrix(
            RENDER_SCALE,
            RENDER_SCALE,
        )

        for page_index in range(
            pdf.page_count
        ):
            page = pdf.load_page(
                page_index
            )

            text_content = (
                page.get_text("text").strip()
            )

            image_filename = (
                f"page_{page_index + 1:04d}.png"
            )

            image_path = (
                document_page_dir
                / image_filename
            )

            pixmap = page.get_pixmap(
                matrix=matrix,
                alpha=False,
            )

            pixmap.save(
                str(image_path)
            )

            new_page = models.DocumentPage(
                page_number=page_index + 1,
                text_content=(
                    text_content or None
                ),
                image_path=str(image_path),
                document_id=document.id,
            )

            db.add(new_page)
            db.flush()

            save_page_references(
                page=page,
                text_content=text_content,
                document_page=new_page,
                db=db,
            )

            processed_pages += 1

            # En documentos de cientos de páginas,
            # evita acumular toda la transacción en memoria.
            if processed_pages % 20 == 0:
                db.commit()

        document.processing_status = "completed"
        document.page_count = pdf.page_count

        db.commit()
        db.refresh(document)

        return processed_pages

    except Exception:
        db.rollback()

        document_db = (
            db.query(models.Document)
            .filter(
                models.Document.id
                == document.id
            )
            .first()
        )

        if document_db is not None:
            document_db.processing_status = "error"
            db.commit()

        raise

    finally:
        if pdf is not None:
            pdf.close()
