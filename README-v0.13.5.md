# DiagramIQ v0.13.5 — Visor persistente desde Bucket

Base: v0.13.4.

## Corrección

- Corrige el `404 Not Found` al abrir una página después de un deploy.
- El endpoint `/documents/{document_id}/pages/{page_number}/image` ya no depende del PNG temporal generado durante la indexación.
- Si ese PNG no existe, descarga/resuelve el PDF original desde Railway Bucket y renderiza la página solicitada.
- Guarda el resultado en caché temporal para acelerar aperturas posteriores.
- Mantiene PostgreSQL, jerarquía normalizada y el botón Limpiar de búsqueda específica.
- No exige reindexar el documento.
