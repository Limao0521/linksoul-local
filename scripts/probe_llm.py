"""Sonda de diagnóstico del pipeline bridge -> llm-server.

Uso (red del compose levantada):
  docker run --rm --network linksoul-local_default \
    -v "${PWD}/scripts/probe_llm.py:/probe.py:ro" \
    -e LLM_BASE_URL=http://llm-server:8080/v1 \
    linksoul-local/bridge:latest python /probe.py
"""
import sys
import time

sys.path.insert(0, "/app")

print("python:", sys.version.split()[0], flush=True)

from bridge.llm import LocalLLM  # noqa: E402
from bridge.persona import load_persona  # noqa: E402

llm = LocalLLM()
print("health:", llm.health(), flush=True)
persona = load_persona()
print("persona chars:", len(persona), flush=True)

# 1) generación completa sin streaming
t0 = time.monotonic()
r = llm.chat(persona, [], "Di solo: OK")
print(f"chat sin streaming ({time.monotonic() - t0:.2f}s):", repr(r), flush=True)

# 2) streaming con métricas
history = []
for user in ("Hola! Quien eres?", "Dime una curiosidad de los robots"):
    t0 = time.monotonic()
    ttft, n = None, 0
    parts = []
    for delta in llm.chat_stream(persona, history, user):
        if ttft is None:
            ttft = time.monotonic() - t0
        n += 1
        parts.append(delta)
    total = time.monotonic() - t0
    reply = "".join(parts).strip()
    history.append({"role": "user", "content": user})
    history.append({"role": "assistant", "content": reply})
    print(
        f"\ntu> {user}\nrobot> {reply}\n"
        f"  TTFT={ttft * 1000:.0f}ms chunks={n} total={total:.2f}s "
        f"gen={n / max(total - (ttft or 0), 1e-6):.1f} tok/s",
        flush=True,
    )

llm.close()
print("\nPROBE OK", flush=True)
