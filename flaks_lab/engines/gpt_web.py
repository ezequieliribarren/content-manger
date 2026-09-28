"""Plugin desactivado · Scraping de ChatGPT web."""
from __future__ import annotations

from ..models import Pieza, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar


@registrar
class GptWeb(Motor):
    id = "gpt_web"
    nombre = "ChatGPT web"
    descripcion = "Automatiza chatgpt.com con tu sesión, con ritmo humano."
    tipo = "navegador"
    usa_referencia = "imagen"
    formatos_nativos = ("4x5",)
    ritmo_humano = True
    activo_por_defecto = False
    orden = 7

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("openai", "chatgpt-web", imagenes=len(pieza.slides))]

    def generar(self, pieza: Pieza, ctx: Contexto):
        raise ErrorConfiguracion("Plugin todavía no implementado: usalo en modo simulado")
