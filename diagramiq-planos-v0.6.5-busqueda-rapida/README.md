# DiagramIQ v0.6.5 — búsqueda rápida indexada

Esta versión evita abrir o descargar el PDF durante cada búsqueda.

## Cambio principal

Al procesar un documento, DiagramIQ guarda en la base de datos:

- palabras normalizadas;
- página y documento;
- coordenadas del recuadro amarillo;
- texto de la fila o zona cercana;
- referencias técnicas y contexto detectado.

El endpoint `/search` consulta exclusivamente ese índice persistente. Esto evita descargar desde Railway Bucket un PDF grande por cada resultado.

## Compatibilidad

- Railway Storage Bucket mediante las variables AWS ya vinculadas.
- PostgreSQL en Railway.
- SQLite para pruebas locales.
- Archivos locales de versiones anteriores.

## Importante después del deploy

Los documentos procesados con versiones anteriores todavía no tienen el nuevo índice de palabras. En la lista de documentos, pulse **Procesar** una vez para cada PDF existente. Los PDFs que se carguen desde esta versión se indexan automáticamente.

Para un plano de miles de páginas, la reindexación inicial puede tardar. Las búsquedas posteriores serán consultas directas a la base de datos.

## API de búsqueda

`GET /search?q=FC011&limit=50&offset=0`

La respuesta incluye:

- `total`: coincidencias totales;
- `count`: resultados de la página actual;
- `has_more`: indica si existen más resultados;
- `search_mode: persistent_database_index`;
- coordenadas y contexto sin volver a leer el PDF.

## Prueba realizada

Se procesó un PDF de prueba y se buscaron una palabra común y una referencia técnica. La búsqueda se resolvió desde la base de datos, conservando recuadro, fila, tipo de componente y modelo.
