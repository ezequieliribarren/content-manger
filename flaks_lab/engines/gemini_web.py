"""Motor 5 · Scraping de Gemini web con la sesión del usuario."""
from __future__ import annotations

from ..models import Pieza, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar


@registrar
class GeminiWeb(Motor):
    id = "gemini_web"
    nombre = "Gemini web"
    descripcion = "Automatiza gemini.google.com con tu sesión, con ritmo humano."
    tipo = "navegador"
    usa_referencia = "imagen"
    formatos_nativos = ("4x5",)
    ritmo_humano = True
    orden = 5

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("google", "gemini-web", imagenes=len(pieza.slides))]

    def generar(self, pieza: Pieza, ctx: Contexto):
        raise ErrorConfiguracion("Motor 5 todavía no implementado: usalo en modo simulado")
