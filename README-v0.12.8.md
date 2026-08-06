# DiagramIQ v0.12.8 — Sincronización persistente del Bucket

- El botón **Actualizar** de Documentos ahora sincroniza `documents/` del Bucket con la base de datos.
- Recupera PDFs cuyo archivo existe pero cuyo registro desapareció después de un deploy.
- Evita duplicados mediante SHA-256 y ruta del objeto.
- Reindexa únicamente documentos recuperados o registros sin páginas; no vuelve a subir el PDF.
- Las nuevas cargas guardan un manifiesto JSON junto al PDF con título, nombre original y jerarquía Empresa/Planta/Sector.
- Los PDFs antiguos sin manifiesto también se recuperan usando la estructura de carpetas del Bucket.
