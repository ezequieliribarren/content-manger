"""Rutas del proyecto y configuración editable (guardada en SQLite)."""
from __future__ import annotations

import copy
import os
from pathlib import Path

ROOT = Path(os.environ.get("FLAKS_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
TEMPLATES_DIR = ROOT / "plantillas"
REFERENCES_DIR = ROOT / "referencias"
DEMO_SHEET = ROOT / "datos" / "demo_sheet.json"
DB_PATH = DATA_DIR / "lab.db"
BROWSER_PROFILES_DIR = DATA_DIR / "navegador"

# Formatos de salida. "4x5" es el formato base desde el que se reexporta el resto.
FORMATS = {
    "4x5": {"label": "Carrusel 4:5", "w": 1080, "h": 1350},
    "9x16": {"label": "Historia / Reel 9:16", "w": 1080, "h": 1920},
    "1x1": {"label": "Post cuadrado 1:1", "w": 1080, "h": 1080},
    "pdf": {"label": "PDF LinkedIn", "w": 1080, "h": 1350},
}
IMAGE_FORMATS = ("4x5", "9x16", "1x1")

# Valores por defecto de Configuración. Todo lo que está acá se puede editar desde la UI.
DEFAULT_SETTINGS: dict = {
    "claves": {
        "openai_api_key": "",
        "anthropic_api_key": "",
        "google_service_account_json": "credenciales/service-account.json",
        "spreadsheet_id": "",
    },
    "clientes": [
        {"id": "flaks", "nombre": "Flaks", "pestana": "Flaks", "activo": True},
        {"id": "cliente-1", "nombre": "Cliente 1", "pestana": "Cliente 1", "activo": True},
        {"id": "cliente-2", "nombre": "Cliente 2", "pestana": "Cliente 2", "activo": True},
    ],
    "cliente_piloto": "flaks",
    # Motores en modo simulado: no llaman a ninguna API ni abren el navegador.
    "simulacion": {
        "gpt_html": True, "claude_html": True, "gpt_imagen": True,
        "gpt_canva": True, "gemini_web": True, "claude_canva": True, "gpt_web": True,
    },
    # Multiplica las esperas en modo simulado (0.01 = 100 veces más rápido).
    "simulacion_escala_tiempo": 0.01,
    "simulacion_tasa_error": 0.08,
    # Formatos que el motor 3 genera con la API (cada uno cuesta una imagen por slide); el resto se reexporta.
    "motor3_formatos": ["4x5", "9x16", "1x1"],
    "modelos": {
        "openai_texto": "gpt-5.4-mini",
        "openai_imagen": "gpt-image-2",
        "openai_imagen_calidad": "medium",
        "anthropic_texto": "claude-opus-5-5",
        "anthropic_effort": "medium",
    },
    # USD. Tokens: precio por millón. Imágenes: precio por imagen (si la API no devuelve tokens).
    # Son valores de referencia: revisalos contra la página de precios de cada proveedor.
    "precios": {
        "gpt-5.4-mini": {"input_mtok": 0.75, "output_mtok": 4.50},
        "gpt-5.5": {"input_mtok": 5.00, "output_mtok": 30.00},
        "claude-opus-5-5": {"input_mtok": 4.00, "output_mtok": 20.00},
        "claude-sonnet-5-5": {"input_mtok": 2.00, "output_mtok": 10.00},
        "claude-opus-4-8": {"input_mtok": 5.00, "output_mtok": 25.00},
        "claude-haiku-4-5": {"input_mtok": 1.00, "output_mtok": 5.00},
        "gpt-image-2": {"input_mtok": 5.00, "image_input_mtok": 8.00, "output_mtok": 30.00, "por_imagen": 0.05},
        "gpt-image-1": {"input_mtok": 5.00, "image_input_mtok": 10.00, "output_mtok": 40.00, "por_imagen": 0.063},
        "gemini-web": {"por_imagen": 0.0},
        "chatgpt-web": {"por_imagen": 0.0},
    },
    "limites": {
        "presupuesto_diario_usd": 5.0,
        "max_piezas_dia_por_motor": 30,
        "api_espera_min_s": 1.0,
        "api_espera_max_s": 3.0,
        "api_reintentos": 5,
        "api_backoff_base_s": 2.0,
        "sync_automatico_min": 0,
        "solo_fechas_desde_hoy": False,
    },
    "ritmo_humano": {
        "espera_carga_s": [2, 6],
        "escritura_ms_por_letra": [40, 120],
        "pausa_entre_prompts_s": [30, 120],
        "pausa_entre_carruseles_min": [5, 12],
        "descanso_cada_n": [4, 5],
        "descanso_min": [15, 30],
        "tope_diario": [8, 10],
        "franjas": ["09:00-11:00", "14:00-16:00", "20:00-22:00"],
        "pausa_bloqueo_horas": 24,
    },
    # Selectores de las webs automatizadas. Cambian seguido: se editan desde Configuración.
    "selectores": {
        "gemini_web": {
            "url": "https://gemini.google.com/app",
            "prompt": "rich-textarea div[contenteditable='true'], div[contenteditable='true'][role='textbox']",
            "enviar": "button[aria-label*='Send'], button[aria-label*='Enviar']",
            "subir_menu": "button[aria-label*='upload'], button[aria-label*='Subir'], button[aria-label*='Upload']",
            "input_archivo": "input[type='file']",
            "imagen_respuesta": "model-response img, message-content img, .response-container img",
            "respuesta_lista": "model-response",
            "login": "a[href*='accounts.google.com/ServiceLogin'], a[aria-label*='Sign in'], a[aria-label*='Acceder']",
        },
        "gpt_web": {
            "url": "https://chatgpt.com/",
            "prompt": "#prompt-textarea, div[contenteditable='true']",
            "enviar": "button[data-testid='send-button'], button[aria-label*='Send']",
            "subir_menu": "",
            "input_archivo": "input[type='file']",
            "imagen_respuesta": "div[data-message-author-role='assistant'] img",
            "respuesta_lista": "div[data-message-author-role='assistant']",
            "login": "button[data-testid='login-button']",
        },
    },
}


def merge_defaults(stored: dict | None) -> dict:
    """Combina lo guardado con los valores por defecto (para claves nuevas)."""
    result = copy.deepcopy(DEFAULT_SETTINGS)

    def _merge(base: dict, over: dict) -> None:
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                _merge(base[k], v)
            else:
                base[k] = v

    if stored:
        _merge(result, stored)
    return result


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUTPUT_DIR, TEMPLATES_DIR, REFERENCES_DIR, BROWSER_PROFILES_DIR):
        d.mkdir(parents=True, exist_ok=True)
