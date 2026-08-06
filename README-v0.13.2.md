# DiagramIQ v0.13.2 — Jerarquía obligatoria y persistente

- Gestión de plantas y sectores dentro de Empresas.
- Empresa, planta y sector se guardan en PostgreSQL antes de cargar PDFs.
- La carga de documentos exige una planta y un sector existentes.
- No crea empresas, plantas ni sectores genéricos al sincronizar el Bucket.
- Plantas y sectores se crean de forma idempotente, evitando duplicados.
- Los desplegables de Buscar y Cargar se actualizan después de crear la jerarquía.
- Mantiene Bucket, PostgreSQL, catálogo, asistente y visor de la v0.13.1.
