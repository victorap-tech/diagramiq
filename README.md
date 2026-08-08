# DiagramIQ v0.15.4

Base: v0.14.8 estable.

## Documentación técnica multilingüe

- Mantiene intacto el flujo estable de planos eléctricos de v0.14.8.
- Agrega tipos: Manual, Datasheet / ficha técnica y Procedimiento técnico.
- Manuales, datasheets y procedimientos se indexan por página y texto, pero no contaminan el catálogo de componentes ni las relaciones eléctricas.
- El asistente detecta preguntas de configuración, protocolos, parámetros, alarmas y puesta en marcha y prioriza documentación técnica.
- Expande términos técnicos español/inglés para mejorar consultas cruzadas.
- Responde en español aunque la fuente esté en inglés.
- Conserva literalmente parámetros, códigos, acrónimos y nomenclatura del fabricante.
- Las respuestas incluyen documento, tipo documental y página en las fuentes.

## Ejemplo

Documento: manual de control de velocidad por protocolo USS en inglés.
Pregunta: `¿Cómo configuro el control de velocidad por USS?`
DiagramIQ prioriza el manual, responde en español y conserva términos como `USS`, `PZD`, `PKW`, `Control Word` y números de parámetro.

## Persistencia

Se conserva PostgreSQL + Bucket y el comportamiento de deploy seguro de la base estable.

## v0.15.2 — Filtro estricto + recuperación de TAG del plano

- Mantiene el filtro estricto Empresa → Planta → Sector: nunca mezcla fichas de otro sector.
- Si un TAG como `Q401` existe en el PDF del sector pero la ficha del catálogo quedó incompleta, lo recupera desde el índice textual persistente (`page_search_terms`).
- La recuperación se hace **dentro del sector seleccionado**, por lo que no vuelve a introducir resultados de otras líneas.
- Usa el contexto y el modelo cercano para clasificar equipos físicos; reconoce `3RV`, `GV2`, `MS116`, `PKZM/PKZ` y textos de protección de motor como guardamotor.
- Conserva las coordenadas del término para poder abrir la página correcta del plano.
- Evita que una respuesta antigua de una petición asíncrona pise el sector actualmente visible.
- Mantiene seguridad/login, documentación multilingüe y todas las funciones previas.

## v0.15.0 — Seguridad de acceso

Esta versión agrega autenticación obligatoria para la interfaz y la API, sin modificar la lógica de búsqueda, resaltado, relaciones ni documentación técnica.

### Variables nuevas en Railway

Configurar antes de usar:

- `DIAGRAMIQ_USER`: usuario de acceso. Si se omite, usa `admin`.
- `DIAGRAMIQ_PASSWORD`: contraseña de acceso **obligatoria**. Elegir una contraseña larga y única.
- `DIAGRAMIQ_AUTH_SECRET`: secreto aleatorio largo para firmar sesiones (recomendado).
- `DIAGRAMIQ_SESSION_HOURS`: duración de sesión en horas (opcional, por defecto 12).
- `DIAGRAMIQ_COOKIE_SECURE`: mantener `true` en Railway. Solo usar `false` para pruebas locales por HTTP.

Ejemplo de nombres (no copiar los valores):

```text
DIAGRAMIQ_USER=admin
DIAGRAMIQ_PASSWORD=<contraseña-larga-y-unica>
DIAGRAMIQ_AUTH_SECRET=<cadena-aleatoria-larga>
```

La aplicación queda cerrada si `DIAGRAMIQ_PASSWORD` no está configurada. `/health`, `/login` y los archivos estáticos son las únicas rutas públicas necesarias. Los endpoints costosos de IA incluyen un límite básico de solicitudes por IP.


## v0.15.4 — Aprendizaje de nomenclatura por sector/documento

- Aprende prefijos locales del plano usando fichas ya confirmadas dentro del mismo sector.
- Ejemplo: en Caldera1, si una referencia `Q...` confirmada es guardamotor, otras `Q...` del mismo sector pueden clasificarse como guardamotor cuando no haya evidencia contradictoria.
- En otro sector el mismo prefijo puede significar otra cosa; las reglas no se comparten entre sectores.
- Incorpora reconocimiento de `W...` como cable cuando el plano aporta evidencia de cable/conductor.
- La evidencia local y los modelos de fabricante siempre tienen prioridad sobre una regla aprendida.
- Si un prefijo tiene usos contradictorios, no se aplica automáticamente salvo que exista una mayoría clara.

## v0.15.4 — Reindexación segura con integridad referencial
- Corrige `ForeignKeyViolation` al reindexar documentos ya procesados.
- La limpieza respeta el orden: conexiones → adjuntos → términos/referencias → páginas.
- La limpieza de PostgreSQL se ejecuta en una sola transacción con rollback ante error.
- Los PNG anteriores se eliminan solamente después de confirmar la limpieza en base de datos.
- Conserva el aprendizaje de nomenclatura por sector/documento de v0.15.3.
