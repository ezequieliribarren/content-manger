"""Motor 3 · Python local + GPT imagen.

Le manda a la API de imágenes de OpenAI la imagen de la plantilla de marca (y la referencia, si hay) más la idea
de cada slide, y guarda la imagen que devuelve. Genera nativamente los formatos configurados (por defecto 4:5,
9:16 y 1:1); el PDF se arma con sus propios slides 4:5.
"""
from __future__ import annotations

import base64
from pathlib import Path

from .. import formats, plantillas, proveedores
from ..models import Pieza, Resultado, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar

# Tamaño pedido a la API por formato; después se recorta al tamaño exacto (1080 x ...).
TAMANOS = {"4x5": "1024x1536", "9x16": "1024x1536", "1x1": "1024x1024"}
DESCRIPCION_FORMATO = {
    "4x5": "vertical 4:5 para carrusel de Instagram (se recortan un poco arriba y abajo: dejá margen)",
    "9x16": "vertical 9:16 para historia o reel (se recortan los costados: dejá margen lateral y dejá libres "
            "el 12 % superior e inferior para la interfaz de Instagram)",
    "1x1": "cuadrado 1:1 para post",
}


def prompt_slide(pieza: Pieza, i: int, texto: str, formato: str, brand: dict, con_ref: bool) -> str:
    n = len(pieza.slides)
    rol = "portada" if i == 1 else ("cierre con llamada a la acción" if i == n and n > 1 else "slide de contenido")
    ref = ""
    if con_ref:
        que = pieza.que_tomar or "estilo visual"
        ref = (f"\nLa segunda imagen es una REFERENCIA. Tomá de ella únicamente: {que}. No copies su texto, "
               "sus logos ni su marca.")
    return f"""Diseñá el slide {i} de {n} ({rol}) de un carrusel de la marca {brand.get('nombre')}.
La primera imagen es la PLANTILLA DE MARCA: respetá sus colores, tipografías, márgenes, estilo y elementos fijos
(nombre de la marca, contador {i:02d}/{n:02d}, handle {brand.get('handle', '')}).{ref}
Estilo de la marca: {brand.get('estilo_visual', '')}
Formato: {DESCRIPCION_FORMATO[formato]}.

Texto del slide (escribilo EXACTAMENTE así, sin agregar ni cambiar palabras, con buena jerarquía tipográfica):
\"\"\"{texto}\"\"\"

Imagen limpia, legible, sin marcas de agua ni texto adicional."""


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

    def generar(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        s = ctx.settings
        modelo = s["modelos"]["openai_imagen"]
        calidad = s["modelos"].get("openai_imagen_calidad") or "medium"
        pedidos = [f for f in s.get("motor3_formatos", ["4x5", "9x16", "1x1"]) if f in TAMANOS]
        if "4x5" not in pedidos:
            pedidos.insert(0, "4x5")  # el 4:5 es la base para reexportar el resto
        client = proveedores.cliente_openai(s)
        uso = Uso("openai", modelo)
        res = Resultado(uso=[uso])
        for fmt in pedidos:
            try:
                tpl = plantillas.imagen_plantilla(ctx.plantilla, fmt)
            except FileNotFoundError as e:
                raise ErrorConfiguracion(str(e)) from e
            paths = []
            for i, texto in enumerate(pieza.slides, 1):
                ctx.paso(f"Imagen {fmt} · slide {i}/{len(pieza.slides)} ({modelo})")
                p = ctx.dir_formato(fmt) / f"slide-{i:02d}.png"
                self._generar_imagen(client, modelo, calidad, tpl, ctx.referencia,
                                     prompt_slide(pieza, i, texto, fmt, ctx.plantilla.brand, bool(ctx.referencia)),
                                     TAMANOS[fmt], p, uso, ctx)
                formats.normalizar(p, fmt)
                paths.append(p)
            res.archivos[fmt] = paths
        res.archivos["pdf"] = [formats.exportar_pdf(res.archivos["4x5"], ctx.dir_formato("pdf") / "carrusel-linkedin.pdf")]
        res.textos = [{"slide": i, "texto": t} for i, t in enumerate(pieza.slides, 1)]
        return res

    @staticmethod
    def _generar_imagen(client, modelo: str, calidad: str, plantilla: Path, referencia: Path | None, prompt: str,
                        size: str, dest: Path, uso: Uso, ctx: Contexto) -> None:
        def llamar():
            imagenes = [open(plantilla, "rb")]
            if referencia:
                imagenes.append(open(referencia, "rb"))
            try:
                with proveedores.errores_openai():
                    return client.images.edit(model=modelo, image=imagenes, prompt=prompt, size=size,
                                              quality=calidad, n=1)
            finally:
                for f in imagenes:
                    f.close()

        resp = ctx.llamar_api(llamar, "OpenAI imagen")
        if not resp.data or not resp.data[0].b64_json:
            raise RuntimeError("OpenAI no devolvió una imagen")
        dest.write_bytes(base64.b64decode(resp.data[0].b64_json))
        uso.imagenes += 1
        u = getattr(resp, "usage", None)
        if u:
            det = getattr(u, "input_tokens_details", None)
            img_in = (getattr(det, "image_tokens", 0) or 0) if det else 0
            uso.image_input_tokens += img_in
            uso.input_tokens += (u.input_tokens or 0) - img_in
            uso.output_tokens += u.output_tokens or 0
