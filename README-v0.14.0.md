# DiagramIQ v0.14.0 — Búsqueda estable y alias de códigos

- Restaura y refuerza la búsqueda técnica normal, separada de Vision.
- Compara códigos con `_`, `-`, `.`, `/` como equivalentes.
- Ejemplo: `S7_1`, `S7-1` y `S7.1` encuentran el mismo componente.
- Agrega fallback al índice de texto persistente cuando no existe ficha estructurada.
- Muestra el motivo real de un fallo de reindexación en Documentos.
- No modifica PostgreSQL, Bucket ni las coincidencias de DiagramIQ Vision.
