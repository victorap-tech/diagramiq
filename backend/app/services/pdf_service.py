import re
from pathlib import Path

import fitz
from sqlalchemy.orm import Session

from app import models
from app.services.storage_service import resolve_local_file
from app.services.connection_indexer import rebuild_document_connections


BASE_DIR = Path(__file__).resolve().parents[2]
PAGE_IMAGE_DIR = BASE_DIR / "uploads" / "pages"
PAGE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# Escala usada para generar la imagen PNG.
# Las coordenadas también se guardarán con esta escala,
# para poder dibujar el resaltado directamente sobre la imagen.
RENDER_SCALE = 1.5


REFERENCE_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:"
    # Designaciones IEC de componentes. DI/DO/AI/AO deben llevar número
    # para no confundir palabras del borde como DIESES.
    r"[-=+]?(?:(?:KM|KA|KE|QF|QS|QA|FU|FR|FC|PLC|XD|XT|X|M|B|V)[A-Z0-9]+"
    r"|(?:DI|DO|AI|AO)\d+[A-Z0-9]*)"
    r"(?:[_./-][A-Z0-9]+)*|"
    # Potenciales y nombres de conductores: 401_A1+, 24VDC+, L1, N, PE.
    r"\d{2,}[A-Z0-9]*(?:_[A-Z0-9]+)+(?:[+-])?|"
    r"(?:24VDC|24VAC|230VAC|400VAC)[+-]?|"
    r"(?:L[123]|N|PE)"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)

INVALID_REFERENCE_WORDS = {
    "DIESES", "PIEZA", "PIEZAS", "LISTA", "PLANO", "PAGINA", "PÁGINA",
    "INDICE", "ÍNDICE", "DOCUMENTO", "DESCRIPCION", "DESCRIPCIÓN",
}



def normalize_reference(reference: str) -> str:
    """
    Normaliza una referencia para facilitar las búsquedas.

    Ejemplos:
        -570u4  -> 570U4
        KM-03   -> KM-03
        570u4   -> 570U4
    """
    value = reference.strip().upper()
    value = value.strip(" \t\r\n.,;:()[]{}<>/\\")
    # En planos EPLAN los signos iniciales suelen ser prefijos gráficos.
    value = value.lstrip("=-")
    return value


def classify_reference(reference: str) -> str:
    value = normalize_reference(reference)

    if value.startswith("KM"):
        return "Contactor"

    if value.startswith("KA"):
        return "Relé auxiliar"

    if value.startswith("QF"):
        return "Interruptor automático"

    if value.startswith("QA"):
        return "Interruptor o actuador"

    if value.startswith("FC"):
        return "Contacto o fin de carrera"

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

    if value.startswith(("XD", "XT", "X")):
        return "Bornera o conector"

    if value.startswith("V"):
        return "Variador o referencia V"

    return "Referencia técnica"


def is_valid_component_reference(reference: str) -> bool:
    value = normalize_reference(reference)
    if not value or value in INVALID_REFERENCE_WORDS:
        return False
    # E/S de PLC válidas: DI1, DO12, AI3, AO4. No palabras como DIESES.
    if value.startswith(("DI", "DO", "AI", "AO")):
        return bool(re.fullmatch(r"(?:DI|DO|AI|AO)\d+[A-Z0-9]*(?:[_./-][A-Z0-9]+)*", value))
    # Una referencia alfabética sin número sólo es válida para potenciales.
    if value not in {"N", "PE"} and not any(ch.isdigit() for ch in value):
        return False
    return True


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
        if normalize_reference(match) and is_valid_component_reference(match)
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


def analyze_context_text(row_text: str | None, search_text: str) -> dict:
    combined = (row_text or "").strip()
    upper = combined.upper()
    type_rules = [
        ("INTERRUPTOR GUARDAMOTOR", "Guardamotor"),
        ("GUARDAMOTOR", "Guardamotor"),
        ("CONTACTOR", "Contactor"),
        ("RELÉ TÉRMICO", "Relé térmico"),
        ("RELE TERMICO", "Relé térmico"),
        ("FUSIBLE", "Fusible"),
        ("SECCIONADOR", "Seccionador"),
        ("INTERRUPTOR", "Interruptor"),
        ("SENSOR", "Sensor"),
        ("MOTOR", "Motor"),
        ("VARIADOR", "Variador"),
        ("CONECTOR", "Conector"),
        ("MÓDULO", "Módulo"),
        ("MODULO", "Módulo"),
    ]
    detected_type = next((label for key, label in type_rules if key in upper), None)
    candidates = re.findall(
        r"\b(?:3RV\d+[A-Z0-9-]*|3RT\d+[A-Z0-9-]*|[A-Z]{2,}\d{2,}[A-Z0-9-]*)\b",
        combined, re.IGNORECASE,
    )
    model = next((x for x in candidates if x.upper().startswith(("3RV", "3RT"))), None)
    if model is None:
        model = next((x for x in candidates if x.upper() != search_text.upper()), None)
    description = None
    if combined:
        description = re.sub(re.escape(search_text), "", combined, flags=re.IGNORECASE)
        description = re.sub(r"^[=+\-A-Za-z0-9_/]+\s+", "", description).strip()
        description = re.sub(r"\s{2,}", " ", description).strip(" -:=") or combined
    return {
        "row_text": combined or None,
        "description": description,
        "detected_type": detected_type,
        "model": model,
    }


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
    page_words = page.get_text("words")

    for reference in references:
        rectangles = find_reference_rectangles(
            page=page,
            reference=reference,
        )

        if not rectangles:
            # Se conserva la referencia aunque PyMuPDF no consiga localizarla.
            # No se intenta usar un rectángulo inexistente.
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
                row_text=None,
                description=None,
                detected_type=None,
                model=None,
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

            row_text = row_context_for_word(
                page_words,
                (rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1, reference),
            )
            context = analyze_context_text(row_text, reference)

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
                row_text=context["row_text"],
                description=context["description"],
                detected_type=context["detected_type"],
                model=context["model"],
                document_page_id=document_page.id,
            )

            db.add(new_reference)
            saved_references += 1

    return saved_references




