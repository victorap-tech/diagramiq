import hashlib
import logging
import re
import shutil
import threading
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import SessionLocal, get_db
from app.services.pdf_service import process_pdf_document
from app.services.storage_service import (
    delete_file, get_json, get_object_stream, is_s3_path, list_objects, put_json, resolve_local_file, storage_enabled, upload_file,
    bucket_name, storage_config_status,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/documents",
    tags=["Documentos"],
)


BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = BASE_DIR / "uploads" / "documents"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def calculate_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_document_files(document: models.Document) -> None:
    """Elimina el PDF, las imágenes renderizadas y la copia de caché."""
    for page in list(document.pages):
        if not page.image_path:
            continue
        try:
            image_path = Path(page.image_path)
            if image_path.exists():
                image_path.unlink()
        except Exception:
            pass

    try:
        delete_file(document.file_path)
    except Exception:
        pass


def _document_priority(document: models.Document) -> tuple[int, int, int]:
    """Elige el registro más útil: procesado, con páginas y luego el más antiguo."""
    status_value = (document.processing_status or "").lower()
    completed = 1 if status_value in {"completed", "processed"} else 0
    has_pages = 1 if document.pages else 0
    return (completed, has_pages, -document.id)


def consolidate_duplicate_documents(
    db: Session,
    documents: list[models.Document],
) -> tuple[models.Document | None, int]:
    """Conserva un solo registro y limpia los duplicados del Bucket y la DB."""
    unique = {document.id: document for document in documents}
    candidates = list(unique.values())
    if not candidates:
        return None, 0

    keeper = max(candidates, key=_document_priority)
    duplicates = [document for document in candidates if document.id != keeper.id]
    if not duplicates:
        return keeper, 0

    duplicate_files = list(duplicates)
    try:
        for duplicate in duplicates:
            db.delete(duplicate)
        db.commit()
    except Exception:
        db.rollback()
        raise

    for duplicate in duplicate_files:
        _remove_document_files(duplicate)

    return keeper, len(duplicates)


def find_existing_document_by_hash(
    db: Session,
    content_hash: str,
    sector_id: int,
    original_filename: str,
    page_count: int,
) -> models.Document | None:
    """Busca un PDF idéntico, completa hashes antiguos y limpia duplicados."""
    hashed_matches = (
        db.query(models.Document)
        .filter(
            models.Document.sector_id == sector_id,
            models.Document.content_hash == content_hash,
        )
        .order_by(models.Document.id.asc())
        .all()
    )

    # Compatibilidad con documentos cargados antes de v0.7.2.
    legacy_candidates = (
        db.query(models.Document)
        .filter(
            models.Document.sector_id == sector_id,
            models.Document.content_hash.is_(None),
            models.Document.page_count == page_count,
            func.lower(models.Document.filename) == original_filename.lower(),
        )
        .order_by(models.Document.id.asc())
        .all()
    )

    matches = list(hashed_matches)
    changed = False
    for candidate in legacy_candidates:
        try:
            candidate_path = resolve_local_file(candidate.file_path)
            candidate_hash = calculate_sha256(candidate_path)
            candidate.content_hash = candidate_hash
            changed = True
            if candidate_hash == content_hash:
                matches.append(candidate)
        except Exception:
            continue

    if changed:
        try:
            db.commit()
        except Exception:
            db.rollback()

    if not matches:
        return None

    keeper, _ = consolidate_duplicate_documents(db, matches)
    return keeper


_processing_lock = threading.Lock()
_active_processing_ids: set[int] = set()


def process_document_in_background(document_id: int) -> None:
    """Indexa un PDF sin borrar el documento si la tarea falla.

    El estado y el mensaje de error quedan persistidos en PostgreSQL para que
    el documento pueda reintentarse sin volver a subir el archivo del Bucket.
    """
    with _processing_lock:
        if document_id in _active_processing_ids:
            logger.info("[INDEX] Documento %s ya tiene un worker activo", document_id)
            return
        _active_processing_ids.add(document_id)

    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        if document is None:
            logger.warning("[INDEX] Documento %s no existe", document_id)
            return
        logger.info("[INDEX] Iniciando documento %s (%s)", document_id, document.filename)
        process_pdf_document(document=document, db=db)
        logger.info("[INDEX] Documento %s completado", document_id)
    except Exception:
        db.rollback()
        logger.exception("[INDEX] Falló el documento %s", document_id)
        # process_pdf_document ya deja processing_status=error y el motivo
        # persistido. No eliminar PDF, registro ni índices parciales.
    finally:
        db.close()
        with _processing_lock:
            _active_processing_ids.discard(document_id)


