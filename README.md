# DiagramIQ v0.14.7

Correcciones sobre v0.14.5:
- El componente principal del asistente prioriza la aparición física con evidencia técnica (potencia, tensión, corriente, RPM y función) sobre menciones en listas PLC/HMI.
- Evita que un motor como TC-7002-1 quede presentado como sensor por una aparición secundaria.
- Recupera las coordenadas exactas del TAG desde el índice de términos cuando la coincidencia proviene del texto de página, para habilitar el resaltado amarillo.
- "Ver relacionados" conserva Empresa / Planta / Sector al volver a Buscar; no vacía el sector cuando una relación no trae esos IDs.
- Mantiene la normalización de referencias con guion, guion bajo y separadores equivalentes.

Deploy: subir el proyecto completo a Railway como en la versión anterior. No requiere borrar PDFs ni reconstruir el bucket por este cambio de interfaz/consulta.


## v0.14.7
- Relacionados de motor prioriza arrancador suave, variador, guardamotor, contactor y protección térmica.
- Filtra potenciales y referencias genéricas (N, PE, L1, bornes sueltos).
- Reconoce Siemens 3RW como arrancador suave.
- El fallback de búsqueda recupera coordenadas exactas del TAG para el resaltado amarillo también en modo específico.
- Al abrir un relacionado con ubicación conocida, navega directo al plano sin perder el sector.
