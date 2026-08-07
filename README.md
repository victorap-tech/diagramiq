# DiagramIQ v0.14.3 — Deploy seguro

Base: v0.14.2.

## Cambios
- Un deploy/reinicio de Railway no inicia ni reanuda indexaciones automáticamente.
- PostgreSQL y el Bucket son la fuente persistente; el contenedor se trata como temporal.
- Reindexar es una acción manual. Antes de iniciar, DiagramIQ verifica que el PDF original exista y pueda abrirse.
- Si falta el PDF en el Bucket, la reindexación se rechaza sin tocar el índice existente.
- Los contadores existentes se conservan mientras el trabajo está en cola y solo cambian cuando el worker realmente comienza.
- El PDF se valida y se construye el catálogo preliminar antes de borrar páginas del índice anterior.

## Regla de operación
Un deploy no debe cambiar el estado de los documentos. Si hace falta reindexar, se realiza explícitamente desde Documentos.
