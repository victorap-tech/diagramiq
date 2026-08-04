# DiagramIQ Vision v0.9.8

DiagramIQ puede usar OpenAI o Anthropic/Claude para las tres funciones visuales:

- Vision automático (`/vision/analyze`)
- Foto del TAG de cable (`/cable-tags/recognize`)
- Identificación de componentes (`/components/recognize`)

## Usar Anthropic

Configure en Railway:

```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_VISION_MODEL=claude-sonnet-5
```

## Usar OpenAI

```env
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_VISION_MODEL=gpt-4.1-mini
```

`AI_PROVIDER` acepta únicamente `openai` o `anthropic`. No hace falta cargar ambas claves.
