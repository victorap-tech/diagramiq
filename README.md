# DiagramIQ v0.9.7

Base: v0.9.5 estable.

## Cambio principal: motor de relaciones precalculadas

- Durante la indexación del PDF crea un índice persistente de conexiones.
- Guarda relaciones por referencia cruzada, proximidad y continuidad entre páginas.
- `Seguir circuito` consulta ese índice y no vuelve a analizar el PDF en cada búsqueda.
- Mantiene compatibilidad con documentos anteriores: si aún no tienen índice, usa el método anterior.
- Agrega estado y cantidad de conexiones por documento en la base de datos.
- No cambia el flujo de búsqueda ni agrega demoras a las consultas normales.

Versión visible y API: 0.9.7.


## v0.9.7 — Componente principal

- Prioriza la referencia visual principal del componente sobre tags de cables y continuidades.
- Conserva una aparición principal por página y deja repeticiones como secundarias.
- Envía listados e índices al final de los resultados.
- Amplía el área de enfoque para centrar el símbolo asociado al rótulo.
- La búsqueda sigue consultando únicamente el índice persistente.
