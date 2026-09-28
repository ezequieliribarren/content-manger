from flaks_lab import costs, formats, sheets
from flaks_lab.models import Pieza, Uso
from PIL import Image


def test_mapeo_columnas_con_encabezado_y_extra_slides():
    header = ["Fecha", "Contenido Slide 1", "Contenido Slide 2", "Referencia", "Qué tomar", "Contenido Slide 3"]
    cols = sheets.mapear_columnas(header)
    assert cols["slides"] == [1, 2, 5]
    assert cols["referencia"] == 3 and cols["que_tomar"] == 4


def test_filas_a_piezas_ignora_filas_vacias_y_parsea_fechas():
    valores = [["Fecha", "Contenido Slide 1", "Contenido Slide 2"],
               ["28/09/2026", "Hola", "Chau"], ["", "sin fecha"], ["2026-10-01", "", ""]]
    piezas = sheets.filas_a_piezas("flaks", valores)
    assert len(piezas) == 1
    p = piezas[0]
    assert p.fecha == "2026-09-28" and p.slides == ["Hola", "Chau"] and p.fila == 2
    assert p.id == "flaks-20260928-f002"


def test_hash_cambia_con_el_contenido():
    a = Pieza("flaks", "2026-09-28", ["x"], fila=2)
    b = Pieza("flaks", "2026-09-28", ["y"], fila=2)
    assert a.id == b.id and a.content_hash != b.content_hash


def test_costos_por_tokens_e_imagenes():
    precios = {"m": {"input_mtok": 1.0, "output_mtok": 10.0}, "img": {"por_imagen": 0.04}}
    c, ok = costs.costo_uso(Uso("x", "m", input_tokens=1_000_000, output_tokens=100_000), precios)
    assert ok and abs(c - 2.0) < 1e-9
    assert costs.costo_uso(Uso("x", "img", imagenes=3), precios)[0] == 0.12
    total, sin = costs.costo_total([Uso("x", "desconocido", input_tokens=5)], precios)
    assert total == 0 and sin == ["desconocido"]


def test_reexportar_formatos(tmp_path):
    src = tmp_path / "4x5"
    src.mkdir()
    slides = []
    for i in range(2):
        p = src / f"slide-{i + 1:02d}.png"
        formats.placeholder_slide("Hola", i + 1, 2, "4x5", {}, "test").save(p)
        slides.append(p)
    out = formats.reexportar(slides, tmp_path, ["9x16", "1x1", "pdf"])
    assert Image.open(out["9x16"][0]).size == (1080, 1920)
    assert Image.open(out["1x1"][1]).size == (1080, 1080)
    assert out["pdf"][0].read_bytes().startswith(b"%PDF")
