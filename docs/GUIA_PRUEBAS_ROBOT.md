# Guía de pruebas en robot real — validación de tiempos de respuesta

Objetivo: que cualquier compañero pueda desplegar LinkSoul Local en un AgiBot
X2 / X2 Ultra, **medir la latencia real de conversación** y decidir si la
inferencia local sustituye a la nube con una conversación fluida.

Tiempo estimado: 1-2 h (la mayor parte es esperar credenciales/descargas).
Lectura previa: `README.md` (arquitectura y requisitos).

---

## Criterios de aceptación (lo que validamos)

| Métrica | Objetivo Jetson (X2 Ultra a bordo) | Objetivo LAN GPU | Mínimo aceptable (CPU) |
|---|---|---|---|
| **TTFT** (tiempo hasta el primer token hablado) | < 300 ms | < 200 ms | < 1000 ms |
| **Velocidad de generación** | > 25 tok/s | > 50 tok/s | > 10 tok/s |
| **Turno completo** (respuesta de ~40 palabras) | < 3 s | < 2 s | < 6 s |
| Barge-in (interrumpir al robot hablando) | corta la generación anterior | idem | idem |
| Personalidad | responde como el Character Design de Soul Workshop | idem | idem |

> Regla práctica de fluidez: si el robot empieza a hablar en **menos de ~1 s**
> desde que terminas la frase, la conversación se siente natural.

---

## Fase 0 — Baseline en un PC (sin robot, 15 min)

Sirve para verificar que todo funciona antes de tocar el robot.

```powershell
# Windows (PowerShell) en la raíz del repo:
Copy-Item .env.example .env
.\scripts\download-model.ps1            # ~2.4 GB
docker compose up -d --build
docker run --rm --network linksoul-local_default `
  -v "${PWD}/scripts/probe_llm.py:/probe.py:ro" `
  -e LLM_BASE_URL=http://llm-server:8080/v1 `
  linksoul-local/bridge:latest python /probe.py
```

```bash
# Linux / robot:
cp .env.example .env
./scripts/download-model.sh
docker compose up -d --build
docker run --rm --network linksoul-local_default \
  -v "$PWD/scripts/probe_llm.py:/probe.py:ro" \
  -e LLM_BASE_URL=http://llm-server:8080/v1 \
  linksoul-local/bridge:latest python /probe.py
