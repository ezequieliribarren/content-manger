"""Plantilla de marca por cliente (/plantillas/{cliente}/) y referencias (/referencias/{cliente}/)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config

DEFAULT_BRAND = {
    "nombre": "Cliente",
    "handle": "@cliente",
    "colores": {"fondo": "#191035", "texto": "#FFFFFF", "acento": "#00FE5E", "secundario": "#7B5CFA"},
    "tipografias": {"titulos": "Archivo", "texto": "Inter"},
    "tono": "Cercano, claro y directo.",
    "reglas": [],
}

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


@dataclass
class Plantilla:
    cliente: str
    carpeta: Path
    brand: dict = field(default_factory=dict)
    html: Path | None = None       # plantilla.html (motores 1, 2)
    imagen: Path | None = None     # plantilla.png (motores 3, 5)


def cargar(cliente: str) -> Plantilla:
    carpeta = config.TEMPLATES_DIR / cliente
    brand = json.loads(json.dumps(DEFAULT_BRAND))
    brand["nombre"] = cliente.replace("-", " ").title()
    bj = carpeta / "brand.json"
    if bj.exists():
        data = json.loads(bj.read_text(encoding="utf-8"))
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(brand.get(k), dict):
                brand[k].update(v)
            else:
                brand[k] = v
    html = carpeta / "plantilla.html"
    if not html.exists():
        html = config.TEMPLATES_DIR / "_base" / "plantilla.html"
    imagen = next((carpeta / f"plantilla{e}" for e in IMG_EXT if (carpeta / f"plantilla{e}").exists()), None)
    return Plantilla(cliente=cliente, carpeta=carpeta, brand=brand,
                     html=html if html.exists() else None, imagen=imagen)


_DRIVE_ID = re.compile(r"(?:/d/|id=|/folders/)([A-Za-z0-9_-]{10,})")


def resolver_referencia(cliente: str, referencia: str, settings: dict) -> Path | None:
    """Devuelve la ruta local de la referencia (descargándola de Drive si es un link)."""
    ref = (referencia or "").strip()
    if not ref:
        return None
    carpeta = config.REFERENCES_DIR / cliente
    if "drive.google.com" in ref or "docs.google.com" in ref:
        m = _DRIVE_ID.search(ref)
        if not m:
            raise ValueError(f"No pude leer el ID de Drive en: {ref}")
        return _descargar_drive(m.group(1), carpeta / "_drive", settings)
    local = carpeta / ref
    if local.exists():
        return local
    for ext in IMG_EXT:
        if (carpeta / f"{ref}{ext}").exists():
            return carpeta / f"{ref}{ext}"
    raise FileNotFoundError(f"No encontré la referencia '{ref}' en {carpeta}")


def _descargar_drive(file_id: str, dest_dir: Path, settings: dict) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    cached = next(dest_dir.glob(f"{file_id}.*"), None)
    if cached:
        return cached
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    import io

    from .sheets import credenciales

    creds = credenciales(settings, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    meta = svc.files().get(fileId=file_id, fields="name,mimeType").execute()
    ext = Path(meta.get("name", "")).suffix or ".png"
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest = dest_dir / f"{file_id}{ext}"
    dest.write_bytes(buf.getvalue())
    return dest


def imagen_plantilla(plantilla: Plantilla, formato: str = "4x5") -> Path:
    """Imagen de la plantilla para los motores de imagen (3 y 5).

    Usa /plantillas/{cliente}/plantilla.png si existe; si no, renderiza la plantilla HTML con un texto de muestra
    (se guarda en data/plantillas_generadas/ para no pisar tus archivos).
    """
    if plantilla.imagen:
        return plantilla.imagen
    if not plantilla.html:
        raise FileNotFoundError(f"No hay plantilla.png ni plantilla.html para {plantilla.cliente}")
    from . import render

    dest_dir = config.DATA_DIR / "plantillas_generadas" / plantilla.cliente
    dest = dest_dir / formato / "slide-01.png"
    fuente = max(plantilla.html.stat().st_mtime, (plantilla.carpeta / "brand.json").stat().st_mtime
                 if (plantilla.carpeta / "brand.json").exists() else 0)
    if dest.exists() and dest.stat().st_mtime >= fuente:
        return dest
    muestra = [{"numero": 1, "total": 5, "tipo": "portada", "etiqueta": "Etiqueta",
                "titulo": "Título de *ejemplo* del slide", "texto": "Texto de apoyo de una o dos líneas.", "cta": ""}]
    render.renderizar(plantilla.html, muestra, plantilla.brand, dest_dir, (formato,))
    return dest
