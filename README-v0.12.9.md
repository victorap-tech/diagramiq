# DiagramIQ v0.12.9 — Sincronización de Bucket corregida

- Corrige `NameError: bucket_name is not defined`.
- Importa y valida explícitamente el nombre del Bucket antes de sincronizar.
- Agrega `GET /documents/bucket-status` para diagnóstico seguro.
- Muestra errores reales de credenciales, permisos o listado en lugar de `Internal Server Error`.
- El botón Actualizar comprueba primero la conexión y luego recupera los PDF faltantes.
- No vuelve a subir archivos existentes.
- Reindexa solamente registros recuperados o sin páginas.
