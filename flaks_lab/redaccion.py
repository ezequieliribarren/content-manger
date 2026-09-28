"""Instrucciones y esquema compartidos para escribir el texto del carrusel (motores 1, 2, 4 y Claude + Canva)."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from .models import Pieza

ESQUEMA = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "numero": {"type": "integer"},
                    "tipo": {"type": "string", "enum": ["portada", "contenido", "cierre"]},
                    "etiqueta": {"type": "string"},
                    "titulo": {"type": "string"},
                    "texto": {"type": "string"},
                    "cta": {"type": "string"},
                },
                "required": ["numero", "tipo", "etiqueta", "titulo", "texto", "cta"],
                "additionalProperties": False,
            },
        },
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["slides", "caption", "hashtags"],
    "additionalProperties": False,
}


def instrucciones(brand: dict) -> str:
    reglas = "\n".join(f"- {r}" for r in brand.get("reglas", []))
    return f"""Sos el redactor de redes sociales de la marca {brand.get('nombre')} ({brand.get('handle', '')}).
Escribís el texto final de carruseles de Instagram y LinkedIn.

Tono de la marca: {brand.get('tono', '')}
Reglas de la marca:
{reglas or '- (sin reglas adicionales)'}

Cómo trabajar:
- Recibís el contenido de cada slide tal como lo cargó el equipo en el Sheet. Es la fuente de verdad: respetá la
  idea y el orden, y pulí el texto para que funcione en un slide (título corto y fuerte + texto de apoyo breve).
- Devolvé exactamente un objeto por slide, en el mismo orden y con la misma cantidad.
- El primer slide es "portada", el último es "cierre" (si hay más de uno) y el resto "contenido".
- "titulo": máximo 12 palabras. Podés marcar una palabra clave entre *asteriscos* para resaltarla.
- "texto": 0 a 30 palabras. Vacío si el título alcanza.
- "etiqueta": 1 a 3 palabras opcionales arriba del título (vacío si no suma).
- "cta": solo en el slide de cierre; vacío en los demás.
- "caption": texto para la publicación (2 a 4 oraciones) y "hashtags": 3 a 6, sin espacios.
- Escribí en el idioma del contenido del Sheet.
- Si te paso una imagen de referencia: tomá únicamente lo indicado en "Qué tomar" (por ejemplo la estructura
  de slides o el tono). No copies el texto de la referencia ni su marca: el texto y la identidad son del cliente."""


def pedido(pieza: Pieza, con_referencia: bool) -> str:
    slides = "\n".join(f"Slide {i}: {t}" for i, t in enumerate(pieza.slides, 1))
    ref = ""
    if con_referencia:
        que = pieza.que_tomar or "estructura de slides y tono"
        ref = (f"\n\nAdjunto una imagen de referencia. Qué tomar de ella: {que}. "
               "Usala solo para la estructura y el tono del texto; no copies su texto.")
    return f"Fecha de publicación: {pieza.fecha}\nCantidad de slides: {len(pieza.slides)}\n\n{slides}{ref}"


def imagen_b64(path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return mime, base64.standard_b64encode(Path(path).read_bytes()).decode()


def validar(data: dict | str, pieza: Pieza) -> dict:
    """Normaliza la respuesta del modelo: misma cantidad de slides que el Sheet."""
    if isinstance(data, str):
        data = json.loads(data)
    slides = list(data.get("slides") or [])
    n = len(pieza.slides)
    if len(slides) < n:  # completar con el texto del Sheet si el modelo devolvió menos
        for i in range(len(slides), n):
            slides.append({"titulo": pieza.slides[i], "texto": "", "etiqueta": "", "cta": ""})
    slides = slides[:n]
    for i, s in enumerate(slides, 1):
        s["numero"] = i
        s["total"] = n
        s["tipo"] = "portada" if i == 1 else ("cierre" if i == n and n > 1 else "contenido")
        for k in ("etiqueta", "titulo", "texto", "cta"):
            s[k] = (s.get(k) or "").strip()
    return {"slides": slides, "caption": data.get("caption", ""), "hashtags": data.get("hashtags", [])}