def normalize_search_term(value: str) -> str:
    """Normaliza una palabra sin perder letras acentuadas."""
    return re.sub(r"[^0-9A-ZÁÉÍÓÚÜÑ_-]+", "", (value or "").upper()).strip()


def row_context_for_word(words: list, target: tuple) -> str | None:
    center_y = (target[1] + target[3]) / 2
    tolerance = max(5.0, (target[3] - target[1]) * 1.25)
    row = [w for w in words if abs(((w[1] + w[3]) / 2) - center_y) <= tolerance]
    row.sort(key=lambda w: (round(w[1], 1), w[0]))
    value = " ".join(str(w[4]) for w in row).strip()
    return value or None


def save_page_search_terms(page: fitz.Page, document_page: models.DocumentPage, db: Session) -> int:
    """Guarda cada palabra del PDF una sola vez durante la indexación."""
    words = page.get_text("words")
    saved = 0
    # Conservamos apariciones distintas; permite navegar entre coincidencias.
    for word in words:
        display = str(word[4]).strip()
        term = normalize_search_term(display)
        if len(term) < 2:
            continue
        db.add(models.PageSearchTerm(
            term=term,
            display_text=display[:255],
            x=max(0, round(word[0] * RENDER_SCALE) - 4),
            y=max(0, round(word[1] * RENDER_SCALE) - 4),
            width=max(18, round((word[2] - word[0]) * RENDER_SCALE) + 8),
            height=max(18, round((word[3] - word[1]) * RENDER_SCALE) + 8),
            row_text=row_context_for_word(words, word),
            document_page_id=document_page.id,
        ))
        saved += 1
    return saved

def find_text_coordinates(
    pdf_path: str | Path,
    page_number: int,
    search_text: str,
) -> dict | None:
    """
    Localiza la primera coincidencia de un texto en una página.

    Devuelve coordenadas expresadas sobre la imagen PNG renderizada,
    usando la misma escala que el visor de DiagramIQ.
    """
    clean_text = (search_text or "").strip()

    if not clean_text or page_number < 1:
        return None

    document = None

    try:
        document = fitz.open(str(resolve_local_file(pdf_path)))

        if page_number > document.page_count:
            return None

        page = document.load_page(page_number - 1)
        rectangles = page.search_for(clean_text, quads=False)

        if not rectangles:
            # Si la consulta incluye varias palabras, se intenta localizar
            # la palabra más larga para ofrecer igualmente una referencia
            # visual útil.
            words = sorted(
                {word for word in re.split(r"\s+", clean_text) if len(word) >= 2},
                key=len,
                reverse=True,
            )

            for word in words:
                rectangles = page.search_for(word, quads=False)
                if rectangles:
                    break

        if not rectangles:
            return None

        rectangle = rectangles[0]
        padding = 4

        return {
            "x": max(0, round(rectangle.x0 * RENDER_SCALE) - padding),
            "y": max(0, round(rectangle.y0 * RENDER_SCALE) - padding),
            "width": max(18, round(rectangle.width * RENDER_SCALE) + padding * 2),
            "height": max(18, round(rectangle.height * RENDER_SCALE) + padding * 2),
        }

    except Exception:
        return None

    finally:
        if document is not None:
            document.close()



