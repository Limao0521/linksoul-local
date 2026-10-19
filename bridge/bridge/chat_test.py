"""Prueba local del pipeline de conversación SIN robot ni credenciales.

Mide las métricas que deciden la fluidez percibida:
  - TTFT (time-to-first-token): objetivo < 300ms en Jetson, < 1s en CPU
  - tok/s de generación: objetivo > 25 tok/s en Jetson

Uso desde el PC (con el contenedor llm-server levantado):
    $env:LLM_BASE_URL="http://localhost:8080/v1"; python -m bridge.chat_test
Uso dentro de Docker:
    docker compose run --rm -e LLM_BASE_URL=http://llm-server:8080/v1 linksoul-bridge python -m bridge.chat_test
"""
from __future__ import annotations

import sys
import time

from .llm import LLM_BASE_URL, ConversationMemory, LocalLLM
from .persona import load_persona


def main() -> int:
    persona = load_persona()
    llm = LocalLLM()

    print(f"[test] Servidor LLM: {LLM_BASE_URL}")
    print("[test] Esperando a que el modelo esté cargado...")
    llm.wait_ready(timeout_s=300)
    print("[test] Precalentando (system prompt en KV cache)...")
    llm.warmup(persona)

    memory = ConversationMemory()
    robot = "chat-test"

    print("\n=== Chat de prueba (escribe 'salir' para terminar) ===")
    print("    Cada turno muestra TTFT y velocidad de generación.\n")

    while True:
        try:
            user = input("tú> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user.lower() in ("salir", "exit", "quit"):
            break

        t0 = time.monotonic()
        ttft = None
        tokens = 0
        print("robot> ", end="", flush=True)
        reply_parts: list[str] = []
        try:
            for delta in llm.chat_stream(persona, memory.history(robot), user):
                if ttft is None:
                    ttft = time.monotonic() - t0
                tokens += 1  # aprox: 1 chunk SSE ~ 1 token con llama.cpp
                reply_parts.append(delta)
                print(delta, end="", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"\n[test] ERROR: {exc}")
            continue
        total = time.monotonic() - t0
        reply = "".join(reply_parts).strip()
        if reply:
            memory.add(robot, "user", user)
            memory.add(robot, "assistant", reply)
        gen_time = max(total - (ttft or 0), 1e-6)
        print(
            f"\n  ··· TTFT {ttft * 1000:.0f} ms | {tokens / gen_time:.1f} tok/s "
            f"| {tokens} toks | total {total:.2f}s"
        )

    llm.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
