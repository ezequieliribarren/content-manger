"""Scraping de ChatGPT web (chatgpt.com) con tu sesión y ritmo humano."""
from __future__ import annotations

from ..models import Pieza, Uso
from ._navegador import MotorNavegador
from .base import registrar


@registrar
class GptWeb(MotorNavegador):
    id = "gpt_web"
    nombre = "ChatGPT web"
    descripcion = "Automatiza chatgpt.com con tu sesión, con ritmo humano."
    proveedor = "openai"
    modelo_costo = "chatgpt-web"
    orden = 7

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("openai", "chatgpt-web", imagenes=len(pieza.slides))]
