# DiagramIQ v0.9.0

Incluye:

- Búsqueda por foto del TAG de cable.
- Reconocimiento por foto de interruptores, guardamotores, contactores, relés, fusibles, variadores, arrancadores suaves, PLC, módulos de E/S, fuentes, sensores, borneras y motores.
- Extracción de tipo, referencia, marca, modelo y texto visible.
- Búsqueda automática del dato reconocido dentro de los planos seleccionados.
- Número de versión y caché actualizados a 0.9.0.

## Railway

Configurar en Variables:

- `OPENAI_API_KEY`: clave de la API.
- `OPENAI_VISION_MODEL`: opcional; por defecto `gpt-4.1-mini`.

La clave se usa únicamente en el backend.


## v0.9.0 – DiagramIQ Vision
Modo automático tipo Lens mediante `POST /vision/analyze`: detecta TAG de cable, componente industrial o texto visible y prepara la búsqueda dentro de los planos.


## v0.9.2
- Relaciones preliminares entre componentes de una misma página.
- Detección por referencias cruzadas y proximidad gráfica.
- Botón “Ver relaciones” en el catálogo.
- Indicador de confianza y acceso a búsqueda en planos.
