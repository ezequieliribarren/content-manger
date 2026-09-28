"""Motor 2 · Claude API + plantillas HTML."""
from __future__ import annotations

from ..models import Pieza, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar


@registrar
class ClaudeHtml(Motor):
    id = "claude_html"
    nombre = "Claude API + HTML"
    descripcion = "Texto con la API de Anthropic y la misma plantilla HTML de marca."
    tipo = "api"
    usa_referencia = "estructura"
    formatos_nativos = ("4x5", "9x16", "1x1", "pdf")
    orden = 2

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("anthropic", "claude-opus-5-5", input_tokens=1000 + 60 * len(pieza.slides),
                    output_tokens=140 * len(pieza.slides))]

    def generar(self, pieza: Pieza, ctx: Contexto):
        raise ErrorConfiguracion("Motor 2 todavía no implementado: usalo en modo simulado")
