from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import inspect, text

from app.database import Base, engine
from app.services.storage_service import storage_enabled, bucket_name, storage_config_status
from app.services.vision_provider import provider_status
from app.routers import (
    documents,
    equipments,
    organizations,
    plants,
    references,
    search,
    sectors,
    cable_tags,
    components,
    vision,
    component_catalog,
    component_relations,
    assistant_chat,
)

# Crear tablas solo si no existen
Base.metadata.create_all(bind=engine)


def ensure_reference_columns() -> None:
    """Agrega columnas nuevas cuando se reutiliza una base de versiones anteriores."""
    inspector = inspect(engine)
    if "component_references" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("component_references")}
    definitions = {
        "normalized_reference": "VARCHAR(100)",
        "x": "INTEGER",
        "y": "INTEGER",
        "width": "INTEGER",
        "height": "INTEGER",
        "row_text": "TEXT",
        "description": "TEXT",
        "detected_type": "VARCHAR(100)",
        "model": "VARCHAR(150)",
        "manufacturer": "VARCHAR(120)",
        "source_kind": "VARCHAR(40)",
        "catalog_confidence": "INTEGER NOT NULL DEFAULT 0",
    }
    with engine.begin() as connection:
        for name, definition in definitions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE component_references ADD COLUMN {name} {definition}"))


ensure_reference_columns()


def ensure_page_columns() -> None:
    inspector = inspect(engine)
    if "document_pages" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("document_pages")}
    with engine.begin() as connection:
        if "page_type" not in existing:
            connection.execute(text("ALTER TABLE document_pages ADD COLUMN page_type VARCHAR(40) DEFAULT 'unknown'"))


ensure_page_columns()


def ensure_document_columns() -> None:
    """Agrega el hash a bases existentes sin borrar documentos ni índices."""
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("documents")}
    with engine.begin() as connection:
        if "content_hash" not in existing:
            connection.execute(text("ALTER TABLE documents ADD COLUMN content_hash VARCHAR(64)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)"))


ensure_document_columns()


def ensure_connection_columns() -> None:
    """Mantiene compatible la base existente sin borrar documentos."""
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("documents")}
    with engine.begin() as connection:
        if "connection_status" not in existing:
            connection.execute(text("ALTER TABLE documents ADD COLUMN connection_status VARCHAR(50) NOT NULL DEFAULT 'pending'"))
        if "connection_count" not in existing:
            connection.execute(text("ALTER TABLE documents ADD COLUMN connection_count INTEGER NOT NULL DEFAULT 0"))


ensure_connection_columns()

def ensure_processing_columns() -> None:
    """Agrega el seguimiento de progreso sin borrar datos existentes."""
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("documents")}
    definitions = {
        "processing_stage": "VARCHAR(80)",
        "processing_progress": "INTEGER NOT NULL DEFAULT 0",
        "processed_pages": "INTEGER NOT NULL DEFAULT 0",
        "detected_components": "INTEGER NOT NULL DEFAULT 0",
        "detected_terms": "INTEGER NOT NULL DEFAULT 0",
        "processing_message": "TEXT",
    }
    with engine.begin() as connection:
        for name, definition in definitions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE documents ADD COLUMN {name} {definition}"))


ensure_processing_columns()

app = FastAPI(
    title="DiagramIQ API",
    description="Asistente inteligente para mantenimiento industrial",
    version="0.10.8",
)

APP_VERSION = "0.10.8"

# Ruta absoluta de la carpeta app
BASE_DIR = Path(__file__).resolve().parent

# Servir archivos CSS, JavaScript e imágenes
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

@app.middleware("http")
async def prevent_stale_frontend_cache(request: Request, call_next):
    """Evita que el celular siga mostrando una versión anterior tras desplegar."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ==========================
# Routers
# ==========================

app.include_router(organizations.router)
app.include_router(plants.router)
app.include_router(sectors.router)
app.include_router(equipments.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(references.router)
app.include_router(cable_tags.router)
app.include_router(components.router)
app.include_router(vision.router)
app.include_router(component_catalog.router)
app.include_router(component_relations.router)
app.include_router(assistant_chat.router)

# ==========================
# Frontend
# ==========================

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(BASE_DIR / "static" / "index.html")

# ==========================
# Sistema
# ==========================

@app.get("/health", tags=["Sistema"])
def health():
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "storage": "railway_bucket" if storage_enabled() else "local",
        "bucket_configured": storage_enabled(),
        "bucket_name": bucket_name(),
        "storage_config": storage_config_status(),
        "ai": provider_status(),
    }
