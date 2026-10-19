"""Agente LinkSoul: puente entre el robot AgiBot y el servidor LLM local.

Flujo:
  Robot X2 --(voz/ASR)--> Gateway LinkSoul (WSS) --(Agent SDK)--> ESTE bridge
  bridge --(HTTP/SSE)--> llm-server local (Qwen3) --(deltas de texto)--> robot (TTS)

El bridge reemplaza el LLM en la nube de AgiBot por inferencia 100% local,
conservando el pipeline de voz (ASR/TTS) y la vinculación del robot en LinkSoul.

Requiere el wheel propietario `linksoul_agentsdk` en bridge/vendor/ (no está en
PyPI; ver bridge/vendor/README.md). Las firmas del SDK usadas aquí siguen el
repositorio oficial de ejemplo AgibotTech/agibot_agentsdk_sample_code; donde el
SDK pueda variar entre versiones (nombres de métodos de registro, flags), el
código resuelve por inspección en tiempo de arranque.
"""
from __future__ import annotations

import logging
import os
import re
import signal
import sys
import threading
import time
import uuid

from .llm import ConversationMemory, LocalLLM
from .persona import load_persona

log = logging.getLogger("linksoul.bridge")

SDK_MISSING_MSG = """\
[bridge] ERROR: el paquete `linksoul_agentsdk` no está instalado en la imagen.
No se publica en PyPI: descárgalo desde
  https://open.agibot.com/docs/linksoul/agentsdk_docs/python/v140/en
(sección "Distribution downloads" / 开发包下载), copia el .whl en bridge/vendor/
y reconstruye:  docker compose build linksoul-bridge

Mientras tanto puedes validar el pipeline LLM sin robot con:
  docker compose run --rm linksoul-bridge python -m bridge.chat_test
"""

try:
    from linksoul_agentsdk import AgentAuthCallback, AgentSdk
    import linksoul_agentsdk.passive as passive

    try:
        from linksoul_agentsdk import IdGenerator
    except ImportError:  # versión sin IdGenerator: usamos uuid
        IdGenerator = None
except ImportError:
    sys.stderr.write(SDK_MISSING_MSG)
    raise SystemExit(2)

# LINKSOUL_CALLBACK_TYPE -> (clase en linksoul_agentsdk.passive, familia de
# métodos de respuesta). ASR_2_LLM es el recomendado: el robot hace ASR y TTS,
# el bridge solo aporta el texto del LLM local.
CALLBACK_CLASSES = {
    "ASR_2_LLM": ("Asr2LlmCallback", "llm"),
    "AUDIO_2_LLM": ("Audio2LlmCallback", "llm"),
    "ASR_2_TTS": ("Asr2TtsCallback", "llm"),
    "AUDIO_2_TTS": ("Audio2TtsCallback", "llm"),
    "ASR_VIDEO_2_VLM": ("AsrVideo2VlmCallback", "vlm"),
    "asrVideo2Vlm": ("AsrVideo2VlmCallback", "vlm"),
}

# Palabras para cortar la conversación en curso (barge-in explícito)
STOP_WORDS = {
    "stop", "para", "parar", "cállate", "callate", "silencio",
    "闭嘴", "停下", "别说了", "别讲了",
}

REQUEST_FIELDS = ("agent_id", "event_id", "flag", "text", "buf", "param", "response")


# --------------------------------------------------------------------- helpers
def _new_item_id() -> str:
    if IdGenerator is not None:
        try:
            return IdGenerator.generate_item_id()
        except Exception:  # noqa: BLE001
            pass
    return uuid.uuid4().hex


def _call_first(obj, names, *args) -> bool:
    """Llama al primer método existente de `names`; tolera firmas distintas."""
    for name in names:
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                fn(*args)
                return True
            except TypeError:
                continue
    return False


def _send_delta(response, kind, event_id, item_id, text):
    _call_first(response, [f"on_{kind}_item_delta", "on_llm_item_delta", "on_vlm_item_delta"],
                event_id, item_id, text)


def _send_item_done(response, kind, event_id, item_id):
    _call_first(response, [f"on_{kind}_item_done", "on_llm_item_done", "on_vlm_item_done"],
                event_id, item_id)


def _send_done(response, kind, event_id):
    _call_first(response, [f"on_{kind}_done", "on_llm_done", "on_vlm_done"], event_id)


def _send_interrupt(response, event_id):
    _call_first(response, ["on_interrupt"], event_id, "chat", None)


