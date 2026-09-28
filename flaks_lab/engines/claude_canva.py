"""Plugin desactivado · Claude + Canva (igual que el motor 4 con texto de Claude)."""
from __future__ import annotations

from ..models import Pieza, Uso
from .gpt_canva import GptCanva
from .base import registrar


@registrar
class ClaudeCanva(GptCanva):
    id = "claude_canva"
    nombre = "Claude + Canva"
    descripcion = "Texto con Claude, CSV para Canva Bulk Create y espera que subas el resultado."
    activo_por_defecto = False
    orden = 6

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("anthropic", "claude-opus-5-5", input_tokens=800, output_tokens=110 * len(pieza.slides))]
