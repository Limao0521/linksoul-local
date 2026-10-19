"""Cliente del servidor LLM local (API compatible OpenAI, streaming SSE).

Optimizado para conversación en tiempo real:
  - Pool de conexiones HTTP keep-alive: cero handshakes TCP por turno.
  - Warmup al arrancar: precarga el modelo y deja el system prompt de la
    personalidad en la cache de prefijos del servidor => TTFT mínimo en cada turno.
  - thinking desactivado por defecto (Qwen3): el robot responde directo, sin
    gastar segundos en razonamiento interno antes del primer token.
  - max_tokens acotado: respuestas conversacionales cortas = percepción de fluidez.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Iterator

import httpx

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://llm-server:8080/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "local")

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "300"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
ENABLE_THINKING = os.getenv("ENABLE_THINKING", "false").strip().lower() in ("1", "true", "yes")
# Pares user/assistant conservados en el historial por robot
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "8"))


class ConversationMemory:
    """Historial acotado por robot (robotCid), con orden estable.

    El orden estable es importante: llama-server reutiliza el KV cache del
    prefijo común entre requests consecutivos (system + historial), lo que
    reduce el time-to-first-token de cada turno.
    """

    def __init__(self, max_turns: int = HISTORY_TURNS) -> None:
        self._histories: dict[str, deque] = {}
        self._max_turns = max_turns

    def history(self, robot_cid: str) -> list[dict]:
        return list(self._histories.get(robot_cid, ()))

    def add(self, robot_cid: str, role: str, content: str) -> None:
        h = self._histories.setdefault(robot_cid, deque(maxlen=self._max_turns * 2))
        h.append({"role": role, "content": content})

    def reset(self, robot_cid: str) -> None:
        self._histories.pop(robot_cid, None)


class LocalLLM:
    def __init__(self, base_url: str = LLM_BASE_URL, api_key: str = LLM_API_KEY) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            # read largo: una generación completa puede tardar; connect corto
            # para fallar rápido si el servidor LLM no está levantado
            timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=600.0),
        )

    # ------------------------------------------------------------------ utils
    def health(self) -> bool:
        try:
            base = str(self._client.base_url).removesuffix("/v1").removesuffix("/")
            return httpx.get(f"{base}/health", timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False

    def wait_ready(self, timeout_s: float = 300.0, poll_s: float = 3.0) -> None:
        """Espera a que el servidor LLM haya cargado el modelo."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.health():
                return
            time.sleep(poll_s)
        raise TimeoutError(f"Servidor LLM no disponible en {LLM_BASE_URL} tras {timeout_s}s")

    def warmup(self, system_prompt: str) -> None:
        """Fuerza la carga del modelo y cachea el prefijo de la personalidad."""
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Hola"},
            ],
            "max_tokens": 1,
            "stream": False,
        }
        if not ENABLE_THINKING:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            t0 = time.monotonic()
            self._client.post("/chat/completions", json=payload).raise_for_status()
            print(f"[llm] warmup OK en {time.monotonic() - t0:.2f}s", flush=True)
        except httpx.HTTPError as exc:
            print(f"[llm] warmup falló (no fatal): {exc}", flush=True)

    # --------------------------------------------------------------- generar
    def chat_stream(
        self,
        system_prompt: str,
        history: list[dict],
        user_text: str,
        max_tokens: int = MAX_TOKENS,
    ) -> Iterator[str]:
        """Genera la respuesta en streaming; rinde deltas de texto.

        Mantiene el prefijo (system + historial) byte-idéntico entre turnos
        para maximizar la reutilización de KV cache del servidor.
        """
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE,
        }
        if not ENABLE_THINKING:
            # Qwen3: saltarse la fase thinking recorta segundos de latencia
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code != 200:
                body = resp.read().decode(errors="replace")[:500]
                raise RuntimeError(f"LLM HTTP {resp.status_code}: {body}")
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta

    def chat(self, system_prompt: str, history: list[dict], user_text: str) -> str:
        """Variante sin streaming (para routers/intenciones internas)."""
        return "".join(self.chat_stream(system_prompt, history, user_text))

    def close(self) -> None:
        self._client.close()
