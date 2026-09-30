"""Tipos compartidos entre el orquestador y los motores."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


@dataclass
class Pieza:
    """Una fila del Sheet: un carrusel para un cliente y una fecha."""

    cliente: str                 # id del cliente (slug), p. ej. "flaks"
    fecha: str                   # YYYY-MM-DD
    slides: list[str]            # contenido de cada slide, en orden
    fila: int = 0                # fila del Sheet (para trazabilidad)
    referencia: str = ""         # link de Drive o nombre de archivo en /referencias/{cliente}/
    que_tomar: str = ""          # estilo visual / estructura de slides / idea de contenido
    plantilla: str = ""          # imagen de plantilla solo para esta fila (si no, la del cliente)
    id: str = ""

    def __post_init__(self) -> None:
        self.slides = [s.strip() for s in self.slides if s and s.strip()]
        if not self.id:
            self.id = f"{self.cliente}-{self.fecha.replace('-', '')}-f{self.fila:03d}"

    @property
    def content_hash(self) -> str:
        datos = [self.slides, self.referencia, self.que_tomar] + ([self.plantilla] if self.plantilla else [])
        payload = json.dumps(datos, ensure_ascii=False)
        return hashlib.sha1(payload.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "cliente": self.cliente, "fecha": self.fecha, "fila": self.fila,
            "slides": self.slides, "referencia": self.referencia, "que_tomar": self.que_tomar,
            "plantilla": self.plantilla,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Pieza":
        slides = row["slides"]
        if isinstance(slides, str):
            slides = json.loads(slides)
        return cls(cliente=row["client"], fecha=row["fecha"], slides=slides, fila=row.get("fila") or 0,
                   referencia=row.get("referencia") or "", que_tomar=row.get("que_tomar") or "",
                   plantilla=row.get("plantilla") or "", id=row["id"])


@dataclass
class Uso:
    """Consumo reportado por la API en una llamada (tokens o imágenes)."""

    proveedor: str
    modelo: str
    input_tokens: int = 0
    output_tokens: int = 0
    image_input_tokens: int = 0   # tokens de imagen de entrada (APIs de imagen)
    imagenes: int = 0             # imágenes generadas
    detalle: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Resultado:
    """Lo que devuelve un motor: archivos por formato + consumo."""

    archivos: dict[str, list[Path]] = field(default_factory=dict)   # formato -> slides (o [pdf])
    uso: list[Uso] = field(default_factory=list)
    textos: list[dict] = field(default_factory=list)                # texto final por slide
    notas: str = ""
    esperando_manual: bool = False                                  # motor semi-manual (Canva)
    extra: dict = field(default_factory=dict)
