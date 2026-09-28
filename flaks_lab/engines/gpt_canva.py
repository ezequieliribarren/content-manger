"""Motor 4 · GPT + Canva (semi-manual).

1. Escribe el texto con GPT (ignora la referencia).
2. Exporta un CSV listo para Canva Bulk Create: una fila por carrusel, columnas slideN_titulo / slideN_texto.
3. Queda "esperando subida": exportás desde Canva (PNG, ZIP de PNG o PDF) y lo subís desde el dashboard.
   Se guarda como 4:5 y el resto de los formatos se reexporta.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .. import formats
from ..models import Pieza, Resultado, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _natural(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def escribir_csv(datos: dict, pieza: Pieza, dest: Path) -> Path:
    """CSV para Canva Bulk Create. En Canva: Apps → Bulk create → subir CSV → conectar cada campo con su texto."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fila = {"pieza": pieza.id, "fecha": pieza.fecha}
    for s in datos["slides"]:
        n = s["numero"]
        titulo = s["titulo"].replace("*", "")
        fila[f"slide{n}_etiqueta"] = s["etiqueta"]
        fila[f"slide{n}_titulo"] = titulo
        fila[f"slide{n}_texto"] = s["texto"]
        if s.get("cta"):
            fila[f"slide{n}_cta"] = s["cta"]
    fila["caption"] = datos.get("caption", "")
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fila))
        w.writeheader()
        w.writerow(fila)
    return dest


def _pdf_a_png(pdf: Path, dest_dir: Path) -> list[Path]:
    try:
        import pypdfium2 as pdfium
    except ImportError as e:  # pragma: no cover
        raise ErrorConfiguracion("Para subir PDF instalá pypdfium2 (o subí los PNG)") from e
    doc = pdfium.PdfDocument(str(pdf))
    out = []
    for i in range(len(doc)):
        page = doc[i]
        escala = 1350 / page.get_height() * 1.0
        img = page.render(scale=max(escala, 1.0)).to_pil()
        p = dest_dir / f"{pdf.stem}-{i + 1:03d}.png"
        img.save(p)
        out.append(p)
    return out


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

    def escribir(self, pieza: Pieza, ctx: Contexto) -> tuple[dict, Uso]:
        from .gpt_html import escribir_con_gpt

        return escribir_con_gpt(pieza, ctx, con_referencia=False)

    def _esperar(self, datos: dict, pieza: Pieza, ctx: Contexto, usos: list[Uso]) -> Resultado:
        ctx.paso("Exportando CSV para Canva")
        csv_path = escribir_csv(datos, pieza, ctx.dir_formato("canva") / "bulk-create.csv")
        return Resultado(
            uso=usos, esperando_manual=True,
            textos=[{"slide": s["numero"], "titulo": s["titulo"], "texto": s["texto"], "cta": s["cta"]}
                    for s in datos["slides"]],
            notas="CSV listo: esperando que subas el resultado de Canva",
            extra={"csv": str(csv_path.relative_to(ctx.out_dir)), "caption": datos.get("caption", ""),
                   "hashtags": datos.get("hashtags", [])})

    def generar(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        datos, uso = self.escribir(pieza, ctx)
        return self._esperar(datos, pieza, ctx, [uso])

    def simular(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        from .. import redaccion

        ctx.dormir(3)
        datos = redaccion.validar({"slides": [{"titulo": t} for t in pieza.slides], "caption": "", "hashtags": []},
                                  pieza)
        return self._esperar(datos, pieza, ctx, self.uso_simulado(pieza))

    def completar_manual(self, pieza: Pieza, ctx: Contexto, archivos: list[Path]) -> Resultado:
        d = ctx.dir_formato("4x5")
        if not archivos:
            if not ctx.simulado:
                raise ErrorConfiguracion("Subí los PNG (o un ZIP / PDF) exportados desde Canva")
            paths = []
            for i, t in enumerate(pieza.slides, 1):
                p = d / f"slide-{i:02d}.png"
                formats.placeholder_slide(t, i, len(pieza.slides), "4x5", ctx.plantilla.brand, self.nombre).save(p)
                paths.append(p)
            return Resultado(archivos={"4x5": paths})
        imagenes: list[Path] = []
        tmp = ctx.out_dir / "_subida"
        tmp.mkdir(exist_ok=True)
        for a in sorted(archivos, key=_natural):
            if a.suffix.lower() == ".pdf":
                imagenes += _pdf_a_png(a, tmp)
            elif a.suffix.lower() in IMG_EXT:
                imagenes.append(a)
        if not imagenes:
            raise ErrorConfiguracion("No encontré imágenes en lo que subiste (PNG, JPG, ZIP o PDF)")
        paths = []
        for i, src in enumerate(imagenes, 1):
            p = d / f"slide-{i:02d}.png"
            p.write_bytes(src.read_bytes())
            formats.normalizar(p, "4x5")
            paths.append(p)
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
        notas = ""
        if len(paths) != len(pieza.slides):
            notas = f"Subiste {len(paths)} slides y la pieza tiene {len(pieza.slides)}"
            ctx.log(notas, "warning")
        return Resultado(archivos={"4x5": paths}, notas=notas)