def extract_match_context(
    pdf_path: str | Path,
    page_number: int,
    search_text: str,
) -> dict:
    """Extrae la fila o zona de texto que rodea una coincidencia."""
    clean_text = (search_text or "").strip()
    empty = {
        "row_text": None,
        "description": None,
        "detected_type": None,
        "model": None,
    }

    if not clean_text or page_number < 1:
        return empty

    document = None
    try:
        document = fitz.open(str(resolve_local_file(pdf_path)))
        if page_number > document.page_count:
            return empty

        page = document.load_page(page_number - 1)
        rectangles = page.search_for(clean_text, quads=False)
        if not rectangles:
            candidates = sorted(
                {w for w in re.split(r"\s+", clean_text) if len(w) >= 2},
                key=len, reverse=True,
            )
            for candidate in candidates:
                rectangles = page.search_for(candidate, quads=False)
                if rectangles:
                    break
        if not rectangles:
            return empty

        hit = rectangles[0]
        words = page.get_text("words")
        tolerance = max(5.0, hit.height * 1.25)
        row_words = [
            w for w in words
            if abs(((w[1] + w[3]) / 2) - ((hit.y0 + hit.y1) / 2)) <= tolerance
        ]
        row_words.sort(key=lambda w: (round(w[1], 1), w[0]))
        row_text = " ".join(str(w[4]) for w in row_words).strip()

        combined = row_text
        upper = combined.upper()

        type_rules = [
            ("GUARDAMOTOR", "Guardamotor"),
            ("INTERRUPTOR GUARDAMOTOR", "Guardamotor"),
            ("CONTACTOR", "Contactor"),
            ("RELÉ TÉRMICO", "Relé térmico"),
            ("RELE TERMICO", "Relé térmico"),
            ("FUSIBLE", "Fusible"),
            ("SECCIONADOR", "Seccionador"),
            ("INTERRUPTOR", "Interruptor"),
            ("SENSOR", "Sensor"),
            ("MOTOR", "Motor"),
            ("CONECTOR", "Conector"),
            ("MÓDULO", "Módulo"),
            ("MODULO", "Módulo"),
        ]
        detected_type = next((label for key, label in type_rules if key in upper), None)

        model_candidates = re.findall(
            r"\b(?:3RV\d+[A-Z0-9-]*|3RT\d+[A-Z0-9-]*|[A-Z]{2,}\d{2,}[A-Z0-9-]*)\b",
            combined, re.IGNORECASE,
        )
        model = next(
            (item for item in model_candidates if item.upper().startswith(("3RV", "3RT"))),
            None,
        )
        if model is None:
            model = next(
                (item for item in model_candidates if item.upper() != clean_text.upper()),
                None,
            )

        description = None
        if row_text:
            # Quita el término buscado para dejar una descripción más legible.
            description = re.sub(re.escape(clean_text), "", row_text, flags=re.IGNORECASE)
            description = re.sub(r"^[=+\-A-Za-z0-9_/]+\s+", "", description).strip()
            description = re.sub(r"\s{2,}", " ", description).strip(" -:=") or row_text

        return {
            "row_text": combined or None,
            "description": description,
            "detected_type": detected_type,
            "model": model,
        }
    except Exception:
        return empty
    finally:
        if document is not None:
            document.close()


def process_pdf_document(
    document: models.Document,
    db: Session,
) -> int:
    pdf_path = resolve_local_file(document.file_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo: {pdf_path}"
        )

    document.processing_status = "processing"
    document.processing_stage = "preparing"
    document.processing_progress = 1
    document.processed_pages = 0
    document.detected_components = 0
    document.detected_terms = 0
    document.processing_message = "Preparando el PDF"
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
        document.page_count = pdf.page_count
        document.processing_stage = "extracting"
        document.processing_progress = 3
        document.processing_message = "Extrayendo texto e indexando páginas"
        db.commit()

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

            component_count = save_page_references(
                page=page,
                text_content=text_content,
                document_page=new_page,
                db=db,
            )
            term_count = save_page_search_terms(
                page=page,
                document_page=new_page,
                db=db,
            )

            processed_pages += 1
            document.processed_pages = processed_pages
            document.detected_components = (document.detected_components or 0) + component_count
            document.detected_terms = (document.detected_terms or 0) + term_count
            document.processing_stage = "indexing"
            document.processing_progress = min(88, 5 + round((processed_pages / pdf.page_count) * 83))
            document.processing_message = f"Página {processed_pages} de {pdf.page_count}"

            # Mantiene las transacciones cortas para que SQLite no bloquee
            # las búsquedas mientras se indexa un PDF grande.
            if processed_pages % 5 == 0:
                db.commit()

        document.processing_status = "processing"
        document.processing_stage = "connections"
        document.processing_progress = 92
        document.processing_message = "Generando relaciones entre componentes"
        document.page_count = pdf.page_count
        document.connection_status = "pending"

        db.commit()
        # Segunda etapa: precalcula relaciones una sola vez. Las búsquedas normales
        # siguen consultando el índice existente y no esperan este análisis.
        rebuild_document_connections(document.id, db)
        db.refresh(document)
        document.processing_status = "completed"
        document.processing_stage = "completed"
        document.processing_progress = 100
        document.processing_message = "Procesamiento completado"
        db.commit()

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
            document_db.processing_stage = "error"
            document_db.processing_message = "El procesamiento terminó con error"
            document_db.connection_status = "error"
            db.commit()

        raise

    finally:
        if pdf is not None:
            pdf.close()
