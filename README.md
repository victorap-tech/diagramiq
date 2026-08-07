# DiagramIQ v0.14.5 — Búsqueda y clasificación corregidas

Esta versión parte de v0.14.3 y mantiene el modo de deploy seguro.

## Correcciones principales

- La búsqueda específica ya no depende únicamente de que una referencia haya sido clasificada como componente. Si el TAG existe en el texto persistido de una página, se devuelve como coincidencia sin abrir el PDF.
- Los TAG con `-`, `_`, `.`, `/` o sin separador se consideran equivalentes (por ejemplo `TC-7002-1`, `TC_7002_1` y `TC70021`).
- La indexación reconoce TAG industriales genéricos como `TC-7002-1` y `RT-6502-1`, además de los prefijos IEC conocidos.
- La Biblioteca de Componentes prioriza evidencia física de la página. Datos como kW/CV, corriente, RPM, U1/V1/W1 y palabras como motor, cinta, transportador o redler pesan más que un modelo de PLC cercano.
- Se evita que un modelo Siemens `6ES7...` de otra zona de la página convierta un motor real en «módulo PLC».
- El asistente contextual usa las mismas variantes de TAG que la búsqueda.
- Se conserva PostgreSQL, Bucket y el comportamiento de deploy seguro de v0.14.3.

## Caso validado

`TC-7002-1` puede localizarse aunque una versión anterior no lo haya creado correctamente como `ComponentReference`. Si la página aporta evidencia de motor, la ficha se consolida como **motor** y se prioriza esa página física sobre referencias cruzadas.

## v0.14.5
- Prioriza páginas con evidencia física del equipo (potencia, tensión, corriente, RPM, U1/V1/W1 y función mecánica) sobre páginas de PLC/HMI o referencias cruzadas.
- La Biblioteca consolida el TAG por la aparición física más confiable y evita heredar modelos 6ES7 de otro equipo de la misma página cuando el TAG corresponde a un motor.
- El visor usa las coordenadas exactas del TAG para el resaltado amarillo y mantiene una zona ampliada separada para el enfoque del equipo.
- Resaltado amarillo reforzado con z-index para que siempre quede visible sobre la imagen.