def start_document_worker(document_id: int) -> bool:
    """Lanza un worker daemon y evita iniciar dos veces el mismo documento."""
    with _processing_lock:
        if document_id in _active_processing_ids:
            return False
    thread = threading.Thread(
        target=process_document_in_background,
        args=(document_id,),
        name=f"diagramiq-index-{document_id}",
        daemon=True,
    )
    thread.start()
    return True


def recover_queued_documents() -> list[int]:
    """Reanuda trabajos que quedaron en cola tras un deploy/reinicio.

    Solo toma estados pendientes. Los documentos con error requieren una nueva
    orden explícita de Reindexar para no entrar en un bucle de fallos.
    """
    db = SessionLocal()
    try:
        queued = (
            db.query(models.Document)
            .filter(models.Document.processing_status == "pending")
            .order_by(models.Document.id.asc())
            .all()
        )
        ids = [item.id for item in queued]
        for item in queued:
            item.processing_stage = "waiting"
            item.processing_message = "Reindexación recuperada tras reinicio"
        if queued:
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("[INDEX] No se pudo recuperar la cola pendiente")
        return []
    finally:
        db.close()

    started: list[int] = []
    for document_id in ids:
        if start_document_worker(document_id):
            started.append(document_id)
    if started:
        logger.info("[INDEX] Cola recuperada; workers iniciados: %s", started)
    return started


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
    background_tasks: BackgroundTasks,
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
    file_path = UPLOAD_DIR / f"tmp_{stored_filename}"

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

    content_hash = calculate_sha256(file_path)
    existing_document = find_existing_document_by_hash(
        db=db,
        content_hash=content_hash,
        sector_id=sector.id,
        original_filename=original_filename,
        page_count=page_count,
    )
    if existing_document is not None:
        if file_path.exists():
            file_path.unlink()
        return existing_document

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

    object_key = f"documents/{sector.plant.organization_id}/{sector.plant_id}/{sector.id}/{content_hash}.pdf"
    try:
        stored_path = upload_file(file_path, object_key)
    except Exception as exc:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo guardar el PDF en el Bucket: {str(exc)}",
        )
    finally:
        if file_path.exists():
            file_path.unlink()

    new_document = models.Document(
        title=clean_title,
        filename=original_filename,
        file_path=stored_path,
        content_hash=content_hash,
        description=clean_description,
        document_type=clean_document_type,
        page_count=page_count,
        processing_status="pending",
        processing_stage="waiting",
        processing_progress=0,
        processed_pages=0,
        processing_message="Esperando para comenzar",
        sector_id=sector.id,
        equipment_id=equipment.id if equipment else None,
    )

    try:
        db.add(new_document)
        db.commit()
        db.refresh(new_document)

        # Manifiesto persistente: permite reconstruir la base desde el Bucket
        # después de un deploy, incluso si la BD local quedó vacía.
        if is_s3_path(stored_path):
            try:
                put_json(
                    object_key.rsplit(".", 1)[0] + ".json",
                    {
                        "schema_version": 1,
                        "title": clean_title,
                        "filename": original_filename,
                        "content_hash": content_hash,
                        "description": clean_description,
                        "document_type": clean_document_type,
                        "page_count": page_count,
                        "organization": {
                            "id": sector.plant.organization.id,
                            "name": sector.plant.organization.name,
                        },
                        "plant": {
                            "id": sector.plant.id,
                            "name": sector.plant.name,
                        },
                        "sector": {
                            "id": sector.id,
                            "name": sector.name,
                        },
                    },
                )
            except Exception:
                # El PDF ya está seguro. Un fallo del manifiesto no debe
                # invalidar la carga principal.
                pass

    except Exception as exc:
        db.rollback()

        try:
            delete_file(stored_path)
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo guardar el documento: {str(exc)}",
        )

    background_tasks.add_task(process_document_in_background, new_document.id)

    return new_document



