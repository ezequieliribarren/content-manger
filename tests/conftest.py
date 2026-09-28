"""Cada sesión de tests corre en una carpeta temporal (FLAKS_HOME) con copias de plantillas y datos demo."""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_HOME = Path(tempfile.mkdtemp(prefix="flaks-test-"))
for carpeta in ("plantillas", "referencias", "datos"):
    shutil.copytree(REPO / carpeta, _HOME / carpeta)
os.environ["FLAKS_HOME"] = str(_HOME)

from flaks_lab import config, db  # noqa: E402
from flaks_lab.orchestrator import Orquestador  # noqa: E402

CHROMIUM = os.environ.get("FLAKS_CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else "")
if CHROMIUM:
    os.environ.setdefault("FLAKS_CHROMIUM", CHROMIUM)


@pytest.fixture()
def orq():
    """Orquestador sin hilos, con base y /output limpios y todo en modo simulado y rápido."""
    shutil.rmtree(config.OUTPUT_DIR, ignore_errors=True)
    config.DB_PATH.unlink(missing_ok=True)
    o = Orquestador()
    o.iniciar(workers=False)
    s = db.get_settings()
    s["simulacion_escala_tiempo"] = 0
    s["simulacion_tasa_error"] = 0
    s["limites"]["api_espera_min_s"] = 0
    s["limites"]["api_espera_max_s"] = 0
    db.save_settings(s)
    yield o
    o.detener()


def correr_cola(o, motor_id=None, max_jobs=100):
    """Procesa trabajos en cola de forma sincrónica (sin hilos)."""
    from flaks_lab.engines.base import REGISTRO

    hechos = 0
    motores = [motor_id] if motor_id else list(REGISTRO)
    for m in motores:
        while hechos < max_jobs:
            job = o._reclamar(m)
            if not job:
                break
            s = db.get_settings()
            o.ejecutar(job, REGISTRO[m](), s, bool(s["simulacion"].get(m, True)))
            hechos += 1
    return hechos
