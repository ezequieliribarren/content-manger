"""Motor 3 · Python local + GPT (imagen)."""
from __future__ import annotations

from ..models import Pieza, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar


@registrar
class GptImagen(Motor):
    id = "gpt_imagen"
    nombre = "Python + GPT Imagen"
    descripcion = "Le manda a GPT la imagen de la plantilla más la idea y guarda la imagen que devuelve."
    tipo = "api"
    usa_referencia = "imagen"
    formatos_nativos = ("4x5", "9x16", "1x1", "pdf")
    orden = 3

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        n = len(pieza.slides) * 3
        return [Uso("openai", "gpt-image-2", input_tokens=250 * n, image_input_tokens=1300 * n,
                    output_tokens=1600 * n, imagenes=n)]

    def generar(self, pieza: Pieza, ctx: Contexto):
        raise ErrorConfiguracion("Motor 3 todavía no implementado: usalo en modo simulado")
