import pytest
from fastapi.testclient import TestClient

from flaks_lab import config, db, sheets
from flaks_lab.main import app


@pytest.fixture()
def api(orq):
    app.state.sin_workers = True
    with TestClient(app) as c:
        yield c


def test_hoja_local_arranca_con_demo_y_se_edita(api, orq):
    h = api.get("/api/sheet/flaks").json()
    assert h["slides"] == 5 and len(h["filas"]) == 3
    assert h["filas"][0]["fecha"] == "2026-09-28"  # dd/mm/aaaa → ISO para el editor

    filas = [{"fecha": "2026-10-05", "slides": ["Hola", "Mundo", "", "", "", "Seis"], "referencia": "",
              "que_tomar": "Idea de contenido"},
             {"fecha": "", "slides": [""] * 6, "referencia": "", "que_tomar": ""}]  # fila vacía: se descarta
    assert api.put("/api/sheet/flaks", json={"slides": 6, "filas": filas}).json()["filas"] == 1
    assert config.LOCAL_SHEET.exists()

    valores, modo = sheets.leer_pestana(db.get_settings(), "Flaks")
    assert modo == "local" and valores[0][6] == "Contenido Slide 6"
    r = orq.sincronizar("flaks")
    assert r["piezas"] == 1
    pieza = db.one("SELECT * FROM pieces WHERE client = 'flaks'")
    assert pieza["fecha"] == "2026-10-05" and pieza["que_tomar"] == "Idea de contenido"


def test_fuente_google_sin_credenciales_da_error(orq):
    s = db.get_settings()
    s["fuente_sheets"] = "google"
    db.save_settings(s)
    r = orq.sincronizar("flaks")
    assert r["piezas"] == 0
    assert db.one("SELECT status FROM sources WHERE client = 'flaks'")["status"] == "error"


def test_motores_ocultos_no_reciben_trabajos(api, orq):
    s = db.get_settings()
    s["motores_visibles"] = ["gpt_web"]
    db.save_settings(s)
    r = orq.sincronizar("flaks")
    assert r["encolados"] == r["piezas"]  # solo ChatGPT web
    assert {j["engine"] for j in db.query("SELECT engine FROM jobs")} == {"gpt_web"}
    motores = api.get("/api/estado").json()["motores"]
    assert [m["id"] for m in motores] == ["gpt_web"]
    ocultos = [m["id"] for m in api.get("/api/config").json()["motores"] if m["oculto"]]
    assert "gemini_web" in ocultos and "gpt_web" not in ocultos
    # ocultar no borra: el estado del motor sigue en la base
    assert db.one("SELECT deleted FROM engine_state WHERE engine = 'gemini_web'")["deleted"] == 0


def test_subir_plantilla_y_referencia_por_fila(api, orq):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 50), "red").save(buf, "PNG")
    r = api.post("/api/sheet/flaks/imagen", files={"archivo": ("Mi Plantilla.png", buf.getvalue(), "image/png")})
    nombre = r.json()["nombre"]
    assert nombre.startswith("mi-plantilla-") and nombre.endswith(".png")
    assert api.get(f"/api/sheet/flaks/imagen/{nombre}").status_code == 200
    assert api.get("/api/sheet/flaks/imagen/..%2F..%2Fdata%2Flab.db").status_code == 404
    assert api.post("/api/sheet/flaks/imagen", files={"archivo": ("x.txt", b"hola", "text/plain")}).status_code == 400

    filas = [{"fecha": "2026-10-06", "slides": ["Uno", "Dos"], "referencia": nombre, "que_tomar": "Estilo visual",
              "plantilla": nombre}]
    api.put("/api/sheet/flaks", json={"slides": 2, "filas": filas})
    assert api.get("/api/sheet/flaks").json()["filas"][0]["plantilla"] == nombre
    orq.sincronizar("flaks")
    pieza = db.one("SELECT * FROM pieces WHERE client = 'flaks'")
    assert pieza["plantilla"] == nombre

    from flaks_lab.engines.base import REGISTRO
    from flaks_lab.models import Pieza
    job = db.one("SELECT * FROM jobs WHERE engine = 'gpt_web'")
    ctx = orq._contexto(job, REGISTRO["gpt_web"](), Pieza.from_row(pieza), config.OUTPUT_DIR, db.get_settings(),
                        True, None)
    assert ctx.plantilla.imagen.name == nombre  # la plantilla de la fila reemplaza a la del cliente


def test_regenerar_misma_idea_y_sin_tope_diario(api, orq):
    filas = [{"fecha": "2026-10-07", "slides": ["Una sola slide"], "referencia": "", "que_tomar": "", "plantilla": ""}]
    api.put("/api/sheet/flaks", json={"slides": 1, "filas": filas})
    s = db.get_settings()
    s["motores_visibles"] = ["gpt_web"]
    s["ritmo_humano"]["tope_diario"] = [0, 0]
    db.save_settings(s)

    r = api.post("/api/sheet/flaks/generar", json={"fila": 2}).json()
    assert r["encolados"] == 1  # primera vez
    r = api.post("/api/sheet/flaks/generar", json={"fila": 2}).json()
    assert r["encolados"] == 0 and r["en_curso"] == 1  # ya está en la cola: no duplica
    db.execute("UPDATE jobs SET status = 'listo', finished_at = ? WHERE engine = 'gpt_web'", (db.now(),))
    r = api.post("/api/sheet/flaks/generar", json={"fila": 2}).json()
    assert r["encolados"] == 1  # ya generada: se puede volver a generar
    assert api.post("/api/sheet/flaks/generar", json={"fila": 9}).status_code == 400

    from flaks_lab.engines.base import REGISTRO
    st = {**orq.estado_motor("gpt_web"), "day": None}
    db.execute("UPDATE engine_state SET day_count = 500 WHERE engine = 'gpt_web'")
    st = {**orq.estado_motor("gpt_web"), "day": __import__("datetime").date.today().isoformat(), "day_count": 500}
    assert orq._puede_trabajar(REGISTRO["gpt_web"], st, db.get_settings(), True) is None
