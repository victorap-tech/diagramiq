# DiagramIQ

Asistente inteligente para mantenimiento industrial.

## Objetivo

DiagramIQ permite cargar diagramas eléctricos, manuales y procedimientos para ayudar a diagnosticar fallas rápidamente.

También permite registrar asistencias, detectar problemas repetitivos y analizar el historial de mantenimiento.

## Tecnología inicial

- FastAPI
- PostgreSQL
- SQLAlchemy
- PyMuPDF
- React
- Railway

## Ejecutar localmente

Desde la carpeta `backend`:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
