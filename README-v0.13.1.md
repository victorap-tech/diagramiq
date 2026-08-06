# DiagramIQ v0.13.1 — Jerarquía persistente en PostgreSQL

- Empresa, planta y sector se guardan en PostgreSQL.
- Al sincronizar el Bucket se reconstruye la jerarquía desde el manifiesto de cada PDF.
- Los IDs viejos del Bucket no se reutilizan como identidad; se usan nombres estables.
- Documentos ya registrados reparan automáticamente su vínculo con sector/planta/empresa.
- Después de sincronizar, el frontend recarga los desplegables sin refrescar la página.
- Si existe una única empresa/planta/sector, se selecciona automáticamente.
- Los manifiestos nuevos guardan la jerarquía con `schema_version: 2`.
- PostgreSQL de Railway usa explícitamente el controlador Psycopg 3.
- No inicia reindexaciones automáticas.
