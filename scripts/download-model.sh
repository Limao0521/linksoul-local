#!/usr/bin/env bash
# Descarga modelos GGUF de Qwen3 (oficiales en HuggingFace) a ./models/
#
# Uso (desde el robot o servidor Linux):
#   ./scripts/download-model.sh              # Qwen3-4B Q4_K_M (recomendado, ~2.5GB)
#   ./scripts/download-model.sh 8B Q4_K_M    # Máxima calidad en Orin NX 16GB
#   ./scripts/download-model.sh 0.6B Q4_K_M  # Draft p/ decodificación especulativa
#   HF_ENDPOINT=https://hf-mirror.com ./scripts/download-model.sh   # Espejo (China)
set -euo pipefail

SIZE="${1:-4B}"
QUANT="${2:-Q4_K_M}"
ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/models"
mkdir -p "$DIR"

FILE="Qwen3-${SIZE}-${QUANT}.gguf"
URL="${ENDPOINT%/}/Qwen/Qwen3-${SIZE}-GGUF/resolve/main/${FILE}"
DEST="$DIR/$FILE"

if [ -f "$DEST" ]; then
    echo "Ya existe: $DEST (bórralo para re-descargar)"
    exit 0
fi

echo "Descargando $FILE"
echo "  URL:  $URL"
echo "  Dest: $DEST"

if command -v curl >/dev/null 2>&1; then
    curl -L --fail --retry 3 --retry-delay 2 -C - --progress-bar -o "$DEST" "$URL"
elif command -v wget >/dev/null 2>&1; then
    wget -c -O "$DEST" "$URL"
else
    echo "ERROR: necesitas curl o wget" >&2
    exit 1
fi

ls -lh "$DEST"
echo "OK. Ajusta MODEL_PATH=/models/$FILE en tu .env si no es el modelo por defecto."
