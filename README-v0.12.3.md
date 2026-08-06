# DiagramIQ v0.12.3

Corrección principal: la Biblioteca y Buscar/IA usan la misma evidencia indexada.

- Si una referencia no existe todavía en `component_references`, la Biblioteca busca la referencia exacta en las páginas ya indexadas.
- Solo crea una ficha derivada cuando detecta un equipo físico con evidencia técnica suficiente.
- Motores como `RDL-6502-1` se incorporan con tipo, datos eléctricos y página del plano, aunque no tengan fabricante o modelo comercial.
- Se evita crear fichas para potenciales, colores, canales PLC y textos genéricos.
- La ficha derivada queda persistida para futuras consultas y para asociar manuales/datasheets.
