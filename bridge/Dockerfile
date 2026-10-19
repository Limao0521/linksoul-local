# Bridge: conecta LinkSoul (WebSocket Agent SDK) con el servidor LLM local.
#
# ANTES DE COMPILAR: descarga el SDK propietario de AgiBot y coloca el wheel en
# bridge/vendor/ (ver bridge/vendor/README.md). Sin el wheel, la imagen compila
# igualmente pero solo funciona el modo de prueba local (chat_test).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

# SDK oficial (no está en PyPI): se instala desde vendor/ si está presente
COPY vendor/ /tmp/vendor/
RUN whl=$(find /tmp/vendor -maxdepth 1 \( -name 'linksoul_agentsdk*.whl' -o -name 'linksoul_agentsdk*.tar.gz' \) 2>/dev/null | head -1); \
    if [ -n "$whl" ]; then \
        pip install "$whl" && echo "[build] SDK LinkSoul instalado: $whl"; \
    else \
        echo "[build] AVISO: linksoul_agentsdk no encontrado en vendor/. El bridge no podrá conectarse a LinkSoul (solo modo chat_test)."; \
    fi; \
    rm -rf /tmp/vendor

COPY bridge/ ./bridge/
COPY persona/ ./persona/

# Por defecto arranca el agente LinkSoul; override en compose para chat_test
CMD ["python", "-m", "bridge.agent"]
