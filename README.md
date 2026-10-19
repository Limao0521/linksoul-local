# LinkSoul Local — inferencia LLM on-device para AgiBot X2 / X2 Ultra

Sustituye el LLM en la nube de **LinkSoul** (plataforma de personalidades de
AgiBot) por **inferencia 100% local**, conservando la voz, el ASR/TTS y la
vinculación del robot. Objetivo: conversación lo más fluida posible
(time-to-first-token mínimo + streaming).

> 📋 **Para el equipo**: la guía paso a paso de pruebas en el robot real y
> validación de tiempos de respuesta está en
> [`docs/GUIA_PRUEBAS_ROBOT.md`](docs/GUIA_PRUEBAS_ROBOT.md).

## Por qué un "bridge" y no solo cambiar una URL

La investigación (oct-2026) confirmó que LinkSoul es una plataforma cerrada:
**no permite reconfigurar el endpoint de su LLM interno**. Su punto de
integración oficial es el **Agent SDK**: registras tu propio agente en el
portal de LinkSoul y el robot enruta la conversación a TU proceso vía WebSocket,
en lugar de al LLM cloud de AgiBot. Este proyecto implementa ese agente
(`linksoul-bridge`) y lo alimenta con un servidor LLM local (`llm-server`).

```
┌──────────┐  voz/ASR   ┌─────────────────────┐  Agent SDK (WSS)  ┌──────────────────┐
│ Robot X2 │ ─────────► │ Gateway LinkSoul    │ ────────────────► │ linksoul-bridge  │
│ (ASR+TTS)│ ◄───────── │ (nube de AgiBot)    │ ◄──────────────── │ (Python, este    │
└──────────┘  deltas    └─────────────────────┘   texto streaming │  proyecto)       │
     de texto                                                     └────────┬─────────┘
                                                                           │ HTTP/SSE (LAN o localhost)
                                                                  ┌────────▼─────────┐
                                                                  │ llm-server       │
                                                                  │ llama.cpp+Qwen3  │
                                                                  │ (Docker, local)  │
                                                                  └──────────────────┘
```

> Nota de transparencia: el *gateway* WebSocket de LinkSoul sigue siendo de
> AgiBot (los eventos de voz del robot pasan por ahí). Lo que se vuelve local es
> **la inteligencia**: ningún texto de la conversación se envía a un LLM de
> terceros. Para offline total habría que bypassar LinkSoul vía AimDK_X2 con
> ASR/TTS propios (proyecto aparte).

## Componentes

| Servicio | Qué es | Imagen |
|---|---|---|
| `llm-server` | llama-server (llama.cpp) con **Qwen3-4B Q4_K_M**, API compatible OpenAI (`/v1/chat/completions` + SSE) | build local sobre `ghcr.io/ggml-org/llama.cpp:server` (CPU), `:server-cuda12` (x86 GPU) o `dustynv/llama_cpp` (Jetson) |
| `linksoul-bridge` | Agente LinkSoul (SDK oficial) + persona + memoria de conversación + cliente LLM con streaming | build local `python:3.12-slim` + wheel propietario |

## Estructura

```
linksoul-local/
├── docker-compose.yml        # base: llm-server (CPU) + bridge
├── compose.jetson.yml        # override: robot X2 Ultra (Jetson Orin NX 16GB)
├── compose.x86-cuda.yml      # override: servidor LAN con GPU NVIDIA
├── .env.example              # copia a .env y rellena credenciales
├── llm-server/
│   ├── Dockerfile
│   └── entrypoint.sh         # auto-detecta flags de llama.cpp, modo latencia
├── bridge/
│   ├── Dockerfile            # instala wheel del SDK desde vendor/ si existe
│   ├── requirements.txt
│   ├── vendor/README.md      # cómo obtener el SDK propietario
│   ├── persona/persona.md    # ← TU personalidad (copiar de Soul Workshop)
│   └── bridge/
│       ├── agent.py          # agente LinkSoul (on_request → LLM → deltas)
│       ├── llm.py            # cliente OpenAI-compatible + memoria + warmup
│       ├── persona.py        # carga del system prompt
│       └── chat_test.py      # prueba de latencia SIN robot ni credenciales
├── scripts/
│   ├── download-model.ps1    # descarga GGUF (Windows)
│   ├── download-model.sh     # descarga GGUF (Linux/robot)
│   └── probe_llm.py          # sonda diagnóstica TTFT/tok-s
└── models/                   # GGUF (gitignored)
```

## Requisitos

- **Docker** con Compose v2 (en el PC, en el robot o en un servidor LAN).
- **Cuenta AgiBot**: app con capacidad *AgentSDK* en
  https://open.agibot.com/cn/console/apps → obtén `appId`, `appKey`,
  `appSecret` (el secret **solo se muestra una vez**).
