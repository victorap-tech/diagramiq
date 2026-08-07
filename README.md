# DiagramIQ v0.14.6

Correcciones sobre v0.14.5:
- El componente principal del asistente prioriza la aparición física con evidencia técnica (potencia, tensión, corriente, RPM y función) sobre menciones en listas PLC/HMI.
- Evita que un motor como TC-7002-1 quede presentado como sensor por una aparición secundaria.
- Recupera las coordenadas exactas del TAG desde el índice de términos cuando la coincidencia proviene del texto de página, para habilitar el resaltado amarillo.
- "Ver relacionados" conserva Empresa / Planta / Sector al volver a Buscar; no vacía el sector cuando una relación no trae esos IDs.
- Mantiene la normalización de referencias con guion, guion bajo y separadores equivalentes.

Deploy: subir el proyecto completo a Railway como en la versión anterior. No requiere borrar PDFs ni reconstruir el bucket por este cambio de interfaz/consulta.
