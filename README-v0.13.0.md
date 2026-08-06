# DiagramIQ v0.13.0 — Recuperación sin reindexación automática

- El botón **Actualizar** sincroniza los PDF del Bucket con la base de datos.
- No inicia procesamiento ni reindexación automática.
- Los documentos recuperados quedan disponibles para **Ver PDF**.
- Cuando falta el índice, muestran el estado **PDF recuperado; índice faltante** y el botón **Procesar**.
- Cada documento se procesa únicamente por decisión del usuario.
- Evita que un deploy dispare nuevamente miles de páginas de forma automática.

Para conservar también páginas, componentes y relaciones entre deploys, se recomienda usar PostgreSQL persistente mediante `DATABASE_URL`.
