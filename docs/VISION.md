# DiagramIQ Vision v0.9.0

Endpoint: `POST /vision/analyze` con campo multipart `image`.

Clasifica automáticamente la foto como `cable_tag`, `component`, `document` o `unknown`, extrae referencia, TAG, marca, modelo y textos visibles, y devuelve `search_query` para buscar en los planos.

Requiere `OPENAI_API_KEY`. Modelo configurable con `OPENAI_VISION_MODEL`.
