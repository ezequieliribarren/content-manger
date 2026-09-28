"""Motor 1 · GPT API + plantillas HTML.

Texto por la API de OpenAI (salida JSON con esquema) y plantilla HTML de marca renderizada a PNG con Playwright.
La referencia (si hay) se manda como imagen solo para la estructura y el tono del texto.
"""
from __future__ import annotations

from .. import proveedores, redaccion, render
from ..models import Pieza, Resultado, Uso
from .base import Contexto, ErrorConfiguracion, Motor, registrar


def escribir_con_gpt(pieza: Pieza, ctx: Contexto, con_referencia: bool = True) -> tuple[dict, Uso]:
    """Devuelve (texto validado, uso). Compartido con GPT + Canva."""
    s = ctx.settings
    modelo = s["modelos"]["openai_texto"]
    client = proveedores.cliente_openai(s)
    contenido: list[dict] = [{"type": "input_text", "text": redaccion.pedido(pieza, bool(ctx.referencia and con_referencia))}]
    if ctx.referencia and con_referencia:
        mime, b64 = redaccion.imagen_b64(ctx.referencia)
        contenido.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "low"})

    def llamar():
        with proveedores.errores_openai():
            return client.responses.create(
                model=modelo,
                instructions=redaccion.instrucciones(ctx.plantilla.brand),
                input=[{"role": "user", "content": contenido}],
                text={"format": {"type": "json_schema", "name": "carrusel", "schema": redaccion.ESQUEMA,
                                 "strict": True}},
            )

    ctx.paso(f"Escribiendo texto ({modelo})")
    resp = ctx.llamar_api(llamar, "OpenAI texto")
    if getattr(resp, "status", "completed") not in ("completed", None):
        raise RuntimeError(f"OpenAI devolvió estado {resp.status}: {getattr(resp, 'incomplete_details', '')}")
    texto = resp.output_text
    if not texto:
        raise RuntimeError("OpenAI no devolvió texto")
    u = resp.usage
    uso = Uso("openai", modelo, input_tokens=u.input_tokens if u else 0, output_tokens=u.output_tokens if u else 0)
    return redaccion.validar(texto, pieza), uso


def renderizar_plantilla(datos: dict, ctx: Contexto, formatos=("4x5", "9x16", "1x1", "pdf")) -> dict:
    if not ctx.plantilla.html:
        raise ErrorConfiguracion(f"No hay plantilla HTML para {ctx.pieza.cliente} (ni la base en plantillas/_base)")
    ctx.paso("Renderizando plantilla HTML")
    ctx.chequear()
    return render.renderizar(ctx.plantilla.html, datos["slides"], ctx.plantilla.brand, ctx.out_dir, formatos)


def resultado_html(datos: dict, archivos: dict, uso: Uso) -> Resultado:
    return Resultado(archivos=archivos, uso=[uso],
                     textos=[{"slide": s["numero"], "titulo": s["titulo"], "texto": s["texto"], "cta": s["cta"]}
                             for s in datos["slides"]],
                     extra={"caption": datos["caption"], "hashtags": datos["hashtags"]})


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

    def generar(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        datos, uso = escribir_con_gpt(pieza, ctx)
        archivos = renderizar_plantilla(datos, ctx)
        return resultado_html(datos, archivos, uso)
