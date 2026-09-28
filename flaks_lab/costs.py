"""Costos: consumo real (tokens/imágenes que devuelve la API) x tabla de precios editable."""
from __future__ import annotations

from .models import Uso


def costo_uso(uso: dict | Uso, precios: dict) -> tuple[float, bool]:
    """Devuelve (costo_usd, tiene_precio). input_tokens = tokens de texto de entrada."""
    u = uso.to_dict() if isinstance(uso, Uso) else uso
    p = precios.get(u.get("modelo", ""))
    if not p:
        return 0.0, False
    costo = 0.0
    tokens = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) + (u.get("image_input_tokens") or 0)
    if tokens:
        costo += (u.get("input_tokens") or 0) * p.get("input_mtok", 0) / 1e6
        costo += (u.get("image_input_tokens") or 0) * p.get("image_input_mtok", p.get("input_mtok", 0)) / 1e6
        costo += (u.get("output_tokens") or 0) * p.get("output_mtok", 0) / 1e6
    elif u.get("imagenes"):
        costo += u["imagenes"] * p.get("por_imagen", 0)
    return round(costo, 6), True


def costo_total(usos: list, precios: dict) -> tuple[float, list[str]]:
    total, sin_precio = 0.0, []
    for u in usos:
        c, ok = costo_uso(u, precios)
        total += c
        if not ok:
            sin_precio.append((u.to_dict() if isinstance(u, Uso) else u).get("modelo", "?"))
    return round(total, 6), sorted(set(sin_precio))
