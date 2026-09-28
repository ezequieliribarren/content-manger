"""Motor 1 · GPT API + plantillas HTML."""
from __future__ import annotations

from ..models import Pieza, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar


@registrar
class GptHtml(Motor):
    id = "gpt_html"
    nombre = "GPT API + HTML"
    descripcion = "Texto con la API de OpenAI y plantilla HTML de marca renderizada a PNG con Playwright."
    tipo = "api"
    usa_referencia = "estructura"
    formatos_nativos = ("4x5", "9x16", "1x1", "pdf")
    orden = 1

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("openai", "gpt-5.4-mini", input_tokens=900 + 60 * len(pieza.slides),
                    output_tokens=120 * len(pieza.slides))]

    def generar(self, pieza: Pieza, ctx: Contexto):
        raise ErrorConfiguracion("Motor 1 todavía no implementado: usalo en modo simulado")