```

**Anota** la salida (`TTFT=...ms ... gen=... tok/s`): es tu baseline. En CPU de
portátil esperamos ~370 ms TTFT y ~13 tok/s; con GPU debe mejorar 3-5x.

## Fase 1 — Credenciales y SDK (una sola vez por equipo)

1. Cuenta en https://open.agibot.com/cn/console/apps → crear aplicación →
   solicitar capacidad **AgentSDK** → guardar `appId`, `appKey`, `appSecret`
   (⚠️ el secret solo se muestra UNA vez; compartidlo por el canal seguro del
   equipo, **nunca** lo commiteéis — `.env` está en `.gitignore`).
2. Descargar el wheel `linksoul_agentsdk-1.4.0a0-py3-none-any.whl` de
   https://open.agibot.com/docs/linksoul/agentsdk_docs/python/v140/en
   (sección *Distribution downloads*) → copiarlo a `bridge/vendor/` →
   `docker compose build linksoul-bridge`.
3. En https://linksoul.agibot.com → **Agent Center → Agent Templates → Add
   Agent Template** → tipo **SDK Integration Creation** → asociar la app →
   crear el agente (configurar voz/timbre aquí: el robot hablará con esa voz) →
   **Test Connectivity**.
4. **Vincular el agente al robot** (Device Management): relación 1:1, firmware
   del robot ≥ v0.9.0.
5. Copiar el *Character Design* de Soul Workshop a `bridge/persona/persona.md`
   (si quieres comparar contra la personalidad cloud original).
6. Rellenar `.env`: `AGIBOT_APP_ID`, `AGIBOT_APP_KEY`, `AGIBOT_APP_SECRET`,
   `AGIBOT_AGENT_CODE`.

## Fase 2 — Despliegue junto al robot

Elegid UN escenario (recomendado empezar por A):

**A) Servidor LAN (cualquier X2, máx. rendimiento)** — PC con GPU NVIDIA en la
misma red que usa el robot:
```bash
docker compose -f docker-compose.yml -f compose.x86-cuda.yml up -d --build
```

**B) A bordo del X2 Ultra (Jetson Orin NX 16GB, autónomo)** — copiar el repo al
Jetson (p. ej. `scp -r linksoul-local/ <user>@10.0.1.41:~/` con el PC en
`10.0.1.2/24` conectado al puerto SDK del robot):
```bash
sudo nvpmodel -m 0 && sudo jetson_clocks     # clocks máximos (+15-25%)
./scripts/download-model.sh                   # en China: HF_ENDPOINT=https://hf-mirror.com
docker compose -f docker-compose.yml -f compose.jetson.yml up -d --build
```

El bridge se conecta **saliente** al gateway de AgiBot: la máquina donde corra
solo necesita internet + acceso al `llm-server`.

Verificación previa a hablar con el robot:
```bash
docker compose logs -f linksoul-bridge
# ✓ "Esperando al servidor LLM..." → "warmup OK"
# ✓ "autenticación LinkSoul OK"
```

## Fase 3 — Protocolo de prueba en el robot real

Con `docker compose logs -f linksoul-bridge` abierto en un terminal (el bridge
logea `TTFT=xxx ms` y duración por turno), di al robot estas 8 frases y rellena
la tabla:

| # | Frase de prueba | Qué evalúa |
|---|---|---|
| 1 | «Hola, ¿quién eres?» | saludo + identidad de la persona |
| 2 | «¿Qué hora es?» | respuesta corta (TTFT puro) |
| 3 | «Cuéntame algo interesante sobre el espacio» | generación media |
| 4 | Pregunta en chino (p. ej. «你好，你今天怎么样？») | multilingüe |
| 5 | «¿Y eso por qué?» justo después de la 4 | memoria de conversación |
| 6 | Frase larga de ~30 palabras | prefill largo |
| 7 | Interrumpe al robot a media respuesta con «para» | barge-in |
| 8 | 5 preguntas rápidas encadenadas | estabilidad bajo turns seguidos |

### Tabla de resultados (copiad y rellenad)

| # | TTFT (ms) | Turno total (s) | ¿Responde como la persona? (S/N) | Fluidez 1-5 | Notas |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| … | | | | | |

- **TTFT y total**: salen directos de los logs del bridge (`TTFT=312ms`,
  `turno listo event=... en 1.85s`).
- **Fluidez 1-5**: 5 = no notas que piense; 3 = pausa notable pero aceptable;
  1 = inusable.
- Extraed métricas agregadas rápido:
  ```bash
  docker compose logs linksoul-bridge | grep -oE "TTFT=[0-9]+ms" | sort -t= -k2 -n
  ```

### Comparativa contra la nube (opcional pero recomendada)

Repetid las frases 1-6 con el agente **cloud por defecto** de LinkSoul (desvincula
tu agente SDK en Device Management) y anotad TTFT percibido y calidad. Esa delta
es el argumento del proyecto.

### Control térmico (solo escenario B, a bordo)

Durante las pruebas, en otro SSH del Jetson: `sudo tegrastats`. Si la GPU pasa
de ~90 °C o veis throttling, repetid la fase 3 con el escenario A (LAN).

## Fase 4 — Registro de resultados

1. Rellenad la tabla en este archivo (sección abajo) o en un issue del repo.
2. Incluid: hardware (Jetson a bordo / LAN con qué GPU), modelo y cuantización,
   perfil de compose usado, fecha.
3. Commit + push para que quede histórico.

---

## Solución de problemas durante la prueba

| Síntoma | Acción |
|---|---|
| `autenticación LinkSoul FALLÓ` | Credenciales mal copiadas / app sin capacidad AgentSDK aprobada |
| Bridge se conecta pero el robot no le habla | Agente no vinculado al dispositivo, o firmware < v0.9.0, o Test Connectivity fallaba en el portal |
| El robot responde con la voz pero texto genérico | Estás hablando con el agente cloud: verifica la vinculación 1:1 |
| TTFT altísimo solo en el primer turno | Normal (cold start): el warmup debe evitarlo; comprueba `warmup OK` en logs |
| Respuestas larguísimas y lentas | Baja `MAX_TOKENS` a 200 y refuerza "respuestas de 1-2 frases" en persona.md |
| Todo lento a bordo | `sudo jetson_clocks`; si sigue, escenario A (LAN) o `Qwen3-1.7B` |

## Resultados de referencia (ir añadiendo)

| Fecha | Equipo | Hardware | Modelo | TTFT mediano | tok/s | Fluidez |
|---|---|---|---|---|---|---|
| 2026-10-19 | dev (PC, Docker CPU) | CPU laptop, sin GPU | Qwen3-4B Q4_K_M | 372 ms (1º turno) | 13.1 | n/a (sin robot) |
| | | | | | | |
