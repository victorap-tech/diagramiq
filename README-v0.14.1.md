# DiagramIQ v0.14.1 — Cola de reindexación recuperable

- Retoma automáticamente documentos con `processing_status=pending` al iniciar Railway.
- Reindexar inicia un worker real inmediatamente, sin depender de una tarea HTTP efímera.
- Evita workers duplicados para el mismo documento.
- Si la indexación falla, conserva el documento y el PDF del Bucket; ya no borra el registro.
- Railway registra `[INDEX]` con inicio, finalización y traceback de errores.
- Mantiene las mejoras de v0.14.0: búsqueda estable y equivalencia de separadores en códigos.
