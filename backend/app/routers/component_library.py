from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.routers.component_catalog import _best_model_from_page, infer_manufacturer, infer_type, normalize_term, is_nonphysical_reference
from app.services.storage_service import (
    delete_file,
    get_object_stream,
    is_s3_path,
    resolve_local_file,
    upload_file,
)

router = APIRouter(prefix="/component-library", tags=["Biblioteca técnica"])

ALLOWED_KINDS = {"datasheet", "manual", "plano", "foto", "otro"}
MAX_FILE_SIZE = 50 * 1024 * 1024


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "archivo")
    return cleaned.strip("-._") or "archivo"


def _asset_payload(asset: models.ComponentAsset) -> dict:
    return {
        "id": asset.id,
        "kind": asset.asset_kind,
        "title": asset.title,
        "filename": asset.filename,
        "content_type": asset.content_type or "",
        "file_size": asset.file_size or 0,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "download_url": f"/component-library/assets/{asset.id}/download",
    }


def _reference_or_404(db: Session, reference_id: int) -> models.ComponentReference:
    item = db.query(models.ComponentReference).filter(models.ComponentReference.id == reference_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Componente no encontrado")
    return item


@router.get("/{reference_id}")
def component_library(reference_id: int, db: Session = Depends(get_db)):
    ref = _reference_or_404(db, reference_id)
    page = ref.document_page
    document = page.document if page else None
    sector = document.sector if document else None
    plant = sector.plant if sector else None
    organization = plant.organization if plant else None
    assets = (
        db.query(models.ComponentAsset)
        .filter(models.ComponentAsset.component_reference_id == reference_id)
        .order_by(models.ComponentAsset.created_at.desc(), models.ComponentAsset.id.desc())
        .all()
    )
    model = _best_model_from_page(ref.reference or "", page.text_content if page else "", ref.model)
    manufacturer = infer_manufacturer(model, ref.manufacturer)
    component_type = infer_type(
        ref.reference or "", ref.detected_type, ref.component_type, model, ref.description or ref.row_text
    )
    occurrence_rows = []
    if document and sector:
        target = normalize_term(ref.reference)
        related = (
            db.query(models.ComponentReference, models.DocumentPage)
            .join(models.DocumentPage, models.ComponentReference.document_page_id == models.DocumentPage.id)
            .filter(models.DocumentPage.document_id == document.id)
            .filter(
                (models.ComponentReference.normalized_reference == target)
                | (models.ComponentReference.reference == ref.reference)
            )
            .order_by(models.DocumentPage.page_number.asc(), models.ComponentReference.id.asc())
            .limit(1000)
            .all()
        )
        for related_ref, related_page in related:
            if normalize_term(related_ref.reference) != target:
                continue
            occurrence_rows.append({
                "id": related_ref.id,
                "page_number": related_page.page_number,
                "source_kind": related_ref.source_kind or "",
                "model": _best_model_from_page(related_ref.reference or "", related_page.text_content, related_ref.model),
            })
    # Una sola aparición útil por página/modelo/origen. Las menciones repetidas en
    # la misma página no se muestran como una lista interminable.
    deduped_occurrences = []
    seen_occurrences = set()
    for row in sorted(occurrence_rows, key=lambda value: (value["page_number"], value["id"])):
        key = (row.get("page_number"), normalize_term(row.get("model")), row.get("source_kind") or "")
        if key in seen_occurrences:
            continue
        seen_occurrences.add(key)
        deduped_occurrences.append(row)
    unique_pages = sorted({row["page_number"] for row in deduped_occurrences if row.get("page_number") is not None})
    return {
        "component": {
            "id": ref.id,
            "reference": ref.reference or "",
            "type": component_type,
            "manufacturer": manufacturer,
            "model": model,
            "description": ref.description or ref.row_text or "",
            "confidence": ref.catalog_confidence or 0,
            "source_kind": ref.source_kind or "",
            "document_id": document.id if document else None,
            "document_title": document.title if document else "",
            "page_number": page.page_number if page else None,
            "organization": organization.name if organization else "",
            "plant": plant.name if plant else "",
            "sector": sector.name if sector else "",
        },
        "occurrences": deduped_occurrences,
        "occurrence_summary": {
            "total_mentions": len(occurrence_rows),
            "unique_occurrences": len(deduped_occurrences),
            "page_count": len(unique_pages),
            "pages": unique_pages,
        },
        "assets": [_asset_payload(asset) for asset in assets],
    }


@router.post("/{reference_id}/assets", status_code=201)
def upload_component_asset(
    reference_id: int,
    asset_kind: str = Form(...),
    title: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ref = _reference_or_404(db, reference_id)
    kind = (asset_kind or "").strip().lower()
    if kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="Tipo de documento no válido")
    original_name = _safe_filename(file.filename or "archivo")
    suffix = Path(original_name).suffix
    hasher = hashlib.sha256()
    total = 0

    with NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp_path = Path(temp.name)
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="El archivo supera el límite de 50 MB")
            hasher.update(chunk)
            temp.write(chunk)

    if total <= 0:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    digest = hasher.hexdigest()
    object_key = f"component-library/{ref.id}/{digest[:16]}-{original_name}"
    try:
        stored_path = upload_file(
            temp_path,
            object_key,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo guardar el archivo: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    asset = models.ComponentAsset(
        component_reference_id=ref.id,
        asset_kind=kind,
        title=(title or "").strip() or original_name,
        filename=original_name,
        file_path=stored_path,
        content_type=file.content_type,
        file_size=total,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _asset_payload(asset)


@router.get("/assets/{asset_id}/download")
def download_component_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(models.ComponentAsset).filter(models.ComponentAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if is_s3_path(asset.file_path):
        body, content_length = get_object_stream(asset.file_path)
        headers = {"Content-Disposition": f'inline; filename="{asset.filename}"'}
        if content_length:
            headers["Content-Length"] = str(content_length)
        return StreamingResponse(body, media_type=asset.content_type or "application/octet-stream", headers=headers)
    local_path = resolve_local_file(asset.file_path)
    if not local_path.exists():
        raise HTTPException(status_code=404, detail="El archivo físico no está disponible")
    return FileResponse(
        local_path,
        media_type=asset.content_type or "application/octet-stream",
        filename=asset.filename,
    )


@router.delete("/assets/{asset_id}", status_code=204)
def delete_component_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(models.ComponentAsset).filter(models.ComponentAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    path = asset.file_path
    db.delete(asset)
    db.commit()
    try:
        delete_file(path)
    except Exception:
        pass
    return None
