# DiagramIQ v0.14.2

Corrección de reindexación en Railway.

- El worker se reserva antes de lanzar el hilo para evitar carreras.
- Los trabajos `pending` se recuperan al iniciar el deploy.
- Logs `[INDEX]` se imprimen con `flush=True` para verse inmediatamente en Railway.
- Nuevo endpoint `POST /documents/{id}/retry-now` para forzar un worker sin volver a subir el PDF.
- Los fallos no eliminan el PDF ni el registro del documento.
- Mantiene búsqueda y alias de códigos de v0.14.0/v0.14.1.

Deployar normalmente sobre la versión anterior. No hace falta borrar PostgreSQL ni el Bucket.
