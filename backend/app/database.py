import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./diagramiq.db",
)

# Railway puede entregar postgresql://. Forzamos el controlador Psycopg 3
# incluido en requirements para no depender de psycopg2 del sistema.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)


connect_args = {}
engine_kwargs = {
    "pool_pre_ping": True,
}

if DATABASE_URL.startswith("sqlite"):
    # SQLite solo admite un escritor a la vez. El timeout evita fallos
    # instantáneos mientras la indexación está guardando un lote.
    connect_args = {
        "check_same_thread": False,
        "timeout": 60,
    }
    # Una conexión corta por request reduce la posibilidad de conservar
    # transacciones y bloqueos entre consultas concurrentes en Railway.
    engine_kwargs["poolclass"] = NullPool


engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            # WAL permite que las búsquedas sigan leyendo mientras el PDF
            # se indexa y escribe en segundo plano.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)


Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()
