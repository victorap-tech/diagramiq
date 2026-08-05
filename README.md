# DiagramIQ v0.9.8

Base: v0.9.5 estable.

## Cambio principal: motor de relaciones precalculadas

- Durante la indexación del PDF crea un índice persistente de conexiones.
- Guarda relaciones por referencia cruzada, proximidad y continuidad entre páginas.
- `Seguir circuito` consulta ese índice y no vuelve a analizar el PDF en cada búsqueda.
- Mantiene compatibilidad con documentos anteriores: si aún no tienen índice, usa el método anterior.
- Agrega estado y cantidad de conexiones por documento en la base de datos.
- No cambia el flujo de búsqueda ni agrega demoras a las consultas normales.

Versión visible y API: 0.9.8.


## v0.9.8 — Componente principal

- Prioriza la referencia visual principal del componente sobre tags de cables y continuidades.
- Conserva una aparición principal por página y deja repeticiones como secundarias.
- Envía listados e índices al final de los resultados.
- Amplía el área de enfoque para centrar el símbolo asociado al rótulo.
- La búsqueda sigue consultando únicamente el índice persistente.


## v0.9.8 — OpenAI + Anthropic

Se agregó selección de proveedor mediante `AI_PROVIDER`. Las funciones de Vision, TAG de cable y reconocimiento de componentes usan el proveedor elegido.

Anthropic:
```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_VISION_MODEL=claude-sonnet-5
```

OpenAI:
```env
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_VISION_MODEL=gpt-4.1-mini
```


## v0.10.1 - Centro de procesamiento
- Progreso persistente por PDF y página.
- Etapa actual, componentes, términos y relaciones detectadas.
- Actualización automática cada 2 segundos mientras hay trabajos activos.
- Botón Reindexar PDF sin volver a cargar el archivo.


## v0.10.3 - Procesamiento seguro y PDFs sin duplicados
- Relaciones filtradas y limitadas a evidencia técnica.
- Botón Cancelar proceso con limpieza de relaciones parciales.
- Barra estable: refresca sin ocultar ni desplazar la tabla.
- Almacenamiento por SHA-256: el mismo PDF reutiliza la misma clave del Bucket y no crea copias nuevas tras un deploy.


## v0.10.3 - Catálogo maestro desde listas

- Clasifica páginas como plano, lista de componentes o lista de cables.
- Lee primero las listas/BOM para construir un catálogo maestro.
- Enriquece las apariciones del plano con tipo, modelo, fabricante y descripción.
- Las listas ayudan a indexar, pero siguen quedando detrás de los planos en la búsqueda.
- Muestra la etapa “Leyendo listas de componentes” en la barra de progreso.

## v0.10.5 - Respuesta técnica estructurada

- Ficha técnica del componente antes de la explicación de la IA.
- Indicador de confianza según catálogo/lista y plano.
- Fuentes clicables que abren la página correspondiente y resaltan la referencia.
- Acciones rápidas: Ver en plano y Ver relacionados.
- Mantiene Anthropic/OpenAI, catálogo desde listas e indexación de la v0.10.3.

## v0.10.9 - Catálogo y uso diario

Cambios implementados sobre v0.10.5:

- El filtro Empresa del catálogo se sincroniza después de cargar las empresas.
- Búsqueda normalizada y ordenada por relevancia: referencia exacta, modelo exacto, coincidencia parcial y descripción.
- Las consultas `fc011`, `FC011` y `-FC011` se tratan como la misma referencia.
- Los resultados secundarios mencionados solo en descripciones se excluyen cuando existen coincidencias reales en referencia o modelo.
- Cada tarjeta indica por qué apareció en los resultados.
- Botones Limpiar y Copiar respuesta en el asistente contextual.
- Exportación del catálogo filtrado a Excel, con una fila por componente/página/sector y sin duplicados visuales.
- Versión de API y frontend actualizada a 0.10.9.

Archivos principales modificados:

- `backend/app/routers/component_catalog.py`
- `backend/app/static/app.js`
- `backend/app/static/index.html`
- `backend/app/static/styles.css`
- `backend/app/main.py`
- `backend/requirements.txt`

## v0.10.9 - Corrección del catálogo de componentes

- Corrige la recursión infinita en `componentCatalogParams()`.
- El catálogo vuelve a cargar respetando Empresa, Planta, Sector, Tipo y búsqueda.
- La exportación Excel reutiliza exactamente los mismos filtros visibles.
- Si la API falla, la interfaz muestra el error y deja de indicar carga.

## v0.10.9 - Asistente con contexto de página

- El asistente recuerda la última página abierta en el visor.
- Cuando una referencia se repite en distintos sectores, prioriza la instancia que el técnico está mirando.
- Envía al backend la página, documento y referencia actuales como contexto explícito.
- La fuente correspondiente queda marcada internamente como contexto actual y recibe máxima prioridad.
- Si no hay una página abierta o vista recientemente, conserva el comportamiento de búsqueda general.
