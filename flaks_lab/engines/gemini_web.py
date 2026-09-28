"""Motor 5 · Scraping de Gemini web (gemini.google.com) con tu sesión y ritmo humano."""
from __future__ import annotations

from ..models import Pieza, Uso
from ._navegador import MotorNavegador
from .base import registrar


@registrar
class GeminiWeb(MotorNavegador):
    id = "gemini_web"
    nombre = "Gemini web"
    descripcion = "Automatiza gemini.google.com con tu sesión, con ritmo humano."
    proveedor = "google"
    modelo_costo = "gemini-web"
    orden = 5

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("google", "gemini-web", imagenes=len(pieza.slides))]
