"""Formatos de salida: reexportar desde 4:5 a 9:16, 1:1 y PDF, y placeholders del modo simulado."""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import FORMATS, IMAGE_FORMATS


def _hex(color: str, fallback: str = "#191035") -> tuple[int, int, int]:
    c = (color or fallback).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return _hex(fallback)


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("Archivo-Bold.ttf", "Inter-Bold.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def placeholder_slide(texto: str, idx: int, total: int, fmt: str, brand: dict, motor: str) -> Image.Image:
    spec = FORMATS[fmt]
    w, h = spec["w"], spec["h"]
    bg = _hex(brand.get("colores", {}).get("fondo", "#191035"))
    accent = _hex(brand.get("colores", {}).get("acento", "#00FE5E"))
    fg = _hex(brand.get("colores", {}).get("texto", "#FFFFFF"))
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 18], fill=accent)
    d.text((72, 80), f"{brand.get('nombre', '')}  ·  {idx}/{total}", font=_font(34), fill=accent)
    lines = textwrap.wrap(texto, width=22)[:9]
    y = h // 2 - len(lines) * 42
    for line in lines:
        d.text((72, y), line, font=_font(64), fill=fg)
        y += 84
    d.text((72, h - 110), f"SIMULADO · {motor} · {fmt}", font=_font(28), fill=accent)
    return img


def _fit_on_canvas(src: Image.Image, w: int, h: int) -> Image.Image:
    """Centra la imagen 4:5 en el lienzo destino con un fondo desenfocado de la misma imagen."""
    src = src.convert("RGB")
    bg = ImageOps.fit(src, (w, h)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), 0.25)
    fg = ImageOps.contain(src, (w, h))
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


def reexportar(slides_4x5: list[Path], piece_dir: Path, faltantes: list[str]) -> dict[str, list[Path]]:
    """Genera los formatos faltantes a partir de los slides 4:5."""
    out: dict[str, list[Path]] = {}
    for fmt in faltantes:
        if fmt == "pdf":
            out["pdf"] = [exportar_pdf(slides_4x5, piece_dir / "pdf" / "carrusel-linkedin.pdf")]
            continue
        if fmt not in IMAGE_FORMATS or fmt == "4x5":
            continue
        spec = FORMATS[fmt]
        d = piece_dir / fmt
        d.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, src in enumerate(slides_4x5, 1):
            with Image.open(src) as im:
                dst = d / f"slide-{i:02d}.png"
                _fit_on_canvas(im, spec["w"], spec["h"]).save(dst)
                paths.append(dst)
        out[fmt] = paths
    return out


def normalizar(path: Path, fmt: str) -> None:
    """Lleva una imagen al tamaño exacto del formato (recorte centrado)."""
    spec = FORMATS[fmt]
    with Image.open(path) as im:
        fitted = ImageOps.fit(im.convert("RGB"), (spec["w"], spec["h"]), method=Image.Resampling.LANCZOS)
    fitted.save(path)


def exportar_pdf(slides: list[Path], dest: Path) -> Path:
    import img2pdf

    dest.parent.mkdir(parents=True, exist_ok=True)
    rgb = []
    for p in slides:
        with Image.open(p) as im:
            if im.mode != "RGB":
                tmp = p.with_suffix(".rgb.jpg")
                im.convert("RGB").save(tmp, quality=95)
                rgb.append(tmp)
            else:
                rgb.append(p)
    dest.write_bytes(img2pdf.convert([str(p) for p in rgb]))
    for p in rgb:
        if p.name.endswith(".rgb.jpg"):
            p.unlink(missing_ok=True)
    return dest


def exportar_reel(slides_9x16: list[Path], dest: Path, segundos_por_slide: float = 3.0) -> Path | None:
    """MP4 simple del reel si hay ffmpeg instalado. Si no, el reel son las imágenes 9:16."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not slides_9x16:
        return None
    lista = dest.with_suffix(".txt")
    lines = []
    for p in slides_9x16:
        lines += [f"file '{p.resolve().as_posix()}'", f"duration {segundos_por_slide}"]
    lines.append(f"file '{slides_9x16[-1].resolve().as_posix()}'")
    lista.write_text("\n".join(lines))
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
           "-vf", "fps=30,format=yuv420p", str(dest)]
    try:
        subprocess.run(cmd, check=True, timeout=120)
        return dest
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        lista.unlink(missing_ok=True)