_BUCKET_DOCUMENT_RE = re.compile(
    r"^documents/(?P<organization_id>\d+)/(?P<plant_id>\d+)/(?P<sector_id>\d+)/(?P<hash>[0-9a-fA-F]{64})\.pdf$"
)


def _safe_name(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text[:150] if text else fallback


def _manifest_hierarchy(manifest: dict | None) -> tuple[str | None, str | None, str | None]:
    manifest = manifest or {}
    organization_data = manifest.get("organization") if isinstance(manifest.get("organization"), dict) else {}
    plant_data = manifest.get("plant") if isinstance(manifest.get("plant"), dict) else {}
    sector_data = manifest.get("sector") if isinstance(manifest.get("sector"), dict) else {}
    return (
        str(organization_data.get("name") or "").strip() or None,
        str(plant_data.get("name") or "").strip() or None,
        str(sector_data.get("name") or "").strip() or None,
    )


def _update_manifest_hierarchy(
    object_key: str,
    document: models.Document,
) -> None:
    """Persiste nombres estables para reconstruir la jerarquía en otra BD."""
    sector = document.sector
    plant = sector.plant if sector else None
    organization = plant.organization if plant else None
    if not (sector and plant and organization):
        return
    manifest_key = object_key.rsplit(".", 1)[0] + ".json"
    current = get_json(manifest_key) or {}
    current.update({
        "schema_version": 2,
        "title": document.title,
        "filename": document.filename,
        "content_hash": document.content_hash,
        "description": document.description,
        "document_type": document.document_type,
        "page_count": document.page_count,
        "organization": {"id": organization.id, "name": organization.name},
        "plant": {"id": plant.id, "name": plant.name},
        "sector": {"id": sector.id, "name": sector.name},
    })
    put_json(manifest_key, current)


def _recover_hierarchy(
    db: Session,
    organization_id: int,
    plant_id: int,
    sector_id: int,
    manifest: dict | None,
) -> models.Sector:
    """Recupera la jerarquía por nombre y la guarda permanentemente.

    Los IDs incrustados en la ruta del Bucket pertenecen a una BD anterior y
    no son confiables en PostgreSQL nuevo. Los nombres del manifiesto son la
    identidad estable; los IDs solo se usan como respaldo para archivos viejos.
    """
    organization_name, plant_name, sector_name = _manifest_hierarchy(manifest)
    if not organization_name or not plant_name or not sector_name:
        raise ValueError(
            "El PDF no tiene manifiesto completo de empresa, planta y sector. "
            "Asignalo manualmente o volvé a cargarlo con la jerarquía seleccionada."
        )
    organization_name = _safe_name(organization_name, organization_name)
    plant_name = _safe_name(plant_name, plant_name)
    sector_name = _safe_name(sector_name, sector_name)

    organization = (
        db.query(models.Organization)
        .filter(func.lower(models.Organization.name) == organization_name.lower())
        .first()
    )
    if organization is None:
        organization = models.Organization(name=organization_name)
        db.add(organization)
        db.flush()

    plant = (
        db.query(models.Plant)
        .filter(
            models.Plant.organization_id == organization.id,
            func.lower(models.Plant.name) == plant_name.lower(),
        )
        .first()
    )
    if plant is None:
        plant = models.Plant(name=plant_name, organization_id=organization.id)
        db.add(plant)
        db.flush()

    sector = (
        db.query(models.Sector)
        .filter(
            models.Sector.plant_id == plant.id,
            func.lower(models.Sector.name) == sector_name.lower(),
        )
        .first()
    )
    if sector is None:
        sector = models.Sector(name=sector_name, plant_id=plant.id)
        db.add(sector)
        db.flush()
    return sector


@router.get("/bucket-status")
def bucket_status():
    """Diagnóstico seguro de la conexión al Bucket, sin exponer secretos."""
    config = storage_config_status()
    result = {**config, "reachable": False, "objects_found": 0, "documents_found": 0, "error": None}
    if not config.get("enabled"):
        result["error"] = "Faltan variables de conexión al Bucket"
        return result
    try:
        objects = list_objects("documents/")
        result["reachable"] = True
        result["objects_found"] = len(objects)
        result["documents_found"] = sum(1 for item in objects if str(item.get("key", "")).lower().endswith(".pdf"))
    except Exception as exc:
        logger.exception("No se pudo consultar el Bucket")
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


@router.post("/sync-bucket")
def sync_documents_from_bucket(
    db: Session = Depends(get_db),
):
    """Sincroniza documents/ del Bucket con la BD sin iniciar indexaciones.

    El Bucket conserva los PDF originales. El índice se reconstruye únicamente
    cuando el usuario pulsa Procesar/Reindexar en un documento concreto.
    """
    if not storage_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El Bucket no está configurado en este servicio",
        )

    configured_bucket = bucket_name()
    if not configured_bucket:
        config = storage_config_status()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo determinar el nombre del Bucket. Variables faltantes: {', '.join(config.get('missing_variables', []))}",
        )

    try:
        bucket_objects = list_objects("documents/")
    except Exception as exc:
        logger.exception("Error listando documents/ en el Bucket")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo listar el Bucket: {type(exc).__name__}: {exc}",
        ) from exc

    pdf_objects = [item for item in bucket_objects if str(item.get("key", "")).lower().endswith(".pdf")]
    found = len(pdf_objects)
    already_registered = 0
    recovered = 0
    index_missing = 0
    ignored = 0

    for item in pdf_objects:
        key = str(item.get("key") or "")
        match = _BUCKET_DOCUMENT_RE.match(key)
        if not match:
            ignored += 1
            continue

        values = match.groupdict()
        content_hash = values["hash"].lower()
        storage_path = f"s3://{configured_bucket}/{key}"
        existing = (
            db.query(models.Document)
            .filter(
                (models.Document.file_path == storage_path)
                | (models.Document.content_hash == content_hash)
            )
            .order_by(models.Document.id.asc())
            .first()
        )
        manifest_key = key.rsplit(".", 1)[0] + ".json"
        manifest = get_json(manifest_key) or {}

        if existing is not None:
            already_registered += 1
            try:
                recovered_sector = _recover_hierarchy(
                    db,
                    int(values["organization_id"]),
                    int(values["plant_id"]),
                    int(values["sector_id"]),
                    manifest,
                )
                if existing.sector_id != recovered_sector.id:
                    existing.sector_id = recovered_sector.id
                # Completa metadatos antiguos cuando ahora existe manifiesto.
                if manifest.get("title"):
                    existing.title = _safe_name(manifest.get("title"), existing.title)
                if manifest.get("filename"):
                    existing.filename = _safe_name(manifest.get("filename"), existing.filename)
                db.flush()
                _update_manifest_hierarchy(key, existing)
            except Exception as exc:
                logger.warning("No se pudo reparar la jerarquía de %s: %s", key, exc)
            # Si el PDF existe pero el índice no, lo deja disponible sin procesarlo.
            if not existing.pages and str(existing.processing_status or "").lower() != "processing":
                existing.processing_status = "uploaded"
                existing.processing_stage = "index_missing"
                existing.processing_progress = 0
                existing.processed_pages = 0
                existing.processing_message = "PDF recuperado; índice faltante. Procesar manualmente"
                index_missing += 1
            db.commit()
            continue
        try:
            sector = _recover_hierarchy(
                db,
                int(values["organization_id"]),
                int(values["plant_id"]),
                int(values["sector_id"]),
                manifest,
            )
            title = _safe_name(manifest.get("title"), f"Documento recuperado {content_hash[:12]}")
            filename = _safe_name(manifest.get("filename"), f"{content_hash}.pdf")
            page_count = manifest.get("page_count")
            try:
                page_count = int(page_count) if page_count is not None else None
            except (TypeError, ValueError):
                page_count = None

            document = models.Document(
                title=title,
                filename=filename,
                file_path=storage_path,
                content_hash=content_hash,
                description=(str(manifest.get("description")).strip() if manifest.get("description") else "Recuperado automáticamente desde el Bucket"),
                document_type=(str(manifest.get("document_type")).strip() if manifest.get("document_type") else "plano_electrico"),
                page_count=page_count,
                processing_status="uploaded",
                processing_stage="index_missing",
                processing_progress=0,
                processed_pages=0,
                processing_message="PDF recuperado; índice faltante. Procesar manualmente",
                sector_id=sector.id,
            )
            db.add(document)
            db.commit()
            db.refresh(document)
            recovered += 1
            index_missing += 1
        except Exception as exc:
            db.rollback()
            ignored += 1
            logger.exception("No se pudo recuperar el objeto %s: %s", key, exc)

    return {
        "found": found,
        "already_registered": already_registered,
        "recovered": recovered,
        "queued_for_indexing": 0,
        "index_missing": index_missing,
        "ignored": ignored,
        "organizations": db.query(models.Organization).count(),
        "plants": db.query(models.Plant).count(),
        "sectors": db.query(models.Sector).count(),
        "message": (
            f"Bucket sincronizado: {found} PDF encontrados, "
            f"{already_registered} ya registrados y {recovered} recuperados. "
            f"No se inició ninguna indexación. {index_missing} documento(s) requieren procesamiento manual."
        ),
    }


