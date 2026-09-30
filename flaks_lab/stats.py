"""Métricas para el dashboard y el ranking de motores."""
from __future__ import annotations

from datetime import date

from . import db
from .engines.base import REGISTRO, motor_visible


def _filtro_cliente(cliente: str | None, alias: str = "") -> tuple[str, list]:
    if cliente and cliente != "todos":
        return f" AND {alias}client = ?", [cliente]
    return "", []


def ranking(cliente: str | None = None) -> list[dict]:
    f, params = _filtro_cliente(cliente)
    estados = {r["engine"]: r for r in db.query("SELECT * FROM engine_state")}
    ajustes = db.get_settings()
    filas = []
    for motor_id, cls in REGISTRO.items():
        st = estados.get(motor_id, {})
        r = db.one(f"""
            SELECT
              SUM(status = 'listo') AS listos,
              SUM(status = 'error') AS errores,
              SUM(status = 'en_cola') AS en_cola,
              SUM(status = 'procesando') AS procesando,
              SUM(status = 'esperando_manual') AS esperando,
              AVG(CASE WHEN status = 'listo' THEN duration_s END) AS tiempo_medio,
              COALESCE(SUM(cost_usd), 0) AS costo,
              COALESCE(SUM(CASE WHEN finished_at >= ? THEN cost_usd END), 0) AS costo_hoy,
              SUM(review = 'aprobado') AS aprobados,
              SUM(review = 'descartado') AS descartados,
              AVG((COALESCE(score_design, 0) + COALESCE(score_text, 0) + COALESCE(score_brand, 0)) * 1.0 /
                  NULLIF((score_design IS NOT NULL) + (score_text IS NOT NULL) + (score_brand IS NOT NULL), 0))
                  AS puntaje,
              AVG(score_design) AS p_diseno, AVG(score_text) AS p_texto, AVG(score_brand) AS p_marca,
              SUM(simulated) AS simulados
            FROM jobs WHERE engine = ?{f}""", [date.today().isoformat(), motor_id, *params]) or {}
        listos, errores = r.get("listos") or 0, r.get("errores") or 0
        aprobados = r.get("aprobados") or 0
        costo = r.get("costo") or 0.0
        filas.append({
            "id": motor_id, "nombre": cls.nombre, "descripcion": cls.descripcion, "tipo": cls.tipo,
            "orden": cls.orden, "usa_referencia": cls.usa_referencia, "ritmo_humano": cls.ritmo_humano,
            "formatos_nativos": list(cls.formatos_nativos),
            "encendido": bool(st.get("enabled")), "pausado": bool(st.get("paused")),
            "bloqueado_hasta": st.get("paused_until"), "motivo_pausa": st.get("pause_reason"),
            "eliminado": bool(st.get("deleted")),
            "oculto": not motor_visible(ajustes, motor_id),
            "hoy": st.get("day_count") or 0, "tope_hoy": st.get("day_cap"),
            "generadas": listos, "errores": errores,
            "tasa_error": errores / (listos + errores) if (listos + errores) else 0.0,
            "tiempo_medio_s": r.get("tiempo_medio"), "costo_usd": costo, "costo_hoy_usd": r.get("costo_hoy") or 0.0,
            "costo_por_pieza": costo / listos if listos else None,
            "aprobados": aprobados, "descartados": r.get("descartados") or 0,
            "costo_por_aprobado": costo / aprobados if aprobados else None,
            "puntaje": r.get("puntaje"), "p_diseno": r.get("p_diseno"), "p_texto": r.get("p_texto"),
            "p_marca": r.get("p_marca"),
            "en_cola": r.get("en_cola") or 0, "procesando": r.get("procesando") or 0,
            "esperando": r.get("esperando") or 0, "simulados": r.get("simulados") or 0,
        })
    filas.sort(key=lambda x: x["orden"])
    return filas


def costos_por_dia(cliente: str | None = None, dias: int = 30) -> list[dict]:
    f, params = _filtro_cliente(cliente)
    return db.query(f"""
        SELECT substr(finished_at, 1, 10) AS dia, engine, COUNT(*) AS piezas,
               ROUND(SUM(cost_usd), 6) AS costo, SUM(review = 'aprobado') AS aprobados
        FROM jobs WHERE finished_at IS NOT NULL AND status IN ('listo', 'esperando_manual'){f}
        GROUP BY dia, engine ORDER BY dia DESC, engine LIMIT ?""", [*params, dias * 10])


def progreso(cliente: str | None = None) -> dict | None:
    """Estado de la última corrida para la barra de progreso con pasos."""
    f = " WHERE client IN (?, 'todos')" if cliente and cliente != "todos" else ""
    run = db.one(f"SELECT * FROM runs{f} ORDER BY id DESC LIMIT 1", [cliente] if f else [])
    if not run:
        return None
    c = db.one("""SELECT COUNT(*) AS total, SUM(status = 'listo') AS listos, SUM(status = 'error') AS errores,
                  SUM(status = 'en_cola') AS en_cola, SUM(status = 'procesando') AS procesando,
                  SUM(status = 'esperando_manual') AS esperando, SUM(status = 'cancelado') AS cancelados,
                  SUM(review != 'pendiente' AND status = 'listo') AS revisados
                  FROM jobs WHERE run_id = ?""", (run["id"],)) or {}
    c = {k: v or 0 for k, v in c.items()}
    pendientes = c["en_cola"] + c["procesando"]
    if not run["finished_at"] and c["total"] and not pendientes:
        db.execute("UPDATE runs SET finished_at = ?, step = 'revisar' WHERE id = ?", (db.now(), run["id"]))
        run["finished_at"] = db.now()
    terminados = c["listos"] + c["errores"] + c["esperando"] + c["cancelados"]
    generar = "hecho" if c["total"] and not pendientes else ("activo" if c["total"] else "hecho")
    pasos = [
        {"id": "leer", "label": "Leer Google Sheets", "estado": "hecho"},
        {"id": "encolar", "label": "Encolar piezas", "estado": "hecho", "detalle": f"{c['total']} trabajos"},
        {"id": "generar", "label": "Generar", "estado": generar, "detalle": f"{terminados}/{c['total']}"},
        {"id": "exportar", "label": "Exportar formatos", "estado": generar,
         "detalle": f"{c['listos']} listos"},
        {"id": "revisar", "label": "Revisar", "estado": "activo" if generar == "hecho" and c["listos"] else "pendiente",
         "detalle": f"{c['revisados']}/{c['listos']}"},
    ]
    return {"run": run, "conteo": c, "pasos": pasos,
            "porcentaje": round(100 * terminados / c["total"]) if c["total"] else 100}


def resumen(cliente: str | None = None) -> dict:
    f, params = _filtro_cliente(cliente)
    hoy = date.today().isoformat()
    r = db.one(f"""SELECT COUNT(*) AS piezas, COALESCE(SUM(cost_usd), 0) AS costo,
                   SUM(review = 'aprobado') AS aprobados, SUM(review = 'pendiente' AND status = 'listo') AS por_revisar
                   FROM jobs WHERE status = 'listo'{f}""", params) or {}
    h = db.one(f"SELECT COALESCE(SUM(cost_usd), 0) AS c FROM jobs WHERE finished_at >= ?{f}", [hoy, *params]) or {}
    aprob = r.get("aprobados") or 0
    return {"piezas": r.get("piezas") or 0, "costo_usd": r.get("costo") or 0.0, "costo_hoy_usd": h.get("c") or 0.0,
            "aprobados": aprob, "por_revisar": r.get("por_revisar") or 0,
            "costo_por_aprobado": (r.get("costo") or 0) / aprob if aprob else None}
