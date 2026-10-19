# Imagen del servidor LLM local (API compatible OpenAI: /v1/chat/completions + streaming SSE)
#
# Base por defecto: llama.cpp server CPU (x86/arm64) para desarrollo.
# Overrides de compose cambian BASE_IMAGE:
#   - Jetson (robot):   dustynv/llama_cpp:r36.4.0        (ARM64 + CUDA, ajusta tag a tu L4T/JetPack)
#   - x86 con GPU:      ghcr.io/ggml-org/llama.cpp:server-cuda12
ARG BASE_IMAGE=ghcr.io/ggml-org/llama.cpp:server
FROM ${BASE_IMAGE}

# Asegurar curl para el healthcheck (falla silenciosamente en bases no-Debian que ya lo traen)
RUN (command -v curl >/dev/null 2>&1) \
    || (apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*) \
    || true

COPY entrypoint.sh /entrypoint.sh
# Tolerancia a CRLF (por si el build context viene de un checkout en Windows)
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# El wrapper detecta los flags soportados por el binario (varían entre versiones de llama.cpp)
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]

EXPOSE 8080
