# DiagramIQ v0.13.7 — Vision diagnóstico y compatibilidad

Corrección sobre v0.13.6.

- Mantiene la llamada Anthropic Vision mínima: model, max_tokens, messages e imagen.
- Registra en Railway el status HTTP y detalle real devuelto por Anthropic.
- Registra errores de conexión, respuestas vacías y errores inesperados.
- Registra una vista previa de la respuesta de Vision para diagnosticar JSON inválido.
- El endpoint /vision/analyze conserva el error real en vez de fallar silenciosamente.
- No modifica documentos, PostgreSQL, Bucket, búsquedas ni jerarquía empresa/planta/sector.
