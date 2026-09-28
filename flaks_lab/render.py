"""Plantilla HTML de marca (Jinja2) → PNG por formato y PDF para LinkedIn, con Playwright."""
from __future__ import annotations

import html
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .config import FORMATS


def _resaltar(texto: str) -> Markup:
    """*palabra* → <em>palabra</em> (el resto se escapa)."""
    seguro = html.escape(texto or "")
    return Markup(re.sub(r"\*(.+?)\*", r"<em>\1</em>", seguro))


def _env(carpeta: Path) -> Environment:
    env = Environment(loader=FileSystemLoader(str(carpeta)), autoescape=select_autoescape(["html"]))
    env.filters["resaltar"] = _resaltar
    return env


def html_slide(plantilla_html: Path, slide: dict, brand: dict, formato: str) -> str:
    spec = FORMATS[formato]
    tpl = _env(plantilla_html.parent).get_template(plantilla_html.name)
    return tpl.render(slide=slide, brand=brand, formato={"id": formato, "w": spec["w"], "h": spec["h"]})


def lanzar_chromium(p, **kwargs):
    """Chromium de Playwright; FLAKS_CHROMIUM permite apuntar a otro ejecutable."""
    exe = os.environ.get("FLAKS_CHROMIUM")
    if exe:
        kwargs["executable_path"] = exe
    return p.chromium.launch(**kwargs)


@contextmanager
def navegador() -> Iterator:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = lanzar_chromium(p)
        try:
            yield b
        finally:
            b.close()


def _cargar(page, contenido: str) -> None:
    page.set_content(contenido, wait_until="load")
    try:  # esperar tipografías web si hay conexión, sin trabarse si no la hay
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:  # noqa: BLE001
        pass
    page.evaluate("document.fonts && document.fonts.ready")


def renderizar(plantilla_html: Path, slides: list[dict], brand: dict, out_dir: Path,
               formatos: tuple[str, ...] = ("4x5", "9x16", "1x1", "pdf"), browser=None) -> dict[str, list[Path]]:
    """Renderiza cada slide en cada formato. Devuelve {formato: [rutas]}."""
    if browser is None:
        with navegador() as b:
            return renderizar(plantilla_html, slides, brand, out_dir, formatos, b)
    res: dict[str, list[Path]] = {}
    for fmt in formatos:
        if fmt == "pdf":
            continue
        spec = FORMATS[fmt]
        page = browser.new_page(viewport={"width": spec["w"], "height": spec["h"]}, device_scale_factor=1)
        d = out_dir / fmt
        d.mkdir(parents=True, exist_ok=True)
        paths = []
        for s in slides:
            _cargar(page, html_slide(plantilla_html, s, brand, fmt))
            p = d / f"slide-{s['numero']:02d}.png"
            page.screenshot(path=str(p), clip={"x": 0, "y": 0, "width": spec["w"], "height": spec["h"]})
            paths.append(p)
        page.close()
        res[fmt] = paths
    if "pdf" in formatos:
        res["pdf"] = [renderizar_pdf(plantilla_html, slides, brand, out_dir / "pdf" / "carrusel-linkedin.pdf", browser)]
    return res


def renderizar_pdf(plantilla_html: Path, slides: list[dict], brand: dict, dest: Path, browser) -> Path:
    """PDF vectorial (texto seleccionable) para LinkedIn: una página 4:5 por slide."""
    spec = FORMATS["4x5"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Cada slide en un iframe srcdoc para aislar estilos; una página por slide.
    frames = "".join(
        f'<div class="pg"><iframe srcdoc="{html.escape(html_slide(plantilla_html, s, brand, "4x5"), quote=True)}"></iframe></div>'
        for s in slides)
    doc = (f"<html><head><style>@page {{ size: {spec['w']}px {spec['h']}px; margin: 0 }}"
           f"html,body{{margin:0}} .pg{{width:{spec['w']}px;height:{spec['h']}px;page-break-after:always;overflow:hidden}}"
           f"iframe{{border:0;width:{spec['w']}px;height:{spec['h']}px}}</style></head><body>{frames}</body></html>")
    page = browser.new_page(viewport={"width": spec["w"], "height": spec["h"]})
    _cargar(page, doc)
    page.wait_for_timeout(300)
    page.pdf(path=str(dest), width=f"{spec['w']}px", height=f"{spec['h']}px", print_background=True,
             margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
    page.close()
    return dest
