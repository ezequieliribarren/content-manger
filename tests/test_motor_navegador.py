"""Motor de navegador contra una página de chat falsa (no se abre ningún sitio real)."""
import os
from pathlib import Path

import pytest
from PIL import Image

from flaks_lab import config, db
from flaks_lab.engines.base import REGISTRO

from conftest import CHROMIUM

pytestmark = pytest.mark.skipif(not CHROMIUM, reason="Chromium de Playwright no disponible")
FAKE = (Path(__file__).parent / "fixtures" / "fake_chat.html").resolve().as_uri()


@pytest.fixture()
def gemini_falso(orq, monkeypatch):
    monkeypatch.setenv("FLAKS_HEADLESS", "1")
    s = db.get_settings()
    s["simulacion"]["gemini_web"] = False
    s["navegador_canal"] = ""
    r = s["ritmo_humano"]
    r["espera_carga_s"] = [0, 0]
    r["escritura_ms_por_letra"] = [0, 0]
    r["pausa_entre_prompts_s"] = [0, 0]
    r["franjas"] = ["00:00-23:59"]
    sel = s["selectores"]["gemini_web"]
    sel["url"] = FAKE
    sel["login"] = ""
    db.save_settings(s)
    orq.sincronizar(cliente="flaks")
    return s


def _correr_uno(orq):
    job = orq._reclamar("gemini_web")
    orq.ejecutar(job, REGISTRO["gemini_web"](), db.get_settings(), False)
    return db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))


def test_gemini_genera_un_slide_por_prompt(orq, gemini_falso):
    job = _correr_uno(orq)
    assert job["status"] == "listo", job["error"]
    d = config.OUTPUT_DIR / job["output_dir"]
    for i in range(1, 6):
        assert Image.open(d / "4x5" / f"slide-{i:02d}.png").size == (1080, 1350)
    # 9:16, 1:1 y PDF se reexportan desde el 4:5
    assert Image.open(d / "9x16" / "slide-01.png").size == (1080, 1920)
    assert (d / "pdf" / "carrusel-linkedin.pdf").exists()


def test_gemini_bloqueo_pausa_el_motor(orq, gemini_falso):
    s = db.get_settings()
    s["selectores"]["gemini_web"]["url"] = FAKE + "?modo=bloqueo"
    db.save_settings(s)
    job = _correr_uno(orq)
    assert job["status"] == "en_cola"
    st = orq.estado_motor("gemini_web")
    assert st["paused_until"] and "unusual traffic" in st["pause_reason"]


def test_gemini_sin_sesion_pausa_y_avisa(orq, gemini_falso):
    s = db.get_settings()
    s["selectores"]["gemini_web"]["login"] = "#enviar"  # simula un botón de "Iniciar sesión" visible
    db.save_settings(s)
    job = _correr_uno(orq)
    assert job["status"] == "en_cola"
    assert orq.estado_motor("gemini_web")["paused"] == 1
    assert "sesión" in db.query("SELECT message FROM alerts")[-1]["message"]
