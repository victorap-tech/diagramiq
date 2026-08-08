from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
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
    component_library,
    auth,
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
    version="0.15.4",
)

APP_VERSION = "0.15.4"

# Ruta absoluta de la carpeta app
BASE_DIR = Path(__file__).resolve().parent

# Servir archivos CSS, JavaScript e imágenes
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

# Rutas públicas mínimas. Todo lo demás requiere sesión.
PUBLIC_PATHS = {"/login", "/auth/login", "/auth/status", "/health"}
PUBLIC_PREFIXES = ("/static/",)

# Límite básico por IP para endpoints costosos de IA.
from collections import defaultdict, deque
import time
_ai_requests = defaultdict(deque)
AI_WINDOW_SECONDS = 60
AI_MAX_REQUESTS = 30

@app.middleware("http")
async def security_gate(request: Request, call_next):
    path = request.url.path
    is_public = path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)

    if path == "/login":
        if auth.request_is_authenticated(request):
            return RedirectResponse(url="/", status_code=303)
        return FileResponse(BASE_DIR / "static" / "login.html")

    if not is_public and not auth.request_is_authenticated(request):
        accepts_html = "text/html" in request.headers.get("accept", "")
        if request.method == "GET" and accepts_html:
            return RedirectResponse(url="/login", status_code=303)
        return JSONResponse(status_code=401, content={"detail": "Sesión requerida."})

    if auth.request_is_authenticated(request) and (path.startswith("/assistant/") or path.startswith("/vision/") or path.startswith("/components/recognize") or path.startswith("/cable-tags/recognize")):
        forwarded = request.headers.get("x-forwarded-for", "")
        key = forwarded.split(",", 1)[0].strip() if forwarded else (request.client.host if request.client else "unknown")
        now = time.time()
        bucket = _ai_requests[key]
        while bucket and bucket[0] < now - AI_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= AI_MAX_REQUESTS:
            return JSONResponse(status_code=429, content={"detail": "Demasiadas consultas de IA. Esperá un minuto."})
        bucket.append(now)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    return response


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
app.include_router(component_library.router)
app.include_router(auth.router)


@app.on_event("startup")
def deploy_safe_startup() -> None:
    """Arranque seguro: un deploy nunca inicia ni modifica trabajos de indexación."""
    print("[DEPLOY-SAFE] Inicio sin reindexación automática; PostgreSQL y Bucket permanecen intactos", flush=True)

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