- **Agente SDK creado en LinkSoul** (https://linksoul.agibot.com → Agent Center
  → Agent Templates → *Add Agent Template* → tipo **"SDK Integration
  Creation"** → asocia tu app) y **vinculado a tu robot X2** (relación 1:1,
  firmware del robot ≥ v0.9.0, máx. 5 dispositivos por agente).
- **Wheel del SDK** `linksoul_agentsdk-1.4.0a0-py3-none-any.whl` (no está en
  PyPI): descárgalo de la sección "Distribution downloads" en
  https://open.agibot.com/docs/linksoul/agentsdk_docs/python/v140/en y cópialo
  a `bridge/vendor/`.
- Hardware: **X2 Ultra** → puede correr todo a bordo (Jetson Orin NX 16GB).
  **X2 base** → sin cómputo para LLM a bordo (dual RK3588); usa el perfil de
  servidor LAN.

## Quickstart — pruébalo en tu PC (sin robot)

```powershell
cd linksoul-local
Copy-Item .env.example .env          # Linux: cp .env.example .env
.\scripts\download-model.ps1         # Qwen3-4B Q4_K_M (~2.4 GB)
docker compose up -d --build         # llm-server + bridge
```

Verifica la API y la latencia:

```powershell
# Sonda completa (TTFT, tok/s, 2 turnos con persona)
docker run --rm --network linksoul-local_default `
  -v "${PWD}/scripts/probe_llm.py:/probe.py:ro" `
  -e LLM_BASE_URL=http://llm-server:8080/v1 `
  linksoul-local/bridge:latest python /probe.py

# Chat interactivo con métricas por turno
docker compose run --rm linksoul-bridge python -m bridge.chat_test

# API cruda compatible OpenAI
curl http://localhost:8080/v1/chat/completions -H "Content-Type: application/json" `
  -d '{\"model\":\"local\",\"messages\":[{\"role\":\"user\",\"content\":\"Hola\"}],\"stream\":true}'
```

## Conectarlo al robot (de nube a local)

1. **Wheel del SDK** en `bridge/vendor/` → `docker compose build linksoul-bridge`.
2. **Credenciales** en `.env`: `AGIBOT_APP_ID`, `AGIBOT_APP_KEY`,
   `AGIBOT_APP_SECRET`, `AGIBOT_AGENT_CODE` (el código del agente que creaste).
3. **Personalidad**: copia el texto de *Character Design* (Soul Workshop →
   Advanced Settings) a `bridge/persona/persona.md`. El bridge añade
   automáticamente una guía de estilo (respuestas cortas, mismo idioma del
   usuario) optimizada para voz.
4. `docker compose up -d` y vigila:
   ```bash
   docker compose logs -f linksoul-bridge
   # Espera: "autenticación LinkSoul OK" y por turno: "TTFT=xxx ms"
   ```
5. Habla con el robot: su ASR transcribe, tu bridge responde con el LLM local,
   el robot lo verbaliza con su voz de LinkSoul.

### Dónde correr el bridge

El bridge se conecta **saliente** al gateway WSS de AgiBot, así que puede vivir
en cualquier máquina con internet + acceso al `llm-server`:

| Escenario | Despliegue |
|---|---|
| **X2 Ultra autónomo** (sin infraestructura) | Todo a bordo: copia el proyecto al Jetson (p. ej. `scp -r linksoul-local/ <usuario>@10.0.1.41:~/`, puerto SDK del robot) y usa el perfil Jetson (abajo). Antes: `sudo nvpmodel -m 0 && sudo jetson_clocks`. |
| **X2 Ultra + servidor LAN** (recomendado) | `llm-server` con perfil `compose.x86-cuda.yml` en un PC con GPU; `bridge` en el mismo PC. Cero carga térmica para el robot y modelos más grandes. |
| **X2 base** (sin Jetson) | Igual que el anterior — obligatoriamente LAN. |

```bash
# Perfil Jetson (a bordo del X2 Ultra)
docker compose -f docker-compose.yml -f compose.jetson.yml up -d --build

# Perfil servidor LAN con GPU NVIDIA
docker compose -f docker-compose.yml -f compose.x86-cuda.yml up -d --build
```

> En el robot, AimDK ≥ v1.2.0 usa contenedores Podman para desarrollo a bordo;
> si tu unidad corre Podman en vez de Docker, los mismos archivos funcionan con
> `podman-compose` (o ejecuta el bridge/llm-server en la LAN).
> Descarga del modelo en China: `HF_ENDPOINT=https://hf-mirror.com ./scripts/download-model.sh`

## Optimización de latencia (objetivo: conversación fluida)

Medido en este proyecto (Qwen3-4B Q4_K_M, CPU de portátil en Docker — el techo
peor; en Jetson Orin NX con GPU se esperan TTFT ~100-200 ms y 35-40 tok/s):

| Turno | TTFT | Generación |
|---|---|---|
| 1º (tras warmup) | 372 ms | 13.1 tok/s |
| 2º (con historial) | 970 ms | 13.2 tok/s |

