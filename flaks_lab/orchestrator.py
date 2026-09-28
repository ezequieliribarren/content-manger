"""Orquestador: lee el Sheet, encola piezas en cada motor encendido y corre una cola por motor."""
from __future__ import annotations

import importlib
import pkgutil
import random
import shutil
import threading
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, costs, db, formats, plantillas, sheets, storage
from .engines import base
from .engines.base import REGISTRO, Contexto, ErrorConfiguracion, Interrumpido, Motor, MotorBloqueado
from .models import Pieza, Resultado, Uso

ACTIVOS = ("en_cola", "procesando")


def cargar_plugins() -> dict[str, type[Motor]]:
    from . import engines

    for mod in pkgutil.iter_modules(engines.__path__):
        if mod.name != "base" and not mod.name.startswith("_"):
            importlib.import_module(f"{engines.__name__}.{mod.name}")
    return REGISTRO


def en_franja(franjas: list[str], ahora: datetime | None = None) -> bool:
    ahora = ahora or datetime.now()
    hm = ahora.strftime("%H:%M")
    for f in franjas:
        ini, fin = [x.strip() for x in f.split("-")]
        if ini <= hm < fin:
            return True
    return False


def proxima_franja(franjas: list[str], ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now()
    hm = ahora.strftime("%H:%M")
    inicios = sorted(f.split("-")[0].strip() for f in franjas)
    for ini in inicios:
        if ini > hm:
            return f"hoy {ini}"
    return f"mañana {inicios[0]}" if inicios else "-"


class Orquestador:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        self._cancelados: set[int] = set()
        self._sync_lock = threading.Lock()
        self.runtime: dict[str, dict] = {}   # estado en vivo de cada motor (descansando, fuera de franja...)

    # ------------------------------------------------------------------ ciclo de vida
    def iniciar(self, workers: bool = True) -> None:
        config.ensure_dirs()
        db.init()
        cargar_plugins()
        self._asegurar_estados()
        # Trabajos que quedaron a medias si la app se cerró: vuelven a la cola.
        db.execute("UPDATE jobs SET status = 'en_cola', step = NULL WHERE status = 'procesando'")
        if workers:
            for motor_id in REGISTRO:
                self._lanzar_worker(motor_id)
            t = threading.Thread(target=self._auto_sync, name="auto-sync", daemon=True)
            t.start()

    def detener(self) -> None:
        self._stop.set()
        for t in self._threads.values():
            t.join(timeout=5)

    def _lanzar_worker(self, motor_id: str) -> None:
        if motor_id in self._threads and self._threads[motor_id].is_alive():
            return
        t = threading.Thread(target=self._worker, args=(motor_id,), name=f"motor-{motor_id}", daemon=True)
        self._threads[motor_id] = t
        t.start()

    def _asegurar_estados(self) -> None:
        for motor_id, cls in REGISTRO.items():
            if not db.one("SELECT engine FROM engine_state WHERE engine = ?", (motor_id,)):
                db.execute("INSERT INTO engine_state (engine, enabled) VALUES (?, ?)",
                           (motor_id, int(cls.activo_por_defecto)))

    # ------------------------------------------------------------------ motores
    def estado_motor(self, motor_id: str) -> dict | None:
        return db.one("SELECT * FROM engine_state WHERE engine = ?", (motor_id,))

    def encender(self, motor_id: str, encendido: bool) -> None:
        db.execute("UPDATE engine_state SET enabled = ? WHERE engine = ?", (int(encendido), motor_id))
        db.log(f"Motor {'encendido' if encendido else 'apagado'}", engine=motor_id)

    def pausar(self, motor_id: str, pausado: bool) -> None:
        if pausado:
            db.execute("UPDATE engine_state SET paused = 1 WHERE engine = ?", (motor_id,))
        else:
            db.execute("UPDATE engine_state SET paused = 0, paused_until = NULL, pause_reason = NULL "
                       "WHERE engine = ?", (motor_id,))
        db.log("Motor pausado" if pausado else "Motor reanudado", engine=motor_id)

    def eliminar(self, motor_id: str) -> int:
        """Saca el motor del laboratorio y vacía su cola. El historial y los archivos quedan."""
        db.execute("UPDATE engine_state SET deleted = 1, enabled = 0 WHERE engine = ?", (motor_id,))
        n = db.execute("UPDATE jobs SET status = 'cancelado', step = 'Motor eliminado' "
                       "WHERE engine = ? AND status = 'en_cola'", (motor_id,))
        for j in db.query("SELECT id FROM jobs WHERE engine = ? AND status = 'procesando'", (motor_id,)):
            self._cancelados.add(j["id"])
        db.log(f"Motor eliminado ({n} trabajos cancelados)", "warning", engine=motor_id)
        return n

    def restaurar(self, motor_id: str) -> None:
        db.execute("UPDATE engine_state SET deleted = 0, enabled = 0 WHERE engine = ?", (motor_id,))
        db.log("Motor restaurado (apagado)", engine=motor_id)

    def bloquear(self, motor_id: str, motivo: str, horas: float) -> None:
        hasta = (datetime.now() + timedelta(hours=horas)).isoformat(timespec="seconds")
        db.execute("UPDATE engine_state SET paused_until = ?, pause_reason = ? WHERE engine = ?",
                   (hasta, motivo, motor_id))
        db.alert(f"{REGISTRO[motor_id].nombre} pausado {horas:g} h: {motivo}", engine=motor_id)
        _notificar_escritorio("Flaks Content Lab", f"{REGISTRO[motor_id].nombre} pausado: {motivo}")

    # ------------------------------------------------------------------ Google Sheets
    def sincronizar(self, cliente: str | None = None, trigger: str = "manual") -> dict:
        """Lee el Sheet, guarda las piezas y las encola en cada motor encendido."""
        with self._sync_lock:
            settings = db.get_settings()
            clientes = [c for c in settings["clientes"] if c.get("activo", True)
                        and (cliente is None or c["id"] == cliente)]
            run_id = db.execute("INSERT INTO runs (started_at, trigger, client, step) VALUES (?, ?, ?, ?)",
                                (db.now(), trigger, cliente or "todos", "leer_sheets"))
            db.log(f"Corrida #{run_id} iniciada ({trigger})", run_id=run_id)
            total_piezas, encolados = 0, 0
            for c in clientes:
                try:
                    valores, modo = sheets.leer_pestana(settings, c["pestana"])
                    piezas = sheets.filas_a_piezas(c["id"], valores, settings["limites"]["solo_fechas_desde_hoy"])
                    self._guardar_fuente(c, "ok", modo, len(piezas), None)
                except Exception as e:  # noqa: BLE001 - se muestra en la UI
                    self._guardar_fuente(c, "error", None, 0, str(e))
                    db.log(f"Error leyendo la pestaña '{c['pestana']}': {e}", "error", run_id=run_id)
                    continue
                for p in piezas:
                    self._guardar_pieza(p)
                    encolados += self.encolar(p, run_id=run_id)
                total_piezas += len(piezas)
            resumen = f"{total_piezas} piezas leídas, {encolados} trabajos encolados"
            db.execute("UPDATE runs SET step = ?, summary = ? WHERE id = ?",
                       ("generar" if encolados else "listo", resumen, run_id))
            if not encolados:
                db.execute("UPDATE runs SET finished_at = ? WHERE id = ?", (db.now(), run_id))
            db.log(f"Corrida #{run_id}: {resumen}", run_id=run_id)
            return {"run_id": run_id, "piezas": total_piezas, "encolados": encolados}

    def _guardar_fuente(self, c: dict, status: str, modo: str | None, filas: int, error: str | None) -> None:
        db.execute(
            "INSERT INTO sources (client, tab, status, mode, rows, last_sync, error) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(client) DO UPDATE SET tab=excluded.tab, status=excluded.status, mode=excluded.mode, "
            "rows=excluded.rows, last_sync=excluded.last_sync, error=excluded.error",
            (c["id"], c["pestana"], status, modo, filas, db.now(), error))

    def _guardar_pieza(self, p: Pieza) -> None:
        import json

        db.execute(
            "INSERT INTO pieces (id, client, fecha, fila, slides, referencia, que_tomar, content_hash, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "slides=excluded.slides, referencia=excluded.referencia, que_tomar=excluded.que_tomar, "
            "content_hash=excluded.content_hash, updated_at=excluded.updated_at, fecha=excluded.fecha",
            (p.id, p.cliente, p.fecha, p.fila, json.dumps(p.slides, ensure_ascii=False), p.referencia,
             p.que_tomar, p.content_hash, db.now(), db.now()))

    def encolar(self, p: Pieza, motores: list[str] | None = None, run_id: int | None = None,
                forzar: bool = False) -> int:
        """Encola la pieza en cada motor encendido que todavía no la tenga (misma versión de contenido)."""
        n = 0
        for st in db.query("SELECT * FROM engine_state WHERE deleted = 0"):
            motor_id = st["engine"]
            if motor_id not in REGISTRO or (motores and motor_id not in motores):
                continue
            if not motores and not st["enabled"]:
                continue
            if not forzar and db.one(
                    "SELECT id FROM jobs WHERE piece_id = ? AND engine = ? AND content_hash = ? "
                    "AND status NOT IN ('error', 'cancelado')", (p.id, motor_id, p.content_hash)):
                continue
            db.execute("INSERT INTO jobs (piece_id, engine, client, fecha, content_hash, status, run_id, created_at) "
                       "VALUES (?, ?, ?, ?, ?, 'en_cola', ?, ?)",
                       (p.id, motor_id, p.cliente, p.fecha, p.content_hash, run_id, db.now()))
            n += 1
        return n

    def _auto_sync(self) -> None:
        ultimo = datetime.now()
        while not self._stop.wait(30):
            minutos = db.get_settings()["limites"].get("sync_automatico_min") or 0
            if minutos and datetime.now() - ultimo >= timedelta(minutes=minutos):
                ultimo = datetime.now()
                try:
                    self.sincronizar(trigger="automático")
                except Exception as e:  # noqa: BLE001
                    db.log(f"Sincronización automática falló: {e}", "error")

    # ------------------------------------------------------------------ trabajos
    def cancelar(self, job_id: int) -> None:
        job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not job:
            return
        if job["status"] == "procesando":
            self._cancelados.add(job_id)
        elif job["status"] in ("en_cola", "esperando_manual"):
            db.update_job(job_id, status="cancelado", step="Cancelado")
        db.log("Trabajo cancelado", engine=job["engine"], job_id=job_id)

    def reintentar(self, job_id: int) -> int | None:
        job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not job:
            return None
        return db.execute("INSERT INTO jobs (piece_id, engine, client, fecha, content_hash, status, run_id, "
                          "created_at) VALUES (?, ?, ?, ?, ?, 'en_cola', ?, ?)",
                          (job["piece_id"], job["engine"], job["client"], job["fecha"], job["content_hash"],
                           job["run_id"], db.now()))

    def _reclamar(self, motor_id: str) -> dict | None:
        with db.conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE engine = ? AND status = 'en_cola' ORDER BY fecha, id LIMIT 1",
                            (motor_id,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE jobs SET status = 'procesando', started_at = ?, attempts = attempts + 1, "
                      "step = 'Iniciando' WHERE id = ?", (db.now(), row["id"]))
            return dict(row)

    # ------------------------------------------------------------------ límites
    def _costo_real_hoy(self) -> float:
        row = db.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM jobs WHERE simulated = 0 AND finished_at >= ?",
                     (date.today().isoformat(),))
        return float(row["c"]) if row else 0.0

    def _hechos_hoy(self, motor_id: str) -> int:
        row = db.one("SELECT COUNT(*) AS n FROM jobs WHERE engine = ? AND status IN ('listo', 'esperando_manual') "
                     "AND finished_at >= ?", (motor_id, date.today().isoformat()))
        return int(row["n"]) if row else 0

    def _puede_trabajar(self, motor: type[Motor], st: dict, settings: dict, simulado: bool) -> str | None:
        """None si puede tomar un trabajo; si no, el motivo (se muestra en la tarjeta del motor)."""
        lim = settings["limites"]
        if motor.ritmo_humano:
            ritmo = settings["ritmo_humano"]
            hoy = date.today().isoformat()
            if st.get("day") != hoy:
                cap = random.randint(*[int(x) for x in ritmo["tope_diario"]])
                db.execute("UPDATE engine_state SET day = ?, day_count = 0, day_cap = ? WHERE engine = ?",
                           (hoy, cap, motor.id))
                st = {**st, "day": hoy, "day_count": 0, "day_cap": cap}
            if st["day_count"] >= (st["day_cap"] or 0):
                return f"Tope diario alcanzado ({st['day_count']}/{st['day_cap']})"
            if not simulado and not en_franja(ritmo["franjas"]):
                return f"Fuera de franja horaria · próxima {proxima_franja(ritmo['franjas'])}"
        else:
            tope = int(lim.get("max_piezas_dia_por_motor") or 0)
            if tope and self._hechos_hoy(motor.id) >= tope:
                return f"Límite diario de piezas alcanzado ({tope})"
        if not simulado and motor.tipo == "api":
            presupuesto = float(lim.get("presupuesto_diario_usd") or 0)
            if presupuesto and self._costo_real_hoy() >= presupuesto:
                return f"Presupuesto diario agotado (USD {presupuesto:.2f})"
        return None

    # ------------------------------------------------------------------ worker por motor
    def _worker(self, motor_id: str) -> None:
        cls = REGISTRO[motor_id]
        while not self._stop.is_set():
            st = self.estado_motor(motor_id)
            if not st or st["deleted"] or not st["enabled"]:
                self.runtime[motor_id] = {"estado": "apagado"}
                self._stop.wait(1.5)
                continue
            if st["paused_until"]:
                if st["paused_until"] > db.now():
                    self.runtime[motor_id] = {"estado": "bloqueado", "detalle": st["pause_reason"],
                                              "hasta": st["paused_until"]}
                    self._stop.wait(5)
                    continue
                db.execute("UPDATE engine_state SET paused_until = NULL, pause_reason = NULL WHERE engine = ?",
                           (motor_id,))
                db.log("Terminó la pausa por bloqueo: el motor vuelve a trabajar", engine=motor_id)
            if st["paused"]:
                self.runtime[motor_id] = {"estado": "pausado"}
                self._stop.wait(1.5)
                continue
            settings = db.get_settings()
            simulado = bool(settings["simulacion"].get(motor_id, True))
            motivo = self._puede_trabajar(cls, st, settings, simulado)
            if motivo:
                self.runtime[motor_id] = {"estado": "esperando", "detalle": motivo}
                self._stop.wait(10)
                continue
            job = self._reclamar(motor_id)
            if not job:
                self.runtime[motor_id] = {"estado": "inactivo"}
                self._stop.wait(2)
                continue
            self.runtime[motor_id] = {"estado": "trabajando", "job": job["id"]}
            ok = self.ejecutar(job, cls(), settings, simulado)
            if ok and cls.ritmo_humano:
                self._pausa_humana(cls, settings, simulado)

    def _debe_parar(self, motor_id: str, job_id: int) -> bool:
        if self._stop.is_set() or job_id in self._cancelados:
            return True
        st = self.estado_motor(motor_id)
        return bool(not st or st["deleted"] or not st["enabled"] or st["paused"])

    def _pausa_humana(self, cls: type[Motor], settings: dict, simulado: bool) -> None:
        ritmo = settings["ritmo_humano"]
        st = self.estado_motor(cls.id) or {}
        cada = st.get("break_every") or random.randint(*[int(x) for x in ritmo["descanso_cada_n"]])
        desde = (st.get("since_break") or 0) + 1
        if desde >= cada:
            minutos = random.uniform(*ritmo["descanso_min"])
            desde, cada = 0, random.randint(*[int(x) for x in ritmo["descanso_cada_n"]])
            etiqueta = "Descanso largo"
        else:
            minutos = random.uniform(*ritmo["pausa_entre_carruseles_min"])
            etiqueta = "Pausa entre carruseles"
        db.execute("UPDATE engine_state SET day_count = day_count + 1, since_break = ?, break_every = ? "
                   "WHERE engine = ?", (desde, cada, cls.id))
        escala = float(settings.get("simulacion_escala_tiempo", 0.01)) if simulado else 1.0
        segundos = minutos * 60 * escala
        hasta = (datetime.now() + timedelta(seconds=segundos)).isoformat(timespec="seconds")
        self.runtime[cls.id] = {"estado": "descansando", "detalle": f"{etiqueta} ({minutos:.0f} min)", "hasta": hasta}
        fin = datetime.now() + timedelta(seconds=segundos)
        while datetime.now() < fin and not self._stop.is_set():
            st = self.estado_motor(cls.id)
            if not st or st["deleted"] or not st["enabled"] or st["paused"]:
                return
            self._stop.wait(min(1.0, max(0.0, (fin - datetime.now()).total_seconds())))

    def _contexto(self, job: dict, motor: Motor, pieza: Pieza, out_dir: Path, settings: dict,
                  simulado: bool, referencia: Path | None) -> Contexto:
        job_id, motor_id = job["id"], motor.id
        return Contexto(
            job_id=job_id, motor_id=motor_id, pieza=pieza, out_dir=out_dir, settings=settings,
            plantilla=plantillas.cargar(pieza.cliente), referencia=referencia, simulado=simulado,
            log=lambda m, lvl="info": db.log(m, lvl, engine=motor_id, job_id=job_id, run_id=job.get("run_id")),
            set_step=lambda s: db.update_job(job_id, step=s),
            debe_parar=lambda: self._debe_parar(motor_id, job_id), stop_event=self._stop)

    def ejecutar(self, job: dict, motor: Motor, settings: dict, simulado: bool) -> bool:
        """Corre un trabajo completo. Devuelve True si el motor generó algo (listo o esperando manual)."""
        job_id = job["id"]
        piece = db.one("SELECT * FROM pieces WHERE id = ?", (job["piece_id"],))
        if not piece:
            db.update_job(job_id, status="error", error="La pieza ya no existe", finished_at=db.now())
            return False
        pieza = Pieza.from_row(piece)
        out_dir = storage.carpeta_pieza(pieza.cliente, pieza.fecha, motor.id, pieza.id)
        referencia = None
        if motor.usa_referencia != "ignora" and pieza.referencia:
            try:
                referencia = plantillas.resolver_referencia(pieza.cliente, pieza.referencia, settings)
            except Exception as e:  # noqa: BLE001
                db.log(f"Referencia no disponible ({e}); sigo sin referencia", "warning",
                       engine=motor.id, job_id=job_id)
        ctx = self._contexto(job, motor, pieza, out_dir, settings, simulado, referencia)
        db.update_job(job_id, simulated=int(simulado), output_dir=storage.rel(out_dir))
        db.log(f"Generando {pieza.id} ({len(pieza.slides)} slides){' [simulado]' if simulado else ''}",
               engine=motor.id, job_id=job_id, run_id=job.get("run_id"))
        t0 = datetime.now()
        try:
            res = motor.simular(pieza, ctx) if simulado else motor.generar(pieza, ctx)
            if res.esperando_manual:
                self._esperar_manual(job, motor, pieza, res, out_dir, settings, simulado, t0)
            else:
                self._finalizar(job, motor, pieza, res, out_dir, settings, simulado, t0)
            return True
        except Interrumpido:
            shutil.rmtree(out_dir, ignore_errors=True)
            if job_id in self._cancelados:
                self._cancelados.discard(job_id)
                db.update_job(job_id, status="cancelado", step="Cancelado", finished_at=db.now())
            else:
                db.update_job(job_id, status="en_cola", step="Interrumpido: vuelve a la cola",
                              attempts=max(0, (job.get("attempts") or 0)))
            return False
        except MotorBloqueado as e:
            shutil.rmtree(out_dir, ignore_errors=True)
            db.update_job(job_id, status="en_cola", step="Motor bloqueado: reintenta tras la pausa")
            self.bloquear(motor.id, str(e), float(settings["ritmo_humano"].get("pausa_bloqueo_horas", 24)))
            return False
        except Exception as e:  # noqa: BLE001 - cualquier error queda registrado en el historial
            shutil.rmtree(out_dir, ignore_errors=True)
            dur = (datetime.now() - t0).total_seconds()
            detalle = "" if isinstance(e, ErrorConfiguracion) else "\n" + traceback.format_exc(limit=4)
            db.update_job(job_id, status="error", error=str(e), finished_at=db.now(), duration_s=dur,
                          step="Error", output_dir=None)
            db.log(f"Error: {e}{detalle}", "error", engine=motor.id, job_id=job_id, run_id=job.get("run_id"))
            return False

    def _meta_base(self, job: dict, motor: Motor, pieza: Pieza, settings: dict, simulado: bool) -> dict:
        return {
            "job_id": job["id"], "pieza_id": pieza.id, "cliente": pieza.cliente,
            "cliente_nombre": next((c["nombre"] for c in settings["clientes"] if c["id"] == pieza.cliente),
                                   pieza.cliente),
            "fecha": pieza.fecha, "motor": motor.id, "motor_nombre": motor.nombre, "simulado": simulado,
            "fila_sheet": pieza.fila, "slides_sheet": pieza.slides, "referencia": pieza.referencia,
            "que_tomar": pieza.que_tomar, "creado": db.now(),
            "evaluacion": {"estado": "pendiente", "diseno": None, "texto": None, "marca": None, "notas": ""},
            "instagram": {k: None for k in storage.IG_CAMPOS},
        }

    def _esperar_manual(self, job, motor, pieza, res: Resultado, out_dir, settings, simulado, t0) -> None:
        usos = [u.to_dict() for u in res.uso]
        costo, _ = costs.costo_total(usos, settings["precios"])
        meta = self._meta_base(job, motor, pieza, settings, simulado)
        meta.update({"estado": "esperando_manual", "textos": res.textos, "uso": usos, "costo_usd": costo,
                     "formatos": {}, "notas": res.notas, "extra": _serializable(res.extra)})
        storage.escribir_meta(out_dir, meta)
        db.update_job(job["id"], status="esperando_manual", step=res.notas or "Esperando resultado manual",
                      usage=usos, cost_usd=costo, finished_at=db.now(),
                      duration_s=(datetime.now() - t0).total_seconds())
        db.log(f"Listo para el paso manual: {res.notas}", engine=motor.id, job_id=job["id"])

    def completar_manual(self, job_id: int, archivos: list[Path]) -> None:
        job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not job or job["status"] != "esperando_manual":
            raise ValueError("El trabajo no está esperando un resultado manual")
        cls = REGISTRO[job["engine"]]
        motor = cls()
        settings = db.get_settings()
        pieza = Pieza.from_row(db.one("SELECT * FROM pieces WHERE id = ?", (job["piece_id"],)))
        out_dir = config.OUTPUT_DIR / job["output_dir"]
        ctx = self._contexto(job, motor, pieza, out_dir, settings, bool(job["simulated"]), None)
        res = motor.completar_manual(pieza, ctx, archivos)
        previo = storage.leer_meta(out_dir) or {}
        res.textos = res.textos or previo.get("textos", [])
        import json as _json
        usos_previos = _json.loads(job["usage"]) if job["usage"] else []
        res.uso = [Uso(**u) for u in usos_previos] + res.uso
        t0 = datetime.now() - timedelta(seconds=job["duration_s"] or 0)
        self._finalizar(job, motor, pieza, res, out_dir, settings, bool(job["simulated"]), t0)

    def _finalizar(self, job, motor: Motor, pieza: Pieza, res: Resultado, out_dir: Path, settings: dict,
                   simulado: bool, t0: datetime) -> None:
        db.update_job(job["id"], step="Exportando formatos")
        if not res.archivos.get("4x5"):
            raise RuntimeError("El motor no devolvió slides 4:5")
        faltantes = [f for f in config.FORMATS if f not in res.archivos]
        res.archivos.update(formats.reexportar(res.archivos["4x5"], out_dir, faltantes))
        reel = formats.exportar_reel(res.archivos.get("9x16", []), out_dir / "9x16" / "reel.mp4")
        usos = [u.to_dict() for u in res.uso]
        costo, sin_precio = costs.costo_total(usos, settings["precios"])
        if sin_precio:
            db.log(f"Sin precio cargado para: {', '.join(sin_precio)} (costo 0)", "warning",
                   engine=motor.id, job_id=job["id"])
        dur = (datetime.now() - t0).total_seconds()
        formatos = {f: [storage.rel(p) for p in ps] for f, ps in res.archivos.items()}
        meta = self._meta_base(job, motor, pieza, settings, simulado)
        meta.update({
            "estado": "listo", "formatos": formatos, "nativos": [f for f in motor.formatos_nativos],
            "reexportados": faltantes, "reel_mp4": storage.rel(reel) if reel else None,
            "textos": res.textos, "uso": usos, "costo_usd": costo, "duracion_s": round(dur, 1),
            "notas": res.notas, "extra": _serializable(res.extra),
        })
        storage.escribir_meta(out_dir, meta)
        db.update_job(job["id"], status="listo", step="Listo", finished_at=db.now(), duration_s=dur,
                      cost_usd=costo, usage=usos, formats=list(formatos), output_dir=storage.rel(out_dir))
        db.log(f"Listo en {dur:.0f} s · USD {costo:.4f}", engine=motor.id, job_id=job["id"],
               run_id=job.get("run_id"))

    # ------------------------------------------------------------------ evaluación
    def evaluar(self, job_id: int, *, diseno=None, texto=None, marca=None, estado=None, notas=None,
                instagram: dict | None = None) -> dict:
        job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not job:
            raise ValueError("Trabajo inexistente")
        cambios: dict = {}
        ev: dict = {}
        for campo, col, val in (("diseno", "score_design", diseno), ("texto", "score_text", texto),
                                ("marca", "score_brand", marca)):
            if val is not None:
                v = int(val)
                if not 1 <= v <= 5:
                    raise ValueError("El puntaje va de 1 a 5")
                cambios[col] = v
                ev[campo] = v
        if estado is not None:
            if estado not in ("pendiente", "aprobado", "descartado"):
                raise ValueError("Estado inválido")
            cambios["review"] = estado
            ev["estado"] = estado
        if notas is not None:
            ev["notas"] = notas
        if instagram:
            import json as _json
            actual = _json.loads(job["ig_metrics"]) if job["ig_metrics"] else {}
            actual.update({k: v for k, v in instagram.items() if k in storage.IG_CAMPOS})
            cambios["ig_metrics"] = actual
        if cambios:
            db.update_job(job_id, **cambios)
        if job["output_dir"]:
            upd = {"evaluacion": ev} if ev else {}
            if instagram:
                upd["instagram"] = cambios["ig_metrics"]
            storage.actualizar_meta(config.OUTPUT_DIR / job["output_dir"], **upd)
        return db.one("SELECT * FROM jobs WHERE id = ?", (job_id,)) or {}


def _serializable(d: dict) -> dict:
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in (d or {}).items()}


def _notificar_escritorio(titulo: str, mensaje: str) -> None:
    """Aviso del sistema operativo si está disponible (además del aviso en el dashboard)."""
    import platform
    import subprocess

    try:
        so = platform.system()
        if so == "Darwin":
            subprocess.run(["osascript", "-e", f'display notification "{mensaje}" with title "{titulo}"'],
                           timeout=5, check=False)
        elif so == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", titulo, mensaje], timeout=5, check=False)
        elif so == "Windows":
            ps = ("[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
                  "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Warning;"
                  f"$n.Visible=$true;$n.ShowBalloonTip(10000,'{titulo}','{mensaje}',"
                  "[System.Windows.Forms.ToolTipIcon]::Warning)")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=10, check=False)
    except Exception:  # noqa: BLE001 - el aviso del dashboard alcanza
        pass


orquestador = Orquestador()
