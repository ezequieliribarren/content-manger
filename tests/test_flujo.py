import json

from flaks_lab import config, db, stats, storage
from flaks_lab.engines.base import Motor, MotorBloqueado, REGISTRO

from conftest import correr_cola


def test_flujo_simulado_completo(orq):
    r = orq.sincronizar()
    assert r["piezas"] == 5
    activos = [k for k, c in REGISTRO.items() if c.activo_por_defecto]
    assert r["encolados"] == 5 * len(activos)
    # sincronizar de nuevo no duplica
    assert orq.sincronizar()["encolados"] == 0

    correr_cola(orq)
    listos = db.query("SELECT * FROM jobs WHERE status = 'listo'")
    esperando = db.query("SELECT * FROM jobs WHERE status = 'esperando_manual'")
    assert len(esperando) == 5  # GPT + Canva espera la subida manual
    assert len(listos) == 5 * (len(activos) - 1)

    job = next(j for j in listos if j["engine"] == "gpt_html")
    d = config.OUTPUT_DIR / job["output_dir"]
    # /output/{cliente}/{fecha}/{motor}/{pieza-id}/{formato}/slide-01.png
    partes = d.relative_to(config.OUTPUT_DIR).parts
    assert partes[0] == job["client"] and partes[1] == job["fecha"] and partes[2] == "gpt_html"
    for fmt in ("4x5", "9x16", "1x1"):
        assert (d / fmt / "slide-01.png").exists()
    assert (d / "pdf" / "carrusel-linkedin.pdf").exists()
    meta = json.loads((d / "meta.json").read_text())
    assert meta["costo_usd"] > 0 and meta["simulado"] is True
    assert len(storage.escanear()) == len(listos) + len(esperando)


def test_canva_manual_y_evaluacion(orq):
    orq.sincronizar(cliente="flaks")
    correr_cola(orq, "gpt_canva")
    job = db.one("SELECT * FROM jobs WHERE engine = 'gpt_canva' AND status = 'esperando_manual'")
    assert (config.OUTPUT_DIR / job["output_dir"] / "canva").exists()
    orq.completar_manual(job["id"], [])  # simulado: genera placeholders
    job = db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))
    assert job["status"] == "listo"

    orq.evaluar(job["id"], diseno=4, texto=5, marca=3, estado="aprobado", instagram={"alcance": 1200})
    meta = storage.leer_meta(config.OUTPUT_DIR / job["output_dir"])
    assert meta["evaluacion"]["estado"] == "aprobado" and meta["instagram"]["alcance"] == 1200
    fila = next(m for m in stats.ranking() if m["id"] == "gpt_canva")
    assert fila["puntaje"] == 4.0 and fila["aprobados"] == 1
    assert fila["costo_por_aprobado"] == fila["costo_usd"]


def test_bloqueo_pausa_24h_y_vuelve_a_la_cola(orq, monkeypatch):
    orq.sincronizar(cliente="flaks")

    def bloquear(self, pieza, ctx):
        raise MotorBloqueado("captcha detectado")

    monkeypatch.setattr(Motor, "simular", bloquear)
    job = orq._reclamar("gemini_web")
    orq.ejecutar(job, REGISTRO["gemini_web"](), db.get_settings(), True)
    st = orq.estado_motor("gemini_web")
    assert st["paused_until"] > db.now() and "captcha" in st["pause_reason"]
    assert db.one("SELECT status FROM jobs WHERE id = ?", (job["id"],))["status"] == "en_cola"
    assert db.query("SELECT * FROM alerts")


def test_eliminar_y_restaurar_motor(orq):
    orq.sincronizar(cliente="flaks")
    n = orq.eliminar("gpt_imagen")
    assert n == 3
    assert orq.estado_motor("gpt_imagen")["deleted"] == 1
    orq.restaurar("gpt_imagen")
    st = orq.estado_motor("gpt_imagen")
    assert st["deleted"] == 0 and st["enabled"] == 0


def test_tope_diario_ritmo_humano(orq):
    s = db.get_settings()
    s["ritmo_humano"]["tope_diario"] = [1, 1]
    db.save_settings(s)
    cls = REGISTRO["gemini_web"]
    st = orq.estado_motor("gemini_web")
    assert orq._puede_trabajar(cls, st, s, simulado=True) is None
    db.execute("UPDATE engine_state SET day_count = 1 WHERE engine = 'gemini_web'")
    assert "Tope diario" in orq._puede_trabajar(cls, orq.estado_motor("gemini_web"), s, simulado=True)