@router.post("/cleanup-duplicates")
def cleanup_duplicate_documents(db: Session = Depends(get_db)):
    """Calcula hashes faltantes y elimina copias idénticas, conservando una."""
    documents = db.query(models.Document).order_by(models.Document.id.asc()).all()
    groups: dict[tuple[int, str], list[models.Document]] = {}
    skipped = 0

    for document in documents:
        content_hash = document.content_hash
        if not content_hash:
            try:
                content_hash = calculate_sha256(resolve_local_file(document.file_path))
                document.content_hash = content_hash
                db.flush()
            except Exception:
                skipped += 1
                continue
        groups.setdefault((document.sector_id, content_hash), []).append(document)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"No se pudieron actualizar los hashes: {exc}")

    removed = 0
    kept = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        _, deleted_count = consolidate_duplicate_documents(db, group)
        removed += deleted_count
        kept += 1

    return {
        "message": f"Limpieza terminada: {removed} duplicado(s) eliminado(s).",
        "removed": removed,
        "groups_consolidated": kept,
        "skipped": skipped,
    }


@router.get("/{document_id}/progress")
def document_progress(document_id: int, db: Session = Depends(get_db)):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    total = document.page_count or 0
    return {
        "document_id": document.id,
        "status": document.processing_status,
        "stage": document.processing_stage,
        "progress": document.processing_progress or 0,
        "processed_pages": document.processed_pages or 0,
        "total_pages": total,
        "components": document.detected_components or 0,
        "terms": document.detected_terms or 0,
        "relations": document.connection_count or 0,
        "message": document.processing_message,
    }


