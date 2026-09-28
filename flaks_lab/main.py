"""API local + frontend. Correr con:  python -m flaks_lab"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, stats, storage
from .engines.base import REGISTRO
from .orchestrator import orquestador

STATIC = Path(__file__).parent / "static"
SECRETOS = ("openai_api_key", "anthropic_api_key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    orquestador.iniciar(workers=not getattr(app.state, "sin_workers", False))
    yield
    orquestador.detener()


app = FastAPI(title="Flaks Content Lab", lifespan=lifespan)
config.ensure_dirs()
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/files", StaticFiles(directory=config.OUTPUT_DIR), name="files")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def _motor(motor_id: str):
    if motor_id not in REGISTRO:
        raise HTTPException(404, "Motor inexistente")
    return REGISTRO[motor_id]


# ------------------------------------------------------------------ dashboard
@app.get("/api/estado")
def estado(cliente: str | None = None):
    settings = db.get_settings()
    motores = [m for m in stats.ranking(cliente) if not m["eliminado"]]
    for m in motores:
        m["runtime"] = orquestador.runtime.get(m["id"], {})
        m["simulado"] = bool(settings["simulacion"].get(m["id"], True))
    f = " AND j.client = ?" if cliente and cliente != "todos" else ""
    params = [cliente] if f else []
    cola = db.query(f"""SELECT j.id, j.piece_id, j.engine, j.client, j.fecha, j.status, j.step, j.created_at,
                        j.started_at, j.error, j.simulated, j.output_dir FROM jobs j
                        WHERE j.status IN ('procesando', 'en_cola', 'esperando_manual'){f}
                        ORDER BY CASE j.status WHEN 'procesando' THEN 0 WHEN 'esperando_manual' THEN 1 ELSE 2 END,
                        j.fecha, j.id LIMIT 200""", params)
    recientes = db.query(f"""SELECT j.id, j.piece_id, j.engine, j.client, j.fecha, j.status, j.step, j.error,
                             j.finished_at, j.cost_usd FROM jobs j WHERE j.status IN ('listo', 'error'){f}
                             ORDER BY j.finished_at DESC LIMIT 8""", params)
    return {
        "clientes": settings["clientes"],
        "motores": motores,
        "progreso": stats.progreso(cliente),
        "fuentes": _fuentes(settings),
        "cola": cola,
        "recientes": recientes,
        "resumen": stats.resumen(cliente),
        "alertas": db.query("SELECT * FROM alerts WHERE dismissed = 0 ORDER BY id DESC LIMIT 5"),
    }


def _fuentes(settings: dict) -> list[dict]:
    from . import sheets

    guardadas = {r["client"]: r for r in db.query("SELECT * FROM sources")}
    out = []
    for c in settings["clientes"]:
        s = guardadas.get(c["id"], {})
        out.append({"cliente": c["id"], "nombre": c["nombre"], "pestana": c["pestana"], "activo": c.get("activo", True),
                    "estado": s.get("status") or "sin leer", "modo": s.get("mode") or
                    ("google" if sheets.hay_credenciales(settings) else "demo"),
                    "filas": s.get("rows"), "ultima": s.get("last_sync"), "error": s.get("error")})
    return out


@app.post("/api/sync")
def sync(payload: dict = Body(default={})):
    cliente = payload.get("cliente")
    return orquestador.sincronizar(None if cliente in (None, "", "todos") else cliente)


@app.post("/api/alertas/{alerta_id}/descartar")
def descartar_alerta(alerta_id: int):
    db.execute("UPDATE alerts SET dismissed = 1 WHERE id = ?", (alerta_id,))
    return {"ok": True}


# ------------------------------------------------------------------ motores
@app.get("/api/motores")
def motores(cliente: str | None = None):
    return {"ranking": stats.ranking(cliente), "costos_por_dia": stats.costos_por_dia(cliente)}


@app.post("/api/motores/{motor_id}/encender")
def encender(motor_id: str, payload: dict = Body(...)):
    _motor(motor_id)
    orquestador.encender(motor_id, bool(payload.get("encendido")))
    return {"ok": True}


@app.post("/api/motores/{motor_id}/pausar")
def pausar(motor_id: str, payload: dict = Body(...)):
    _motor(motor_id)
    orquestador.pausar(motor_id, bool(payload.get("pausado")))
    return {"ok": True}


@app.delete("/api/motores/{motor_id}")
def eliminar(motor_id: str):
    _motor(motor_id)
    return {"cancelados": orquestador.eliminar(motor_id)}


@app.post("/api/motores/{motor_id}/restaurar")
def restaurar(motor_id: str):
    _motor(motor_id)
    orquestador.restaurar(motor_id)
    return {"ok": True}


@app.post("/api/motores/{motor_id}/login")
def abrir_login(motor_id: str):
    """Abre el navegador del motor para iniciar sesión a mano (motores de navegador)."""
    cls = _motor(motor_id)
    motor = cls()
    if not hasattr(motor, "abrir_para_login"):
        raise HTTPException(400, "Este motor no usa navegador")
    import threading

    threading.Thread(target=motor.abrir_para_login, args=(db.get_settings(),), daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ trabajos
@app.post("/api/trabajos/{job_id}/cancelar")
def cancelar(job_id: int):
    orquestador.cancelar(job_id)
    return {"ok": True}


@app.post("/api/trabajos/{job_id}/reintentar")
def reintentar(job_id: int):
    return {"nuevo": orquestador.reintentar(job_id)}


@app.post("/api/trabajos/{job_id}/subir")
async def subir_manual(job_id: int, archivos: list[UploadFile] = File(default=[])):
    tmp = Path(tempfile.mkdtemp(prefix="flaks-subida-"))
    try:
        rutas: list[Path] = []
        for up in archivos:
            dest = tmp / Path(up.filename or "archivo").name
            dest.write_bytes(await up.read())
            if dest.suffix.lower() == ".zip":
                with zipfile.ZipFile(dest) as z:
                    for name in sorted(z.namelist()):
                        if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".pdf")) and "__MACOSX" not in name:
                            out = tmp / "zip" / Path(name).name
                            out.parent.mkdir(exist_ok=True)
                            out.write_bytes(z.read(name))
                            rutas.append(out)
            else:
                rutas.append(dest)
        try:
            orquestador.completar_manual(job_id, rutas)
        except (ValueError, Exception) as e:  # noqa: BLE001
            raise HTTPException(400, str(e)) from e
        return {"ok": True}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ contenido finalizado
TIPOS = {"carrusel": "4x5", "historia": "9x16", "reel": "9x16", "post": "1x1", "pdf": "pdf"}


def _items() -> list[dict]:
    jobs = {j["id"]: j for j in db.query("SELECT id, status, review FROM jobs")}
    items = []
    for m in storage.escanear():
        j = jobs.get(m.get("job_id"))
        m["estado_trabajo"] = j["status"] if j else m.get("estado")
        items.append(m)
    return items


@app.get("/api/contenido")
def contenido(tipo: str | None = None, motor: str | None = None, cliente: str | None = None,
              estado: str | None = None, q: str | None = None, desde: str | None = None, hasta: str | None = None):
    out = []
    for m in _items():
        ev = m.get("evaluacion", {})
        if tipo and TIPOS.get(tipo) not in (m.get("formatos") or {}):
            continue
        if motor and m.get("motor") != motor:
            continue
        if cliente and cliente != "todos" and m.get("cliente") != cliente:
            continue
        if estado:
            actual = "esperando_manual" if m.get("estado") == "esperando_manual" else ev.get("estado", "pendiente")
            if actual != estado:
                continue
        if desde and m.get("fecha", "") < desde:
            continue
        if hasta and m.get("fecha", "") > hasta:
            continue
        if q:
            texto = " ".join([m.get("pieza_id", ""), m.get("cliente_nombre", ""), m.get("motor_nombre", ""),
                              *m.get("slides_sheet", []), *[t.get("texto", "") for t in m.get("textos", [])
                                                           if isinstance(t, dict)]]).lower()
            if q.lower() not in texto:
                continue
        out.append(m)
    return {"items": out}


@app.get("/api/contenido/{job_id}")
def detalle(job_id: int):
    job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job or not job["output_dir"]:
        raise HTTPException(404, "No encontrado")
    meta = storage.leer_meta(config.OUTPUT_DIR / job["output_dir"])
    if not meta:
        raise HTTPException(404, "Sin meta.json")
    meta["_dir"] = job["output_dir"]
    return meta


@app.post("/api/contenido/{job_id}/evaluar")
def evaluar(job_id: int, payload: dict = Body(...)):
    try:
        orquestador.evaluar(job_id, diseno=payload.get("diseno"), texto=payload.get("texto"),
                            marca=payload.get("marca"), estado=payload.get("estado"), notas=payload.get("notas"),
                            instagram=payload.get("instagram"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return detalle(job_id)


# ------------------------------------------------------------------ historial
@app.get("/api/historial")
def historial(nivel: str | None = None, motor: str | None = None, limite: int = 300):
    cond, params = [], []
    if nivel:
        cond.append("level = ?")
        params.append(nivel)
    if motor:
        cond.append("engine = ?")
        params.append(motor)
    where = f"WHERE {' AND '.join(cond)}" if cond else ""
    logs = db.query(f"SELECT * FROM logs {where} ORDER BY id DESC LIMIT ?", [*params, min(limite, 2000)])
    corridas = db.query("SELECT * FROM runs ORDER BY id DESC LIMIT 50")
    trabajos = db.query("""SELECT id, piece_id, engine, client, fecha, status, attempts, created_at, started_at,
                           finished_at, duration_s, error, cost_usd, simulated, run_id FROM jobs
                           ORDER BY id DESC LIMIT 300""")
    return {"logs": logs, "corridas": corridas, "trabajos": trabajos}


# ------------------------------------------------------------------ configuración
def _enmascarar(s: dict) -> dict:
    s = copy.deepcopy(s)
    for k in SECRETOS:
        v = s["claves"].get(k) or ""
        s["claves"][k] = ("••••" + v[-4:]) if v else ""
    return s


@app.get("/api/config")
def get_config():
    s = db.get_settings()
    return {"settings": _enmascarar(s),
            "motores": [{"id": k, "nombre": c.nombre, "orden": c.orden} for k, c in
                        sorted(REGISTRO.items(), key=lambda kv: kv[1].orden)],
            "eliminados": [r["engine"] for r in db.query("SELECT engine FROM engine_state WHERE deleted = 1")]}


@app.put("/api/config")
def put_config(payload: dict = Body(...)):
    actual = db.get_settings()
    nuevo = payload.get("settings", payload)
    for k in SECRETOS:  # si viene enmascarada, conservar la guardada
        v = (nuevo.get("claves") or {}).get(k)
        if v is None or str(v).startswith("••••"):
            nuevo.setdefault("claves", {})[k] = actual["claves"].get(k, "")
    try:
        json.dumps(nuevo)
    except TypeError as e:
        raise HTTPException(400, f"Configuración inválida: {e}") from e
    return {"settings": _enmascarar(db.save_settings(nuevo))}
