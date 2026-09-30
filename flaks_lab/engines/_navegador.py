"""Base para motores que automatizan un chat web (Gemini, ChatGPT) con la sesión del usuario.

- Perfil de navegador persistente y visible en data/navegador/{motor}/ (iniciás sesión una vez con el botón
  "Sesión" del dashboard).
- Ritmo humano: espera al cargar, escritura letra por letra, pausa entre prompts (las pausas entre carruseles,
  descansos, tope diario y franjas los maneja el orquestador).
- Captcha, aviso de actividad inusual o límite de uso → MotorBloqueado (el orquestador pausa el motor 24 h y avisa).
- Los selectores CSS se editan en Configuración → Selectores web.
"""
from __future__ import annotations

import base64
import os
import random
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .. import config, formats, plantillas
from ..models import Pieza, Resultado, Uso
from .base import Contexto, Interrumpido, Motor, MotorBloqueado, SesionRequerida
from .gpt_imagen import prompt_slide

FRASES_BLOQUEO = [
    r"unusual (traffic|activity)", r"actividad inusual", r"tr[aá]fico inusual", r"captcha", r"not a robot",
    r"no soy un robot", r"reached (your|the) (usage |daily )?limit", r"(alcanzaste|has alcanzado|llegaste) (el|al) l[ií]mite",
    r"l[ií]mite de (uso|im[aá]genes|generaci)", r"usage limit", r"try again (later|tomorrow)",
    r"vuelve a intentarlo (m[aá]s tarde|ma[nñ]ana)", r"volv[eé] a intentarlo (m[aá]s tarde|ma[nñ]ana)",
    r"too many requests", r"demasiadas solicitudes",
]

_locks: dict[str, threading.Lock] = {}


def _lock(motor_id: str) -> threading.Lock:
    return _locks.setdefault(motor_id, threading.Lock())


_ventanas_login: dict[str, subprocess.Popen] = {}


def cerrar_ventana_login(motor_id: str) -> bool:
    """Cierra (como si tocaras la X) la ventana de Sesión del motor, si sigue abierta."""
    proc = _ventanas_login.get(motor_id)
    if not proc or proc.poll() is not None:
        return False
    if os.name == "nt":  # sin /F: Chrome cierra normal y guarda la sesión
        subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    return True


def chrome_instalado() -> str | None:
    """Ruta de Google Chrome en Windows, macOS o Linux (None si no está)."""
    candidatos = [Path(os.environ.get(v, "")) / "Google/Chrome/Application/chrome.exe"
                  for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(v)]
    candidatos.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for c in candidatos:
        if c.is_file():
            return str(c)
    return shutil.which("google-chrome") or shutil.which("chrome")


