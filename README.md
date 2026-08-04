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