def _parse_request(args, kwargs):
    """Acepta on_request posicional (firma del sample oficial) o por keywords."""
    vals = {}
    for i, name in enumerate(REQUEST_FIELDS):
        if name in kwargs:
            vals[name] = kwargs[name]
        elif i < len(args):
            vals[name] = args[i]
    return (vals.get(n) for n in REQUEST_FIELDS)


def _camel_to_snake(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def _find_register_method(sdk, cb_type: str, cls_name: str):
    """Resuelve el método de registro del callback (varía según versión SDK).

    Confirmado en el sample oficial: sdk.register_asr_video2_vlm(cb).
    Para el resto probamos el patrón register_<snake(nombre-clase-sin-Callback)>
    y, si existe, el API genérica register_passive_callback(type, cb).
    """
    stem = cls_name.removesuffix("Callback")
    candidates = [
        f"register_{_camel_to_snake(stem)}",
        f"register_{stem.lower()}",
        f"register_{cb_type.lower()}",
    ]
    for name in candidates:
        fn = getattr(sdk, name, None)
        if callable(fn):
            return ("direct", fn)
    generic = getattr(sdk, "register_passive_callback", None)
    if callable(generic):
        return ("generic", generic)
    regs = [n for n in dir(sdk) if n.startswith("register") and n != "register_auth"]
    if len(regs) == 1:  # solo hay uno: no hay ambigüedad
        return ("direct", getattr(sdk, regs[0]))
    log.error("No encuentro cómo registrar %s. Métodos disponibles: %s", cls_name, regs)
    raise SystemExit(2)


# ------------------------------------------------------------ callback bridge
def build_callback_class(base_cls, kind: str):
    class BridgeCallback(base_cls):  # type: ignore[misc,valid-type]
        def __init__(self, sdk, llm: LocalLLM, persona: str, memory: ConversationMemory,
                     idle_timeout: float = 300.0):
            # Las bases del sample reciben el sdk; otras no reciben nada
            for attempt in ((sdk,), ()):
                try:
                    base_cls.__init__(self, *attempt)
                    break
                except TypeError:
                    continue
            self._llm = llm
            self._persona = persona
            self._memory = memory
            self._idle_timeout = idle_timeout
            self._lock = threading.Lock()
            self._stop = threading.Event()
            self._last_activity: dict[str, float] = {}

        # -- API del SDK ------------------------------------------------------
        def on_request(self, *args, **kwargs):
            agent_id, event_id, flag, text, buf, param, response = _parse_request(args, kwargs)
            if response is None or not event_id:
                log.warning("on_request ignorado (sin response/event_id): args=%r", (args, kwargs))
                return
            # flag 3 = ASR final (sample oficial); en callbacks de texto puede
            # venir None/0: procesamos igualmente si hay texto
            if flag is not None and flag not in (2, 3):
                return
            if not text or not text.strip():
                return
            text = text.strip()

            session = agent_id or "robot"

            # Barge-in explícito: palabra de parada -> interrumpir y limpiar
            if text.lower() in STOP_WORDS:
                log.info("stop word recibida, interrumpiendo event=%s", event_id)
                with self._lock:
                    self._stop.set()
                _send_interrupt(response, event_id)
                _send_done(response, kind, event_id)
                self._memory.reset(session)
                return

            # Barge-in implícito: nueva utterance -> cancelar generación anterior
            with self._lock:
                self._stop.set()
                stop = self._stop = threading.Event()

            # Sesión por robot con expiración por inactividad
            now = time.time()
            if now - self._last_activity.get(session, 0.0) > self._idle_timeout:
                self._memory.reset(session)
            self._last_activity[session] = now

            item_id = _new_item_id()
            log.info("turno event=%s flag=%s text=%.80r", event_id, flag, text)

            t0 = time.monotonic()
            ttft = None
            parts: list[str] = []
            error_reply = os.getenv("ERROR_REPLY", "Lo siento, ahora mismo no puedo responderte.")
            try:
                for delta in self._llm.chat_stream(self._persona, self._memory.history(session), text):
                    if stop.is_set():
                        log.info("generación cancelada (barge-in) event=%s", event_id)
                        break
                    if ttft is None:
                        ttft = time.monotonic() - t0
                        log.info("TTFT=%.0fms event=%s", ttft * 1000, event_id)
                    parts.append(delta)
                    _send_delta(response, kind, event_id, item_id, delta)

                reply = "".join(parts).strip()
                if not reply:
                    reply = error_reply
                    _send_delta(response, kind, event_id, item_id, reply)
                _send_item_done(response, kind, event_id, item_id)
                _send_done(response, kind, event_id)

                if reply != error_reply:
                    self._memory.add(session, "user", text)
                    self._memory.add(session, "assistant", reply)
                total = time.monotonic() - t0
                log.info("turno listo event=%s en %.2fs (%d chars)", event_id, total, len(reply))
            except Exception as exc:  # noqa: BLE001
                log.exception("error generando respuesta event=%s", event_id)
                if not parts:
                    _send_delta(response, kind, event_id, item_id, error_reply)
                _send_item_done(response, kind, event_id, item_id)
                _send_done(response, kind, event_id)
                _call_first(response, ["on_error"], event_id, 500, str(exc)[:200])

        def on_state(self, *args, **kwargs):
            """robot_pose / tts_status / robot_form: solo logging ligero."""
            try:
                name = kwargs.get("state_name") or (args[2] if len(args) > 2 else None)
                value = kwargs.get("state_value") or (args[3] if len(args) > 3 else None)
                log.debug("state %s=%s", name, value)
            except Exception:  # noqa: BLE001
                pass

    return BridgeCallback


# ------------------------------------------------------------------------ main
def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    missing = [k for k in ("AGIBOT_APP_ID", "AGIBOT_APP_KEY", "AGIBOT_APP_SECRET")
               if not os.getenv(k)]
    if missing:
        log.error("Faltan credenciales en .env: %s", ", ".join(missing))
        log.error("Para probar SOLO el LLM local sin robot: "
                  "docker compose run --rm linksoul-bridge python -m bridge.chat_test")
        return 2

    persona = load_persona()
    llm = LocalLLM()

    log.info("Esperando al servidor LLM en %s ...", os.getenv("LLM_BASE_URL"))
    llm.wait_ready(timeout_s=float(os.getenv("LLM_WAIT_TIMEOUT", "300")))
    llm.warmup(persona)  # deja la personalidad en la KV cache: TTFT mínimo

    cb_type = os.getenv("LINKSOUL_CALLBACK_TYPE", "ASR_2_LLM")
    cls_name, kind = CALLBACK_CLASSES.get(cb_type, (None, None))
    base_cls = getattr(passive, cls_name, None) if cls_name else None
    if base_cls is None:
        # intento directo por nombre de clase o de enum
        base_cls = getattr(passive, cb_type, None)
        if base_cls is None:
            avail = [n for n in dir(passive) if n.endswith("Callback")]
            log.error("LINKSOUL_CALLBACK_TYPE=%r no resuelve a ninguna clase. Disponibles: %s",
                      cb_type, avail)
            return 2
        kind = "vlm" if "Vlm" in base_cls.__name__ else "llm"
        cls_name = base_cls.__name__

    sdk = AgentSdk.create(
        url=os.getenv("LINKSOUL_WS_URL",
                      "wss://open.agibot.com/api/V1/open-portal/app/wss/agent-sdk"),
        app_id=os.environ["AGIBOT_APP_ID"],
        app_key=os.environ["AGIBOT_APP_KEY"],
        app_secret=os.environ["AGIBOT_APP_SECRET"],
    )

    class _Auth(AgentAuthCallback):
        def on_auth_state(self, app_id, code, msg=None):  # firma del sample oficial
            if code == 0:
                log.info("autenticación LinkSoul OK (app_id=%s)", app_id)
            else:
                log.error("autenticación LinkSoul FALLÓ code=%s msg=%s", code, msg)

    try:
        sdk.register_auth(_Auth())
    except Exception:  # noqa: BLE001
        log.warning("register_auth no disponible en esta versión del SDK; continúo")

    memory = ConversationMemory()
    cb_cls = build_callback_class(base_cls, kind)
    cb = cb_cls(sdk, llm, persona, memory,
                idle_timeout=float(os.getenv("IDLE_TIMEOUT", "300")))

    mode, register = _find_register_method(sdk, cb_type, cls_name)
    if mode == "direct":
        register(cb)
    else:
        register(cb_type, cb)  # register_passive_callback(callback_type, callback)

    log.info("bridge listo: callback=%s respuestas=%s agent_code=%s",
             cls_name, kind, os.getenv("AGIBOT_AGENT_CODE") or "(sin definir)")

    sdk.initialize()

    stop = threading.Event()

    def _shutdown(signum, _frame):
        log.info("señal %s recibida, cerrando", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        while not stop.is_set():
            stop.wait(3)
    finally:
        try:
            sdk.release()
        except Exception:  # noqa: BLE001
            pass
        llm.close()
        log.info("bridge detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
