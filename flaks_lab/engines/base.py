"""Interfaz común de los motores (plugins).

Para agregar un motor: crear un archivo en flaks_lab/engines/, heredar de Motor,
implementar generar(pieza, ctx) y decorar la clase con @registrar. Nada más.
"""
from __future__ import annotations

import random
import threading
import time
from pathlib import Path
from typing import Callable, ClassVar, TypeVar

from ..models import Pieza, Resultado, Uso

T = TypeVar("T")

REGISTRO: dict[str, type["Motor"]] = {}


def registrar(cls: type["Motor"]) -> type["Motor"]:
    REGISTRO[cls.id] = cls
    return cls


class MotorBloqueado(Exception):
    """Captcha, aviso de actividad inusual o límite de uso: se pausa el motor 24 h."""


class SesionRequerida(MotorBloqueado):
    """El sitio pide iniciar sesión: se pausa el motor hasta que el usuario inicie sesión y lo reanude."""


class ErrorConfiguracion(Exception):
    """Falta una clave, una plantilla o un login: no tiene sentido reintentar."""


class Interrumpido(Exception):
    """El motor se pausó/eliminó en medio de un trabajo: el trabajo vuelve a la cola."""


class ErrorReintentable(Exception):
    """Error transitorio (rate limit, 5xx, timeout)."""


class Contexto:
    """Todo lo que un motor necesita para trabajar, sin tocar el resto de la app."""

    def __init__(self, *, job_id: int, motor_id: str, pieza: Pieza, out_dir: Path, settings: dict,
                 plantilla, referencia: Path | None, simulado: bool,
                 log: Callable[[str, str], None], set_step: Callable[[str], None],
                 debe_parar: Callable[[], bool], stop_event: threading.Event | None = None):
        self.job_id = job_id
        self.motor_id = motor_id
        self.pieza = pieza
        self.out_dir = out_dir
        self.settings = settings
        self.plantilla = plantilla
        self.referencia = referencia
        self.simulado = simulado
        self._log = log
        self._set_step = set_step
        self._debe_parar = debe_parar
        self._stop = stop_event or threading.Event()

    # --- utilidades ---
    def log(self, msg: str, level: str = "info") -> None:
        self._log(msg, level)

    def paso(self, step: str) -> None:
        self._set_step(step)

    def dir_formato(self, formato: str) -> Path:
        d = self.out_dir / formato
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def escala_tiempo(self) -> float:
        return float(self.settings.get("simulacion_escala_tiempo", 0.01)) if self.simulado else 1.0

    def chequear(self) -> None:
        if self._stop.is_set() or self._debe_parar():
            raise Interrumpido("Motor pausado o detenido")

    def dormir(self, segundos: float) -> None:
        """Espera interrumpible (si pausás el motor, corta enseguida)."""
        fin = time.monotonic() + max(0.0, segundos) * self.escala_tiempo
        while True:
            self.chequear()
            resto = fin - time.monotonic()
            if resto <= 0:
                return
            self._stop.wait(min(resto, 0.5))

    def dormir_rango(self, rango: list | tuple) -> float:
        s = random.uniform(float(rango[0]), float(rango[1]))
        self.dormir(s)
        return s

    # --- ritmo para APIs: 1-3 s entre pedidos y reintentos con espera creciente ---
    def llamar_api(self, fn: Callable[[], T], descripcion: str = "pedido") -> T:
        lim = self.settings["limites"]
        self.dormir(random.uniform(lim["api_espera_min_s"], lim["api_espera_max_s"]))
        intentos = int(lim["api_reintentos"])
        base = float(lim["api_backoff_base_s"])
        for intento in range(1, intentos + 1):
            self.chequear()
            try:
                return fn()
            except ErrorReintentable as e:
                if intento == intentos:
                    raise
                espera = base ** intento + random.uniform(0, 1)
                self.log(f"{descripcion}: {e}. Reintento {intento}/{intentos - 1} en {espera:.0f} s", "warning")
                self.dormir(espera)
        raise RuntimeError("inalcanzable")


class Motor:
    """Clase base de un motor. Un motor = un plugin."""

    id: ClassVar[str] = ""
    nombre: ClassVar[str] = ""
    descripcion: ClassVar[str] = ""
    tipo: ClassVar[str] = "api"               # api | navegador | manual
    usa_referencia: ClassVar[str] = "ignora"  # imagen | estructura | ignora
    formatos_nativos: ClassVar[tuple[str, ...]] = ("4x5",)
    activo_por_defecto: ClassVar[bool] = True
    ritmo_humano: ClassVar[bool] = False      # True = aplica ritmo humano (franjas, tope diario...)
    orden: ClassVar[int] = 100

    def generar(self, pieza: Pieza, ctx: Contexto) -> Resultado:  # pragma: no cover - interfaz
        raise NotImplementedError

    # Motores semi-manuales: completan el trabajo con archivos que sube el usuario.
    def completar_manual(self, pieza: Pieza, ctx: Contexto, archivos: list[Path]) -> Resultado:
        raise ErrorConfiguracion("Este motor no acepta resultados manuales")

    # ---------- modo simulado ----------
    def uso_simulado(self, pieza: Pieza) -> list[Uso]:
        return []

    def simular(self, pieza: Pieza, ctx: Contexto) -> Resultado:
        """Genera placeholders con la marca del cliente, sin llamar a nada externo."""
        from .. import formats

        res = Resultado()
        n = len(pieza.slides)
        for fmt in self.formatos_nativos:
            if fmt == "pdf":
                continue
            ctx.paso(f"Generando {fmt}")
            paths = []
            for i, texto in enumerate(pieza.slides, 1):
                ctx.dormir(random.uniform(1, 4) if self.tipo != "navegador" else random.uniform(20, 60))
                p = ctx.dir_formato(fmt) / f"slide-{i:02d}.png"
                formats.placeholder_slide(texto, i, n, fmt, ctx.plantilla.brand, self.nombre).save(p)
                paths.append(p)
            res.archivos[fmt] = paths
        res.textos = [{"slide": i, "texto": t} for i, t in enumerate(pieza.slides, 1)]
        res.uso = self.uso_simulado(pieza)
        tasa = float(ctx.settings.get("simulacion_tasa_error", 0))
        if random.random() < tasa:
            raise RuntimeError("Error simulado (para probar reintentos y la tasa de error)")
        return res
