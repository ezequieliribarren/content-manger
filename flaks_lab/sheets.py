"""Lectura del Google Sheet (solo lectura, cuenta de servicio). Una pestaña por cliente.

Columna A = Fecha, columnas "Contenido Slide N" (B a F, extensible), y opcionales
"Referencia" y "Qué tomar". Sin credenciales se usa datos/demo_sheet.json (modo demo).
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from . import config
from .models import Pieza

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def parse_fecha(valor: str) -> str | None:
    v = str(valor or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def mapear_columnas(header: list[str]) -> dict:
    """Detecta qué columna es cada cosa. Si no hay encabezado reconocible, usa A=fecha, B..=slides."""
    cols = {"fecha": 0, "slides": [], "referencia": None, "que_tomar": None}
    slides: list[tuple[int, int]] = []
    for i, h in enumerate(header):
        n = _norm(h)
        m = re.search(r"slide\s*(\d+)", n)
        if m:
            slides.append((int(m.group(1)), i))
        elif n.startswith("fecha"):
            cols["fecha"] = i
        elif n.startswith("referencia"):
            cols["referencia"] = i
        elif "que tomar" in n or n == "tomar":
            cols["que_tomar"] = i
    if slides:
        cols["slides"] = [i for _, i in sorted(slides)]
    else:
        cols["slides"] = [i for i in range(1, len(header)) if i not in (cols["referencia"], cols["que_tomar"])]
    return cols


def filas_a_piezas(cliente: str, valores: list[list[str]], solo_desde_hoy: bool = False) -> list[Pieza]:
    if not valores:
        return []
    header, filas = valores[0], valores[1:]
    cols = mapear_columnas(header)
    hoy = date.today().isoformat()
    piezas = []
    for n, fila in enumerate(filas, start=2):  # fila 1 = encabezado
        def cell(i: int | None) -> str:
            return str(fila[i]).strip() if i is not None and i < len(fila) else ""

        fecha = parse_fecha(cell(cols["fecha"]))
        slides = [cell(i) for i in cols["slides"]]
        if not fecha or not any(slides):
            continue
        if solo_desde_hoy and fecha < hoy:
            continue
        piezas.append(Pieza(cliente=cliente, fecha=fecha, slides=slides, fila=n,
                            referencia=cell(cols["referencia"]), que_tomar=cell(cols["que_tomar"])))
    return piezas


def credenciales(settings: dict, scopes: list[str] | None = None):
    from google.oauth2 import service_account

    ruta = Path(settings["claves"]["google_service_account_json"])
    if not ruta.is_absolute():
        ruta = config.ROOT / ruta
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el JSON de la cuenta de servicio: {ruta}")
    return service_account.Credentials.from_service_account_file(str(ruta), scopes=scopes or SCOPES)


def hay_credenciales(settings: dict) -> bool:
    ruta = Path(settings["claves"]["google_service_account_json"])
    if not ruta.is_absolute():
        ruta = config.ROOT / ruta
    return bool(settings["claves"].get("spreadsheet_id")) and ruta.exists()


def leer_pestana(settings: dict, pestana: str) -> tuple[list[list[str]], str]:
    """Devuelve (valores, modo). modo = 'google' o 'demo'."""
    if hay_credenciales(settings):
        from googleapiclient.discovery import build

        svc = build("sheets", "v4", credentials=credenciales(settings), cache_discovery=False)
        rango = f"'{pestana}'!A1:Z1000"
        resp = svc.spreadsheets().values().get(
            spreadsheetId=settings["claves"]["spreadsheet_id"], range=rango,
            valueRenderOption="FORMATTED_VALUE").execute()
        return resp.get("values", []), "google"
    demo = json.loads(config.DEMO_SHEET.read_text(encoding="utf-8")) if config.DEMO_SHEET.exists() else {}
    return demo.get(pestana, []), "demo"
