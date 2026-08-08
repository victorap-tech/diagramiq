# DiagramIQ v0.14.9

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

## v0.15.1 — Filtro estricto por sector

- Componentes respeta estrictamente Empresa → Planta → Sector también durante búsquedas por referencia/modelo.
- Evita que una respuesta antigua de una petición asíncrona pise el sector actualmente visible.
- Las consultas tipo Q401/TC-7002-1 ya no devuelven fichas cuya única coincidencia sea una mención secundaria en el texto.
- Mantiene las funciones de seguridad/login de v0.15.0.

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
