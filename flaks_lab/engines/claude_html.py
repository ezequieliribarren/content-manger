"""Motor 2 · Claude API + plantillas HTML.

Igual que el motor 1, pero el texto sale de la API de Anthropic. Misma plantilla HTML de marca.
"""
from __future__ import annotations

from .. import proveedores, redaccion
from ..models import Pieza, Resultado, Uso
from .base import Contexto, Motor, registrar
from .gpt_html import renderizar_plantilla, resultado_html


def escribir_con_claude(pieza: Pieza, ctx: Contexto, con_referencia: bool = True) -> tuple[dict, Uso]:
    """Devuelve (texto validado, uso). Compartido con Claude + Canva."""
    s = ctx.settings
    modelo = s["modelos"]["anthropic_texto"]
    client = proveedores.cliente_anthropic(s)
    usar_ref = bool(ctx.referencia and con_referencia)
    contenido: list[dict] = []
    if usar_ref:
        mime, b64 = redaccion.imagen_b64(ctx.referencia)
        contenido.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
    contenido.append({"type": "text", "text": redaccion.pedido(pieza, usar_ref)})
    output_config: dict = {"format": {"type": "json_schema", "schema": redaccion.ESQUEMA}}
    if s["modelos"].get("anthropic_effort"):
        output_config["effort"] = s["modelos"]["anthropic_effort"]

    def llamar():
        with proveedores.errores_anthropic():
            return client.beta.messages.create(
                model=modelo,
                max_tokens=16000,
                system=redaccion.instrucciones(ctx.plantilla.brand),
                messages=[{"role": "user", "content": contenido}],
                output_config=output_config,
                # Si el modelo declina el pedido, la API lo reintenta en el modelo de respaldo recomendado.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )

    ctx.paso(f"Escribiendo texto ({modelo})")
    resp = ctx.llamar_api(llamar, "Anthropic texto")
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude declinó el pedido ({getattr(resp, 'stop_details', None)})")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Claude cortó la respuesta por max_tokens")
    texto = next((b.text for b in resp.content if b.type == "text"), "")
    if not texto:
        raise RuntimeError("Claude no devolvió texto")
    u = resp.usage
    entrada = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + \
        (getattr(u, "cache_creation_input_tokens", 0) or 0)
    # Se cobra al modelo que respondió (puede ser el de respaldo).
    uso = Uso("anthropic", resp.model or modelo, input_tokens=entrada, output_tokens=u.output_tokens or 0)
    return redaccion.validar(texto, pieza), uso


@registrar
class ClaudeHtml(Motor):
    id = "claude_html"
    nombre = "Claude API + HTML"
    descripcion = "Texto con la API de Anthropic y la misma plantilla HTML de marca."
    tipo = "api"
    usa_referencia = "estructura"
    formatos_nativos = ("4x5", "9x16", "1x1", "pdf")
    orden = 2

    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return [Uso("anthropic", "claude-opus-5-5", input_tokens=1000 + 60 * len(pieza.slides),
                    output_tokens=140 * len(pieza.slides))]

    def generar(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        datos, uso = escribir_con_claude(pieza, ctx)
        archivos = renderizar_plantilla(datos, ctx)
        return resultado_html(datos, archivos, uso)