Knobs ya aplicados y ajustables en `.env`:

- `ENABLE_THINKING=false` — Qwen3 responde directo, sin fase de razonamiento
  (ahorra 1-3 s por turno). **El mayor win de latencia.**
- `MAX_TOKENS=300` — respuestas conversacionales cortas; para voz, menos es más.
- **Warmup + KV cache de prefijo**: el bridge precalienta al arrancar y mantiene
  el orden system→historial estable, así llama-server reutiliza el KV cache de
  la personalidad entre turnos (`--cache-reuse`, `prompt_tokens_details.cached`
  visible en las respuestas).
- `HISTORY_TURNS=8` — historial acotado; bájalo a 4 para prefill aún más rápido.
- `CTX_SIZE=2048` — contexto justo para charla (ahorra ~750 MB vs 4096).
- Flash Attention + KV cache `q8_0` + offload GPU completo (`NGL=99` en
  perfiles GPU): los activa `llm-server/entrypoint.sh` automáticamente.
- **Decodificación especulativa** (opcional, +25-60 % tok/s):
  ```bash
  ./scripts/download-model.sh 0.6B Q4_K_M
  # .env → DRAFT_MODEL=/models/Qwen3-0.6B-Q4_K_M.gguf
  ```
- En Jetson: `sudo jetson_clocks` (+15-25 %) y vigila `tegrastats` (throttle a 99 °C).
- ¿Más velocidad aún? `Qwen3-1.7B` (~70-80 tok/s en Orin) a costa de riqueza de
  personalidad. ¿Más calidad? `Qwen3-8B` Q4_K_M cabe en el Orin NX 16 GB (~20 tok/s).

## Plan B: el sample oficial apuntando al servidor local

Si el bridge encontrara derivas de API con tu versión del SDK, la alternativa de
máxima fidelidad es usar el ejemplo oficial de AgiBot y apuntar su LLM a este
`llm-server`:

```bash
git clone https://github.com/AgibotTech/agibot_agentsdk_sample_code
cd agibot_agentsdk_sample_code
pip install -r requirements.txt ./ruta/al/linksoul_agentsdk-1.4.0a0-py3-none-any.whl
# config.json → reply_routes.general_chat.llm:
#   "base_url": "http://<host-del-llm-server>:8080/v1",
#   "model": "local", "api_key_env": "LOCAL_LLM_API_KEY" (valor: "not-needed")
export AGIBOT_APP_ID=... AGIBOT_APP_KEY=... AGIBOT_APP_SECRET=... AGIBOT_AGENT_CODE=...
python main.py
```

## Limitaciones conocidas

- El gateway WSS de LinkSoul es de AgiBot (ver nota arriba): se necesita
  conectividad a `open.agibot.com` aunque el LLM sea local.
- El cálculo exacto de la firma HMAC-SHA256 no es público → se usa el SDK
  oficial (que la calcula internamente). No reimplementamos el protocolo.
- Callbacks `*_2_TTS` (el bridge tendría que generar el audio TTS, p. ej. con
  Piper) no implementados; usa `ASR_2_LLM` (recomendado) o `ASR_VIDEO_2_VLM`.
- La relación agente↔robot es 1:1; un agente sirve máx. 5 dispositivos.
- El SDK wheel requiere cuenta en el portal abierto de AgiBot.

## Troubleshooting

| Síntoma | Causa / solución |
|---|---|
| `linksoul-bridge` sale con código 2 | Falta el wheel en `bridge/vendor/` o faltan `AGIBOT_*` en `.env` (mira `docker compose logs linksoul-bridge`) |
| `llm-server` en bucle de reinicio | Falta el modelo: `scripts/download-model.*`; o `MODEL_PATH` mal puesto |
| `autenticación LinkSoul FALLÓ` | Credenciales mal copiadas, o la app no tiene capacidad *AgentSDK* aprobada |
| Robot no responde al agente | Agente no vinculado al dispositivo en Agent Center, firmware < v0.9.0, o "Test Connectivity" fallando en el portal |
| Respuestas lentas en tu PC | Normal sin GPU (13 tok/s CPU); usa `compose.x86-cuda.yml` o despliega en el Jetson |
| Puerto 8080 ocupado | Cambia `LLM_PORT` en `.env` |
| Descarga de modelo falla en China | `HF_ENDPOINT=https://hf-mirror.com` |

## Referencias

- Manual LinkSoul: https://open.agibot.com/docs/linksoul/manual
- Agent SDK Python v1.4.0: https://open.agibot.com/docs/linksoul/agentsdk_docs/python/v140/en
- Sample code oficial: https://github.com/AgibotTech/agibot_agentsdk_sample_code
- AimDK X2 (SDK del robot): https://x2-aimdk.agibot.com
- llama.cpp: https://github.com/ggml-org/llama.cpp · Modelo: https://huggingface.co/Qwen/Qwen3-4B-GGUF
