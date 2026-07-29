from fastapi import FastAPI
from app.database import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="DiagramIQ API",
    description="Asistente inteligente para mantenimiento industrial",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "name": "DiagramIQ",
        "version": "0.1.0",
        "status": "online",
        "message": "API de DiagramIQ funcionando correctamente",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }
