"""Motores de API con clientes falsos (no se llama a ninguna API real)."""
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from flaks_lab import config, db, proveedores
from flaks_lab.engines.base import ErrorReintentable, REGISTRO
from flaks_lab.models import Pieza

from conftest import CHROMIUM

necesita_chromium = pytest.mark.skipif(not CHROMIUM and not __import__("shutil").which("chromium"),
                                       reason="Chromium de Playwright no disponible")


def _texto_modelo(n):
    return {"slides": [{"numero": i, "tipo": "contenido", "etiqueta": "", "titulo": f"Título *{i}*",
                        "texto": "Texto de apoyo", "cta": "Escribinos" if i == n else ""} for i in range(1, n + 1)],
            "caption": "Caption de prueba", "hashtags": ["marketing", "flaks"]}


class FakeOpenAI:
    def __init__(self):
        self.pedidos = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.pedidos.append(kw)
        n = int(kw["input"][0]["content"][0]["text"].split("Cantidad de slides: ")[1].split("\n")[0])
        return SimpleNamespace(status="completed", output_text=json.dumps(_texto_modelo(n)),
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=400))


def _real(motor_id):
    s = db.get_settings()
    s["simulacion"][motor_id] = False
    db.save_settings(s)
    return s


def _correr(orq, motor_id, cliente="flaks"):
    orq.sincronizar(cliente=cliente)
    job = orq._reclamar(motor_id)
    orq.ejecutar(job, REGISTRO[motor_id](), db.get_settings(), False)
    return db.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))


@necesita_chromium
def test_motor1_gpt_html(orq, monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(proveedores, "cliente_openai", lambda s: fake)
    _real("gpt_html")
    job = _correr(orq, "gpt_html")
    assert job["status"] == "listo", job["error"]
    d = config.OUTPUT_DIR / job["output_dir"]
    assert Image.open(d / "4x5" / "slide-01.png").size == (1080, 1350)
    assert Image.open(d / "9x16" / "slide-05.png").size == (1080, 1920)
    assert Image.open(d / "1x1" / "slide-01.png").size == (1080, 1080)
    assert (d / "pdf" / "carrusel-linkedin.pdf").read_bytes().startswith(b"%PDF")
    meta = json.loads((d / "meta.json").read_text())
    assert meta["reexportados"] == []
    assert meta["uso"][0]["input_tokens"] == 1200
    # 1200 tokens in x 0.75/M + 400 out x 4.50/M
    assert abs(meta["costo_usd"] - (1200 * 0.75 + 400 * 4.5) / 1e6) < 1e-9
    pedido = fake.pedidos[0]
    assert pedido["text"]["format"]["type"] == "json_schema"
    assert "Slide 1: 5 errores" in pedido["input"][0]["content"][0]["text"]


def test_motor1_referencia_se_manda_como_imagen(orq, monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(proveedores, "cliente_openai", lambda s: fake)
    monkeypatch.setattr("flaks_lab.engines.gpt_html.renderizar_plantilla",
                        lambda datos, ctx, formatos=None: {"4x5": _placeholders(ctx, len(datos["slides"]))})
    _real("gpt_html")
    orq.sincronizar(cliente="flaks")
    job = db.one("SELECT * FROM jobs WHERE engine = 'gpt_html' AND piece_id LIKE '%f003'")
    db.execute("UPDATE jobs SET status = 'cancelado' WHERE engine = 'gpt_html' AND id != ?", (job["id"],))
    job = orq._reclamar("gpt_html")
    orq.ejecutar(job, REGISTRO["gpt_html"](), db.get_settings(), False)
    contenido = fake.pedidos[0]["input"][0]["content"]
    assert contenido[1]["type"] == "input_image" and contenido[1]["image_url"].startswith("data:image/png;base64,")
    assert "Estructura de slides" in contenido[0]["text"]


def _placeholders(ctx, n):
    from flaks_lab import formats

    out = []
    for i in range(1, n + 1):
        p = ctx.dir_formato("4x5") / f"slide-{i:02d}.png"
        formats.placeholder_slide("x", i, n, "4x5", {}, "t").save(p)
        out.append(p)
    return out


def test_falta_clave_es_error_de_configuracion(orq, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _real("gpt_html")
    job = _correr(orq, "gpt_html")
    assert job["status"] == "error" and "OPENAI_API_KEY" in job["error"]


def test_reintentos_con_espera_creciente(orq):
    from flaks_lab.engines.base import Contexto
    from flaks_lab import plantillas

    s = db.get_settings()
    s["limites"]["api_backoff_base_s"] = 0
    llamadas = []

    def fn():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise ErrorReintentable("429")
        return "ok"

    ctx = Contexto(job_id=0, motor_id="gpt_html", pieza=Pieza("flaks", "2026-01-01", ["a"]), out_dir=config.OUTPUT_DIR,
                   settings=s, plantilla=plantillas.cargar("flaks"), referencia=None, simulado=False,
                   log=lambda m, l="info": None, set_step=lambda x: None, debe_parar=lambda: False)
    assert ctx.llamar_api(fn) == "ok" and len(llamadas) == 3


class FakeAnthropic:
    def __init__(self, stop_reason="end_turn"):
        self.pedidos = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.pedidos.append(kw)
        texto = next(b["text"] for b in kw["messages"][0]["content"] if b["type"] == "text")
        n = int(texto.split("Cantidad de slides: ")[1].split("\n")[0])
        return SimpleNamespace(
            stop_reason=self.stop_reason, stop_details=None, model=kw["model"],
            content=[SimpleNamespace(type="text", text=json.dumps(_texto_modelo(n)))],
            usage=SimpleNamespace(input_tokens=1500, output_tokens=600, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0))


@necesita_chromium
def test_motor2_claude_html(orq, monkeypatch):
    fake = FakeAnthropic()
    monkeypatch.setattr(proveedores, "cliente_anthropic", lambda s: fake)
    _real("claude_html")
    job = _correr(orq, "claude_html")
    assert job["status"] == "listo", job["error"]
    d = config.OUTPUT_DIR / job["output_dir"]
    for fmt, size in (("4x5", (1080, 1350)), ("9x16", (1080, 1920)), ("1x1", (1080, 1080))):
        assert Image.open(d / fmt / "slide-01.png").size == size
    meta = json.loads((d / "meta.json").read_text())
    assert abs(meta["costo_usd"] - (1500 * 4 + 600 * 20) / 1e6) < 1e-9
    kw = fake.pedidos[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default"


def test_motor2_rechazo_queda_como_error(orq, monkeypatch):
    monkeypatch.setattr(proveedores, "cliente_anthropic", lambda s: FakeAnthropic("refusal"))
    _real("claude_html")
    job = _correr(orq, "claude_html")
    assert job["status"] == "error" and "declinó" in job["error"]


class FakeImagenes:
    def __init__(self):
        self.pedidos = []
        self.images = SimpleNamespace(edit=self._edit)

    def _edit(self, **kw):
        import base64
        import io

        self.pedidos.append({**kw, "image": [f.name for f in kw["image"]]})
        w, h = map(int, kw["size"].split("x"))
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "#191035").save(buf, "PNG")
        usage = SimpleNamespace(input_tokens=1500, output_tokens=4000,
                                input_tokens_details=SimpleNamespace(image_tokens=1200, text_tokens=300))
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(buf.getvalue()).decode())], usage=usage)


@necesita_chromium
def test_motor3_gpt_imagen(orq, monkeypatch):
    fake = FakeImagenes()
    monkeypatch.setattr(proveedores, "cliente_openai", lambda s: fake)
    _real("gpt_imagen")
    job = _correr(orq, "gpt_imagen")
    assert job["status"] == "listo", job["error"]
    d = config.OUTPUT_DIR / job["output_dir"]
    for fmt, size in (("4x5", (1080, 1350)), ("9x16", (1080, 1920)), ("1x1", (1080, 1080))):
        assert Image.open(d / fmt / "slide-05.png").size == size
    assert (d / "pdf" / "carrusel-linkedin.pdf").exists()
    assert len(fake.pedidos) == 15  # 5 slides x 3 formatos
    p = fake.pedidos[0]
    assert p["image"][0].endswith("slide-01.png")  # plantilla generada desde el HTML
    assert "5 errores que frenan tu marketing" in p["prompt"]
    meta = json.loads((d / "meta.json").read_text())
    u = meta["uso"][0]
    assert u["imagenes"] == 15 and u["image_input_tokens"] == 15 * 1200 and u["input_tokens"] == 15 * 300
    esperado = (15 * 300 * 5.0 + 15 * 1200 * 8.0 + 15 * 4000 * 30.0) / 1e6
    assert abs(meta["costo_usd"] - esperado) < 1e-9


def test_motor3_solo_4x5_reexporta_el_resto(orq, monkeypatch):
    fake = FakeImagenes()
    monkeypatch.setattr(proveedores, "cliente_openai", lambda s: fake)
    s = _real("gpt_imagen")
    s["motor3_formatos"] = ["4x5"]
    db.save_settings(s)
    (config.TEMPLATES_DIR / "flaks" / "plantilla.png").write_bytes(
        (config.REFERENCES_DIR / "flaks" / "ejemplo-carrusel.png").read_bytes())
    try:
        job = _correr(orq, "gpt_imagen")
    finally:
        (config.TEMPLATES_DIR / "flaks" / "plantilla.png").unlink()
    assert job["status"] == "listo", job["error"]
    assert len(fake.pedidos) == 5
    assert fake.pedidos[0]["image"][0].endswith("plantilla.png")
    meta = json.loads((config.OUTPUT_DIR / job["output_dir"] / "meta.json").read_text())
    assert set(meta["reexportados"]) == {"9x16", "1x1"}