@router.post("/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
def reindex_document(document_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if document.processing_status == "processing":
        raise HTTPException(status_code=409, detail="El documento ya se está procesando")
    document.processing_status = "pending"
    document.processing_stage = "waiting"
    document.processing_progress = 0
    document.processed_pages = 0
    document.processing_message = "Reindexación en cola"
    db.commit()
    started = start_document_worker(document.id)
    if not started:
        logger.info("[INDEX] Documento %s ya estaba siendo procesado", document.id)
    return {"message": "Reindexación iniciada", "document_id": document.id, "worker_started": started}


@router.post("/{document_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_document_processing(document_id: int, db: Session = Depends(get_db)):
    """Solicita la cancelación segura del procesamiento en segundo plano."""
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    current = (document.processing_status or "").lower()
    if current not in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail="El documento no se está procesando")
    document.processing_status = "cancel_requested"
    document.processing_message = "Cancelación solicitada"
    db.commit()
    return {"message": "Cancelación solicitada", "document_id": document.id}


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


@router.get("/{document_id}/pages/{page_number}/image", include_in_schema=False)
def get_document_page_image(
    document_id: int,
    page_number: int,
    scale: float = 1.5,
    db: Session = Depends(get_db),
):
    """Devuelve la página aunque el PNG temporal se haya perdido en un deploy.

    Primero reutiliza la imagen preprocesada si todavía existe. Si no existe,
    resuelve el PDF original (incluido S3/Railway Bucket), renderiza la página
    solicitada y la guarda en un caché temporal.
    """
    page = db.query(models.DocumentPage).filter(
        models.DocumentPage.document_id == document_id,
        models.DocumentPage.page_number == page_number,
    ).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Página no encontrada")

    requested_scale = max(1.0, min(float(scale or 1.5), 4.0))
    if requested_scale <= 1.6 and page.image_path:
        image_path = Path(page.image_path)
        if image_path.exists():
            return FileResponse(image_path, media_type="image/png")

    document = db.query(models.Document).filter(
        models.Document.id == document_id
    ).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    try:
        local_pdf = resolve_local_file(document.file_path)
        cache_dir = Path("/tmp/diagramiq-page-cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        scale_key = str(requested_scale).replace(".", "_")
        cache_path = cache_dir / f"doc_{document_id}_page_{page_number}_s{scale_key}.png"

        if not cache_path.exists():
            pdf = fitz.open(str(local_pdf))
            try:
                page_index = int(page_number) - 1
                if page_index < 0 or page_index >= pdf.page_count:
                    raise ValueError("Número de página fuera de rango")
                pdf_page = pdf.load_page(page_index)
                pixmap = pdf_page.get_pixmap(
                    matrix=fitz.Matrix(requested_scale, requested_scale),
                    alpha=False,
                )
                pixmap.save(str(cache_path))
            finally:
                pdf.close()

        return FileResponse(
            cache_path,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as exc:
        # Último respaldo: usa el PNG preprocesado si reapareció o sigue montado.
        if page.image_path:
            image_path = Path(page.image_path)
            if image_path.exists():
                return FileResponse(image_path, media_type="image/png")
        raise HTTPException(
            status_code=404,
            detail=f"No se pudo renderizar la página desde el PDF: {exc}",
        )


@router.get("/pages/{page_id}/image", include_in_schema=False)
def get_page_image_by_id(
    page_id: int,
    scale: float = 1.5,
    db: Session = Depends(get_db),
):
    page = db.query(models.DocumentPage).filter(models.DocumentPage.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Página no encontrada")

    # Escala base: usa el PNG preprocesado. Para zoom nítido, renderiza el PDF original
    # a la escala solicitada y cachea el resultado temporalmente.
    requested_scale = max(1.0, min(float(scale or 1.5), 4.0))
    if requested_scale <= 1.6 and page.image_path:
        image_path = Path(page.image_path)
        if image_path.exists():
            return FileResponse(image_path, media_type="image/png")

    document = db.query(models.Document).filter(models.Document.id == page.document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    try:
        local_pdf = resolve_local_file(document.file_path)
        cache_dir = Path("/tmp/diagramiq-hires")
        cache_dir.mkdir(parents=True, exist_ok=True)
        scale_key = str(requested_scale).replace(".", "_")
        cache_path = cache_dir / f"page_{page.id}_s{scale_key}.png"
        if not cache_path.exists():
            pdf = fitz.open(str(local_pdf))
            try:
                pdf_page = pdf.load_page(max(0, int(page.page_number) - 1))
                pixmap = pdf_page.get_pixmap(
                    matrix=fitz.Matrix(requested_scale, requested_scale),
                    alpha=False,
                )
                pixmap.save(str(cache_path))
            finally:
                pdf.close()
        return FileResponse(cache_path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        if page.image_path:
            image_path = Path(page.image_path)
            if image_path.exists():
                return FileResponse(image_path, media_type="image/png")
        raise HTTPException(status_code=404, detail="No se pudo renderizar la página")




@router.get("/{document_id}/file", include_in_schema=False)
def open_document_file(
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

    if is_s3_path(document.file_path):
        try:
            body, content_length = get_object_stream(document.file_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se pudo leer el PDF del Bucket: {str(exc)}",
            )
        headers = {
            "Content-Disposition": f'inline; filename="{document.filename}"',
            "Accept-Ranges": "bytes",
        }
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        return StreamingResponse(body, media_type="application/pdf", headers=headers)

    file_path = Path(document.file_path)
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="El archivo PDF ya no existe")
    return FileResponse(
        path=file_path, media_type="application/pdf", filename=document.filename,
        content_disposition_type="inline",
    )


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


@router.patch(
    "/{document_id}/move-sector",
    response_model=schemas.DocumentResponse,
)
def move_document_sector(
    document_id: int,
    payload: schemas.DocumentMove,
    db: Session = Depends(get_db),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    sector = db.query(models.Sector).filter(models.Sector.id == payload.sector_id).first()
    if sector is None:
        raise HTTPException(status_code=404, detail="Sector de destino no encontrado")
    document.sector_id = sector.id
    db.commit()
    db.refresh(document)
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

    document_storage_path = document.file_path

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
        try:
            if image_path.exists():
                image_path.unlink()
        except Exception:
            pass

    try:
        delete_file(document_storage_path)
    except Exception:
        pass

    return None
