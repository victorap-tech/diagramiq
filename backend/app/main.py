from fastapi import FastAPI

from app.database import Base, engine
from app.routers import (
    documents,
    equipments,
    organizations,
    plants,
    references,
    search,
    sectors,
)

# Crear tablas (solo si no existen)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="DiagramIQ API",
    description="Asistente inteligente para mantenimiento industrial",
    version="0.4.0",
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
# Sistema
# ==========================

@app.get("/", tags=["Sistema"])
def root():
    return {
        "name": "DiagramIQ",
        "version": "0.4.0",
        "status": "online",
        "message": "API de DiagramIQ funcionando correctamente",
    }


@app.get("/health", tags=["Sistema"])
def health():
    return {
        "status": "healthy",
    }