class MotorNavegador(Motor):
    tipo = "navegador"
    usa_referencia = "imagen"
    formatos_nativos = ("4x5",)
    ritmo_humano = True
    proveedor = "web"
    modelo_costo = "web"        # nombre en la tabla de precios (0 por defecto: es tu suscripción)
    timeout_respuesta_s = 360

    # ------------------------------------------------------------------ navegador
    def _selectores(self, settings: dict) -> dict:
        return settings["selectores"][self.id]

    def _abrir_contexto(self, p, settings: dict):
        perfil = config.BROWSER_PROFILES_DIR / self.id
        perfil.mkdir(parents=True, exist_ok=True)
        kwargs = dict(user_data_dir=str(perfil), headless=os.environ.get("FLAKS_HEADLESS") == "1",
                      viewport=None, accept_downloads=True, args=["--start-maximized"],
                      locale="es-AR")
        canal = settings.get("navegador_canal") or ""
        exe = os.environ.get("FLAKS_CHROMIUM")
        if canal:
            try:
                return p.chromium.launch_persistent_context(channel=canal, **kwargs)
            except Exception:  # noqa: BLE001 - si no está Chrome instalado, usar el Chromium de Playwright
                pass
        if exe:
            kwargs["executable_path"] = exe
        return p.chromium.launch_persistent_context(**kwargs)

    def abrir_para_login(self, settings: dict, espera_max_s: int = 900) -> None:
        """Abre el navegador del motor para que inicies sesión a mano. Se cierra cuando cerrás la ventana.

        Si está Google Chrome, lo abre como un Chrome normal (sin automatización) sobre el perfil del motor:
        Google bloquea el login en navegadores automatizados ("este navegador no es seguro").
        """
        chrome = chrome_instalado() if (settings.get("navegador_canal") or "") == "chrome" else None
        if chrome:
            perfil = config.BROWSER_PROFILES_DIR / self.id
            perfil.mkdir(parents=True, exist_ok=True)
            with _lock(self.id):
                proc = subprocess.Popen([chrome, f"--user-data-dir={perfil}", "--no-first-run",
                                         "--no-default-browser-check", self._selectores(settings)["url"]])
                _ventanas_login[self.id] = proc
                try:
                    proc.wait(timeout=espera_max_s)
                except subprocess.TimeoutExpired:
                    proc.terminate()
            return
        from playwright.sync_api import sync_playwright

        with _lock(self.id), sync_playwright() as p:
            ctx = self._abrir_contexto(p, settings)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(self._selectores(settings)["url"])
            cerrado = threading.Event()
            ctx.on("close", lambda *_: cerrado.set())
            page.on("close", lambda *_: cerrado.set() if not ctx.pages else None)
            fin = time.monotonic() + espera_max_s
            while not cerrado.is_set() and time.monotonic() < fin:
                try:
                    page.wait_for_timeout(1000)
                except Exception:  # noqa: BLE001 - la ventana se cerró
                    break
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ detección
    def detectar_bloqueo(self, page, settings: dict) -> str | None:
        url = page.url.lower()
        if "/sorry/" in url or "captcha" in url:
            return "Captcha (página de verificación)"
        if page.locator("iframe[src*='recaptcha'], iframe[src*='captcha'], iframe[title*='captcha' i]").count():
            return "Captcha detectado"
        textos = []
        for sel in ("[role='dialog']", "[role='alert']", "[role='alertdialog']"):
            loc = page.locator(sel)
            for i in range(min(loc.count(), 5)):
                try:
                    textos.append(loc.nth(i).inner_text(timeout=1000))
                except Exception:  # noqa: BLE001
                    pass
        resp = self._selectores(settings).get("respuesta_lista")
        if resp:
            loc = page.locator(resp)
            if loc.count():
                try:
                    textos.append(loc.last.inner_text(timeout=1000))
                except Exception:  # noqa: BLE001
                    pass
        frases = settings.get("frases_bloqueo") or FRASES_BLOQUEO
        for t in textos:
            for f in frases:
                if re.search(f, t, re.I):
                    return f"Aviso del sitio: “{t.strip()[:160]}”"
        return None

    def _sesion_iniciada(self, page, settings: dict) -> bool:
        sel = self._selectores(settings)
        if "accounts.google.com" in page.url or "/auth/login" in page.url:
            return False
        if sel.get("login") and page.locator(sel["login"]).count():
            return False
        return page.locator(sel["prompt"]).count() > 0

    def _chequear(self, page, ctx: Contexto) -> None:
        ctx.chequear()
        motivo = self.detectar_bloqueo(page, ctx.settings)
        if motivo:
            raise MotorBloqueado(motivo)

    # ------------------------------------------------------------------ acciones "humanas"
    def escribir(self, page, texto: str, ctx: Contexto) -> None:
        sel = self._selectores(ctx.settings)
        caja = page.locator(sel["prompt"]).first
        caja.click()
        ctx.dormir(random.uniform(0.3, 1.2))
        rango = ctx.settings["ritmo_humano"]["escritura_ms_por_letra"]
        for n, ch in enumerate(texto):
            if ch == "\n":
                page.keyboard.press("Shift+Enter")
            else:
                page.keyboard.type(ch)
            demora = random.uniform(float(rango[0]), float(rango[1])) / 1000
            if demora:
                time.sleep(demora)
            if n % 40 == 0:
                ctx.chequear()

    def enviar(self, page, ctx: Contexto) -> None:
        sel = self._selectores(ctx.settings)
        boton = page.locator(sel["enviar"]).first if sel.get("enviar") else None
        if boton is not None and boton.count() and boton.is_enabled():
            boton.click()
        else:
            page.keyboard.press("Enter")

    def adjuntar(self, page, archivos: list[Path], ctx: Contexto) -> None:
        sel = self._selectores(ctx.settings)
        archivos = [str(a) for a in archivos if a]
        if not archivos:
            return
        entrada = page.locator(sel["input_archivo"])
        if entrada.count():
            entrada.first.set_input_files(archivos)
        else:
            if not sel.get("subir_menu"):
                raise RuntimeError("No encuentro cómo adjuntar archivos: revisá los selectores web")
            with page.expect_file_chooser(timeout=15000) as fc:
                page.locator(sel["subir_menu"]).first.click()
                item = sel.get("subir_item")
                if item and page.locator(item).count():
                    page.locator(item).first.click()
            fc.value.set_files(archivos)
        ctx.dormir(random.uniform(2, 4))

    def esperar_imagen(self, page, antes: int, ctx: Contexto) -> object:
        sel = self._selectores(ctx.settings)["imagen_respuesta"]
        fin = time.monotonic() + self.timeout_respuesta_s
        visto = None  # src de la última imagen completa: se acepta cuando no cambia entre dos chequeos
        while time.monotonic() < fin:
            self._chequear(page, ctx)
            imgs = page.locator(sel)
            if imgs.count() > antes:
                ultima = imgs.nth(imgs.count() - 1)
                try:
                    ultima.wait_for(state="attached", timeout=5000)
                    src = ultima.get_attribute("src") or ""
                    if page.evaluate("(el) => el.complete && el.naturalWidth > 0", ultima.element_handle()):
                        if src and src == visto:
                            return ultima
                        visto = src
                    else:
                        visto = None
                except Exception:  # noqa: BLE001 - todavía cargando
                    visto = None
            ctx.dormir(3)
        raise RuntimeError("El sitio no devolvió una imagen a tiempo")

    def descargar_imagen(self, page, img, dest: Path) -> None:
        src = img.get_attribute("src") or ""
        datos: bytes | None = None
        if src.startswith("data:"):
            datos = base64.b64decode(src.split(",", 1)[1])
        elif src.startswith("blob:"):
            b64 = page.evaluate("""async (src) => { const r = await fetch(src); const b = await r.blob();
                return await new Promise(ok => { const f = new FileReader();
                  f.onload = () => ok(f.result.split(',')[1]); f.readAsDataURL(b); }); }""", src)
            datos = base64.b64decode(b64)
        elif src.startswith("http"):
            try:
                r = page.context.request.get(src, timeout=60000)
                if r.ok:
                    datos = r.body()
            except Exception:  # noqa: BLE001
                datos = None
        if datos:
            dest.write_bytes(datos)
        else:  # último recurso: captura de la imagen en pantalla
            img.screenshot(path=str(dest))

    # ------------------------------------------------------------------ generación
    def prompt_inicial(self, pieza: Pieza, ctx: Contexto) -> str:
        brand = ctx.plantilla.brand
        ref = ""
        if ctx.referencia:
            ref = (f" La segunda imagen adjunta es una referencia: tomá de ella solo {pieza.que_tomar or 'el estilo visual'}, "
                   "sin copiar su texto ni su marca.")
        return (f"Vamos a crear un carrusel de {len(pieza.slides)} slides para la marca {brand.get('nombre')}. "
                f"La primera imagen adjunta es la plantilla de marca: respetá sus colores, tipografías y estilo.{ref} "
                "Te voy a pedir cada slide por separado; generá una sola imagen vertical 4:5 por pedido.")

    def _guardar_diagnostico(self, page, ctx: Contexto) -> None:
        """Ante un error guarda captura + HTML de la página y el último texto del asistente (para ajustar selectores)."""
        try:
            carpeta = config.DATA_DIR / "diagnostico" / self.id
            carpeta.mkdir(parents=True, exist_ok=True)
            base = carpeta / f"trabajo-{ctx.job_id}-{time.strftime('%Y%m%d-%H%M%S')}"
            page.screenshot(path=str(base.with_suffix(".png")))
            base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
            texto = ""
            resp = self._selectores(ctx.settings).get("respuesta_lista")
            if resp and page.locator(resp).count():
                texto = page.locator(resp).last.inner_text(timeout=2000)[:600]
            ctx.log(f"Diagnóstico guardado en {base.relative_to(config.ROOT)}.png/.html · URL {page.url}"
                    + (f" · Última respuesta: “{texto.strip()}”" if texto.strip() else " · Sin respuesta de texto"),
                    "warning")
        except Exception as e:  # noqa: BLE001 - el diagnóstico nunca debe tapar el error original
            ctx.log(f"No pude guardar el diagnóstico: {e}", "warning")

    @contextmanager
    def _perfil_libre(self, ctx: Contexto):
        """El perfil no se puede abrir dos veces: si la ventana de Sesión sigue abierta, espera (y lo muestra)."""
        lock = _lock(self.id)
        if not lock.acquire(blocking=False):
            ctx.paso("Esperando que cierres la ventana de Sesión")
            while not lock.acquire(timeout=2):
                ctx.chequear()
        try:
            yield
        finally:
            lock.release()

    def generar(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        from playwright.sync_api import sync_playwright

        ritmo = ctx.settings["ritmo_humano"]
        plantilla_img = plantillas.imagen_plantilla(ctx.plantilla, "4x5")
        sel = self._selectores(ctx.settings)
        paths: list[Path] = []
        with self._perfil_libre(ctx), sync_playwright() as p:
            navegador = self._abrir_contexto(p, ctx.settings)
            page = None
            try:
                page = navegador.pages[0] if navegador.pages else navegador.new_page()
                ctx.paso("Abriendo el sitio")
                page.goto(sel["url"], wait_until="domcontentloaded")
                ctx.dormir_rango(ritmo["espera_carga_s"])
                try:  # dar tiempo a que cargue la caja del prompt
                    page.locator(sel["prompt"]).first.wait_for(state="visible", timeout=20000)
                except Exception:  # noqa: BLE001 - se evalúa abajo (login o bloqueo)
                    pass
                self._chequear(page, ctx)
                if not self._sesion_iniciada(page, ctx.settings):
                    raise SesionRequerida(f"{self.nombre}: no hay sesión iniciada. Tocá “Sesión” en la tarjeta del "
                                          "motor, iniciá sesión en esa ventana y cerrala (el motor sigue solo). "
                                          "No inicies sesión en la ventana que abre el motor: Google la rechaza.")
                n = len(pieza.slides)
                for i, texto in enumerate(pieza.slides, 1):
                    ctx.paso(f"Slide {i}/{n}: escribiendo prompt")
                    prompt = prompt_slide(pieza, i, texto, "4x5", ctx.plantilla.brand, bool(ctx.referencia))
                    if i == 1:
                        self.adjuntar(page, [plantilla_img, ctx.referencia], ctx)
                        prompt = self.prompt_inicial(pieza, ctx) + "\n\n" + prompt
                    prompt = "Generá una imagen. " + prompt
                    antes = page.locator(sel["imagen_respuesta"]).count()
                    self.escribir(page, prompt, ctx)
                    ctx.dormir(random.uniform(0.5, 1.5))
                    self.enviar(page, ctx)
                    ctx.paso(f"Slide {i}/{n}: esperando la imagen")
                    img = self.esperar_imagen(page, antes, ctx)
                    dest = ctx.dir_formato("4x5") / f"slide-{i:02d}.png"
                    self.descargar_imagen(page, img, dest)
                    formats.normalizar(dest, "4x5")
                    paths.append(dest)
                    if i < n:
                        ctx.paso(f"Pausa entre prompts ({i}/{n} listos)")
                        ctx.dormir_rango(ritmo["pausa_entre_prompts_s"])
            except (SesionRequerida, Interrumpido):
                raise
            except Exception:
                if page is not None:
                    self._guardar_diagnostico(page, ctx)
                raise
            finally:
                try:
                    navegador.close()
                except Exception:  # noqa: BLE001
                    pass
        return Resultado(archivos={"4x5": paths},
                         uso=[Uso(self.proveedor, self.modelo_costo, imagenes=len(paths))],
                         textos=[{"slide": i, "texto": t} for i, t in enumerate(pieza.slides, 1)])
