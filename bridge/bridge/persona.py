"""Carga de la personalidad (system prompt).

Fuente de verdad: bridge/persona/persona.md — copia ahí el "Character Design"
que configuraste en LinkSoul Soul Workshop para que el robot mantenga la misma
personalidad, pero con inferencia 100% local.
"""
from __future__ import annotations

import os

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "persona", "persona.md")

# Guía de estilo añadida SIEMPRE al final del prompt de personalidad:
# respuestas cortas y habladas = menor latencia percibida y mejor TTS.
_STYLE_SUFFIX = """

## Formato de respuesta (importante)
- Responde SIEMPRE en el mismo idioma en que te hablen.
- Respuestas conversacionales cortas: 1-3 frases por turno (las respuestas largas sueltan robóticas en voz alta y añaden latencia).
- Tono natural y hablado, sin listas, sin markdown, sin emojis.
- Si no sabes algo, dilo con naturalidad y cambia de tema.
"""


def load_persona(path: str | None = None) -> str:
    path = path or os.getenv("PERSONA_FILE", _DEFAULT_PATH)
    with open(path, "r", encoding="utf-8") as f:
        persona = f.read().strip()
    if not persona:
        raise ValueError(f"Persona vacía en {path}")
    return persona + _STYLE_SUFFIX
