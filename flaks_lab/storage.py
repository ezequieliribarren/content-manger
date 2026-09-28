"""Carpeta de salida: /output/{cliente}/{YYYY-MM-DD}/{motor}/{pieza-id}/{formato}/slide-01.png + meta.json.

La pantalla de Contenido finalizado se arma leyendo estos meta.json.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import config

IG_CAMPOS = ["alcance", "impresiones", "me_gusta", "comentarios", "guardados", "compartidos", "seguidores_nuevos"]


def carpeta_pieza(cliente: str, fecha: str, motor: str, pieza_id: str) -> Path:
    base = config.OUTPUT_DIR / cliente / fecha / motor
    d = base / pieza_id
    n = 2
    while d.exists() and any(d.iterdir()):
        d = base / f"{pieza_id}-v{n}"
        n += 1
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(p: Path) -> str:
    return Path(p).resolve().relative_to(config.OUTPUT_DIR.resolve()).as_posix()


def escribir_meta(piece_dir: Path, meta: dict) -> Path:
    path = piece_dir / "meta.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def leer_meta(piece_dir: Path) -> dict | None:
    path = piece_dir / "meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def actualizar_meta(piece_dir: Path, **cambios) -> dict | None:
    meta = leer_meta(piece_dir)
    if meta is None:
        return None
    for k, v in cambios.items():
        if isinstance(v, dict) and isinstance(meta.get(k), dict):
            meta[k].update(v)
        else:
            meta[k] = v
    escribir_meta(piece_dir, meta)
    return meta


def escanear() -> list[dict]:
    """Lee todos los meta.json de /output."""
    items = []
    if not config.OUTPUT_DIR.exists():
        return items
    for meta_path in config.OUTPUT_DIR.glob("*/*/*/*/meta.json"):
        meta = leer_meta(meta_path.parent)
        if meta:
            meta["_dir"] = rel(meta_path.parent)
            items.append(meta)
    items.sort(key=lambda m: (m.get("fecha", ""), m.get("creado", "")), reverse=True)
    return items


def borrar(piece_dir: Path) -> None:
    if piece_dir.exists() and config.OUTPUT_DIR.resolve() in piece_dir.resolve().parents:
        shutil.rmtree(piece_dir)
