from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import inspect, text

from app.database import Base, engine
from app.services.storage_service import storage_enabled, bucket_name
from app.routers import (
    documents,
    equipments,
    organizations,
    plants,
    references,
    search,
    sectors,
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
    }
    with engine.begin() as connection:
        for name, definition in definitions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE component_references ADD COLUMN {name} {definition}"))


ensure_reference_columns()

app = FastAPI(
    title="DiagramIQ API",
    description="Asistente inteligente para mantenimiento industrial",
    version="0.6.5",
)

# Ruta absoluta de la carpeta app
BASE_DIR = Path(__file__).resolve().parent

# Servir archivos CSS, JavaScript e imágenes
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

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
        "storage": "railway_bucket" if storage_enabled() else "local",
        "bucket_configured": storage_enabled(),
        "bucket_name": bucket_name() if storage_enabled() else None,
    }
