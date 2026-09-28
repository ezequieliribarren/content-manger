"""Motor 4 · GPT + Canva (semi-manual): CSV para Canva Bulk Create y subida del resultado."""
from __future__ import annotations

import csv
from pathlib import Path

from ..models import Pieza, Resultado, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar


@registrar
class GptCanva(Motor):
    id = "gpt_canva"
    nombre = "GPT + Canva"
    descripcion = "Texto con GPT, CSV listo para Canva Bulk Create y espera que subas el resultado."
    tipo = "manual"
    usa_referencia = "ignora"
    formatos_nativos = ("4x5",)
    orden = 4

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("openai", "gpt-5.4-mini", input_tokens=700, output_tokens=100 * len(pieza.slides))]

    def generar(self, pieza: Pieza, ctx: Contexto):
        raise ErrorConfiguracion("Motor 4 todavía no implementado: usalo en modo simulado")

    def simular(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        ctx.paso("Generando CSV para Canva")
        ctx.dormir(3)
        csv_path = ctx.dir_formato("canva") / "bulk-create.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([f"slide{i}" for i in range(1, len(pieza.slides) + 1)])
            w.writerow(pieza.slides)
        return Resultado(uso=self.uso_simulado(pieza), esperando_manual=True,
                         textos=[{"slide": i, "texto": t} for i, t in enumerate(pieza.slides, 1)],
                         notas="CSV listo: esperando que subas el resultado de Canva",
                         extra={"csv": str(csv_path)})

    def completar_manual(self, pieza: Pieza, ctx: Contexto, archivos: list[Path]) -> Resultado:
        from .. import formats

        if not archivos and ctx.simulado:
            d = ctx.dir_formato("4x5")
            paths = []
            for i, t in enumerate(pieza.slides, 1):
                p = d / f"slide-{i:02d}.png"
                formats.placeholder_slide(t, i, len(pieza.slides), "4x5", ctx.plantilla.brand, self.nombre).save(p)
                paths.append(p)
            return Resultado(archivos={"4x5": paths})
        raise ErrorConfiguracion("Motor 4 todavía no implementado")
