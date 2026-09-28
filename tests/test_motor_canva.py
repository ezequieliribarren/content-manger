"""Motor 4 (GPT + Canva) y plugin Claude + Canva, con clientes falsos; subida por la API."""
import csv
import io
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from flaks_lab import config, db, proveedores
from flaks_lab.engines.base import REGISTRO

from test_motores_api import FakeAnthropic, FakeOpenAI, _real


def _preparar(orq, motor_id):
    _real(motor_id)
    orq.sincronizar(cliente="flaks")
    job = orq._reclamar(motor_id)
    orq.ejecutar(job, REGISTRO[motor_id](), db.get_settings(), False)
    return db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))


def _png(color="#00FE5E", size=(1080, 1350)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_motor4_csv_y_subida_zip(orq, monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(proveedores, "cliente_openai", lambda s: fake)
    job = _preparar(orq, "gpt_canva")
    assert job["status"] == "esperando_manual", job["error"]
    assert job["cost_usd"] > 0
    # ignora la referencia: solo texto
    assert all(c["type"] == "input_text" for c in fake.pedidos[0]["input"][0]["content"])
    d = config.OUTPUT_DIR / job["output_dir"]
    filas = list(csv.DictReader((d / "canva" / "bulk-create.csv").open(encoding="utf-8")))
    assert len(filas) == 1
    assert filas[0]["slide1_titulo"] == "Título 1" and "slide5_cta" in filas[0]

    from flaks_lab.main import app

    app.state.sin_workers = True
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in (10, 2, 1, 3, 4):  # orden "natural": 1, 2, 3, 4, 10
            z.writestr(f"diseno/{i}.png", _png(size=(1080, 1080)))
    with TestClient(app) as client:
        r = client.post(f"/api/trabajos/{job['id']}/subir",
                        files=[("archivos", ("canva.zip", buf.getvalue(), "application/zip"))])
        assert r.status_code == 200, r.text
        det = client.get(f"/api/contenido/{job['id']}").json()
    job = db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))
    assert job["status"] == "listo"
    assert Image.open(d / "4x5" / "slide-01.png").size == (1080, 1350)
    assert Image.open(d / "9x16" / "slide-05.png").size == (1080, 1920)
    assert det["nativos"] == ["4x5"] and set(det["reexportados"]) == {"9x16", "1x1", "pdf"}
    assert det["costo_usd"] == job["cost_usd"] > 0  # conserva el costo del texto


def test_motor4_subida_pdf(orq, monkeypatch):
    monkeypatch.setattr(proveedores, "cliente_openai", lambda s: FakeOpenAI())
    job = _preparar(orq, "gpt_canva")
    pdf = config.DATA_DIR / "canva-test.pdf"
    imgs = [Image.new("RGB", (1080, 1350), c) for c in ("red", "green", "blue", "white", "black")]
    imgs[0].save(pdf, save_all=True, append_images=imgs[1:])
    orq.completar_manual(job["id"], [pdf])
    job = db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))
    assert job["status"] == "listo"
    d = config.OUTPUT_DIR / job["output_dir"]
    assert Image.open(d / "4x5" / "slide-03.png").convert("RGB").getpixel((500, 500))[2] > 200  # azul


def test_claude_canva_usa_claude(orq, monkeypatch):
    fake = FakeAnthropic()
    monkeypatch.setattr(proveedores, "cliente_anthropic", lambda s: fake)
    orq.encender("claude_canva", True)
    job = _preparar(orq, "claude_canva")
    assert job["status"] == "esperando_manual", job["error"]
    assert fake.pedidos and all(b["type"] == "text" for b in fake.pedidos[0]["messages"][0]["content"])
