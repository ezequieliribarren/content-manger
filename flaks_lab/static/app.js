/* Flaks Content Lab · frontend sin build (vanilla JS) */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const app = $("#app");

const S = {
  cliente: localStorage.getItem("cliente") || "todos",
  filtros: { q: "", tipo: "", motor: "", cliente: "", estado: "", desde: "", hasta: "" },
  orden: { col: "puntaje", dir: -1 },
  timer: null,
  cfgSeccion: "claves",
};

// ---------------------------------------------------------------- utilidades
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) } };
  if (opts.body && !(opts.body instanceof FormData)) init.body = JSON.stringify(opts.body);
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Error ${r.status}`);
  return data;
}
function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (error ? " error" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 3500);
}
const usd = (v, d = 4) => (v == null ? "—" : "US$ " + Number(v).toFixed(v >= 1 ? 2 : d));
const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + " %");
const seg = (v) => (v == null ? "—" : v >= 90 ? (v / 60).toFixed(1) + " min" : Math.round(v) + " s");
const nota = (v) => (v == null ? "—" : Number(v).toFixed(2));
const fecha = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) : "—");
const ESTADOS = {
  en_cola: "En cola", procesando: "Procesando", listo: "Listo", error: "Error", cancelado: "Cancelado",
  esperando_manual: "Esperando subida", pendiente: "Por revisar", aprobado: "Aprobado", descartado: "Descartado",
  trabajando: "Trabajando", inactivo: "Sin trabajos", apagado: "Apagado", pausado: "Pausado",
  bloqueado: "Bloqueado", esperando: "En espera", descansando: "Descansando",
};
const badge = (estado, texto) => `<span class="badge ${esc(estado)}"><span class="dot"></span>${esc(texto || ESTADOS[estado] || estado)}</span>`;
const TIPO_MOTOR = { api: "API", navegador: "Navegador", manual: "Semi-manual" };
const FORMATO = { "4x5": "4:5", "9x16": "9:16", "1x1": "1:1", pdf: "PDF" };
const confirmar = (titulo, texto, boton = "Eliminar") =>
  new Promise((ok) => {
    abrirModal(`<div class="modal-box chico"><h2>${esc(titulo)}</h2><p class="muted">${esc(texto)}</p>
      <div class="row mt"><span class="spacer"></span><button class="btn" data-no>Cancelar</button>
      <button class="btn peligro lleno" data-si>${esc(boton)}</button></div></div>`);
    $("#modal [data-no]").onclick = () => { cerrarModal(); ok(false); };
    $("#modal [data-si]").onclick = () => { cerrarModal(); ok(true); };
  });
function abrirModal(html) { const m = $("#modal"); m.innerHTML = html; m.classList.remove("hidden"); }
function cerrarModal() { const m = $("#modal"); m.classList.add("hidden"); m.innerHTML = ""; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") cerrarModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarModal(); });

// ---------------------------------------------------------------- router
const RUTAS = { dashboard: vistaDashboard, contenido: vistaContenido, motores: vistaMotores, historial: vistaHistorial, configuracion: vistaConfig };
function ruta() {
  const r = (location.hash.replace("#/", "") || "dashboard").split("?")[0];
  return RUTAS[r] ? r : "dashboard";
}
async function navegar() {
  clearInterval(S.timer);
  const r = ruta();
  $$("nav a").forEach((a) => a.classList.toggle("activo", a.dataset.route === r));
  try { await RUTAS[r](); } catch (e) { app.innerHTML = `<div class="alerta">${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", navegar);
setInterval(() => ($("#reloj").textContent = new Date().toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" })), 1000);

function tabsClientes(clientes) {
  const todos = [{ id: "todos", nombre: "Todos" }, ...clientes];
  return `<div class="tabs">${todos.map((c) => `<button class="tab ${S.cliente === c.id ? "activo" : ""}" data-cliente="${esc(c.id)}">${esc(c.nombre)}</button>`).join("")}</div>`;
}
function bindTabs(recargar) {
  $$("[data-cliente]").forEach((b) => (b.onclick = () => { S.cliente = b.dataset.cliente; localStorage.setItem("cliente", S.cliente); recargar(); }));
}

// ================================================================= DASHBOARD
async function vistaDashboard() {
  await renderDashboard();
  S.timer = setInterval(() => renderDashboard(true).catch(() => {}), 2500);
}

async function renderDashboard(refresco = false) {
  const d = await api(`/api/estado?cliente=${encodeURIComponent(S.cliente)}`);
  if (refresco && $("#modal:not(.hidden)")) return; // no pisar un modal abierto
  const r = d.resumen;
  app.innerHTML = `
    <div class="topbar">
      <div><h1>Dashboard</h1><p>Generación automática de carruseles desde Google Sheets</p></div>
      <div class="row">${tabsClientes(d.clientes)}
        <button class="btn primario" id="sync">↻ Leer Sheets y generar</button></div>
    </div>
    ${d.alertas.map((a) => `<div class="alerta"><b>⚠</b><span>${esc(a.message)} <small>(${fecha(a.ts)})</small></span><span class="spacer"></span>
       <button class="btn sm" data-alerta="${a.id}">Entendido</button></div>`).join("")}
    <div class="grid g-4">
      <div class="card kpi"><div class="label">Piezas generadas</div><div class="num">${r.piezas}</div></div>
      <div class="card kpi"><div class="label">Por revisar</div><div class="num">${r.por_revisar}</div></div>
      <div class="card kpi"><div class="label">Costo hoy</div><div class="num">${usd(r.costo_hoy_usd, 3)}</div></div>
      <div class="card kpi"><div class="label">Costo por carrusel aprobado</div><div class="num">${usd(r.costo_por_aprobado, 3)}</div></div>
    </div>

    <div class="row mt" style="margin-bottom:10px"><h2 style="margin:0">Motores</h2><span class="spacer"></span>
      <a href="#/motores" class="small">Ver ranking →</a></div>
    <div class="grid motores-grid">${d.motores.map(tarjetaMotor).join("")}</div>

    <div class="card mt">${progresoHTML(d.progreso)}</div>

    <div class="grid g-2 mt">
      <div class="card"><h2>Fuentes de Google Sheets</h2>${d.fuentes.map(fuenteHTML).join("")}</div>
      <div class="card"><div class="row" style="margin-bottom:10px"><h2 style="margin:0">Cola de generación</h2><span class="spacer"></span>
        <span class="muted small">${d.cola.length} activos</span></div>${colaHTML(d.cola, d.motores)}
        ${d.recientes.length ? `<h3 class="mt" style="margin-bottom:6px">Últimos terminados</h3>${recientesHTML(d.recientes, d.motores)}` : ""}
      </div>
    </div>`;
  bindTabs(renderDashboard);
  $("#sync").onclick = async (e) => {
    e.target.disabled = true;
    try { const x = await api("/api/sync", { method: "POST", body: { cliente: S.cliente } }); toast(`${x.piezas} piezas leídas · ${x.encolados} trabajos encolados`); }
    catch (err) { toast(err.message, true); }
    renderDashboard();
  };
  $$("[data-alerta]").forEach((b) => (b.onclick = async () => { await api(`/api/alertas/${b.dataset.alerta}/descartar`, { method: "POST" }); renderDashboard(); }));
  bindAccionesMotor(renderDashboard);
  bindCola(renderDashboard);
}

function estadoMotor(m) {
  const rt = m.runtime || {};
  if (m.bloqueado_hasta) return badge("bloqueado", "Bloqueado") + `<span title="${esc(m.motivo_pausa)}">hasta ${fecha(m.bloqueado_hasta)}</span>`;
  if (!m.encendido) return badge("apagado");
  if (m.pausado) return badge("pausado");
  const e = rt.estado || "inactivo";
  let extra = rt.detalle ? esc(rt.detalle) : "";
  if (rt.hasta && e !== "bloqueado") extra += ` · hasta ${fecha(rt.hasta).slice(11)}`;
  return badge(e) + `<span>${extra}</span>`;
}

function tarjetaMotor(m) {
  const ref = { imagen: "Usa la imagen de referencia", estructura: "Usa la referencia para estructura y tono", ignora: "Ignora la referencia" }[m.usa_referencia];
  return `<div class="card motor ${m.encendido ? "" : "apagado"}">
    <div class="motor-head">
      <div class="motor-titulo"><span class="motor-num">${m.orden}</span><div><h3>${esc(m.nombre)}</h3>
        <div class="row" style="gap:4px;margin-top:4px"><span class="badge">${TIPO_MOTOR[m.tipo]}</span>${m.simulado ? '<span class="badge sim">Simulado</span>' : ""}</div></div></div>
      <label class="toggle" title="Encendido / Apagado"><input type="checkbox" data-toggle="${m.id}" ${m.encendido ? "checked" : ""}><span></span></label>
    </div>
    <div class="estado-linea">${estadoMotor(m)}</div>
    <div class="motor-stats">
      <div><b>${m.en_cola + m.procesando}</b><span>En cola</span></div>
      <div><b>${m.generadas}</b><span>Generadas</span></div>
      <div><b>$${Number(m.costo_hoy_usd || 0).toFixed(3)}</b><span>US$ hoy</span></div>
    </div>
    <div class="small muted" title="${esc(m.descripcion)}">${esc(ref)}${m.ritmo_humano ? ` · hoy ${m.hoy}/${m.tope_hoy ?? "–"}` : ""}</div>
    <div class="row">
      <button class="btn sm" data-pausar="${m.id}" data-estado="${m.pausado || m.bloqueado_hasta ? 1 : 0}">${m.pausado || m.bloqueado_hasta ? "▶ Reanudar" : "❚❚ Pausar"}</button>
      ${m.tipo === "navegador" ? `<button class="btn sm" data-login="${m.id}" title="Abre el navegador para iniciar sesión">Sesión</button>` : ""}
      <span class="spacer"></span>
      <button class="btn sm peligro" data-eliminar="${m.id}" data-nombre="${esc(m.nombre)}">Eliminar</button>
    </div>
  </div>`;
}

function bindAccionesMotor(recargar) {
  $$("[data-toggle]").forEach((i) => (i.onchange = async () => {
    await api(`/api/motores/${i.dataset.toggle}/encender`, { method: "POST", body: { encendido: i.checked } });
    toast(i.checked ? "Motor encendido: las próximas lecturas del Sheet lo incluyen" : "Motor apagado");
    recargar();
  }));
  $$("[data-pausar]").forEach((b) => (b.onclick = async () => {
    const pausado = b.dataset.estado !== "1";
    await api(`/api/motores/${b.dataset.pausar}/pausar`, { method: "POST", body: { pausado } });
    recargar();
  }));
  $$("[data-eliminar]").forEach((b) => (b.onclick = async () => {
    const ok = await confirmar(`¿Eliminar ${b.dataset.nombre}?`, "Se saca del laboratorio y se cancela su cola. El historial, las métricas y los archivos generados se conservan. Lo podés restaurar desde Motores.");
    if (!ok) return;
    const x = await api(`/api/motores/${b.dataset.eliminar}`, { method: "DELETE" });
    toast(`Motor eliminado · ${x.cancelados} trabajos cancelados`);
    recargar();
  }));
  $$("[data-login]").forEach((b) => (b.onclick = async () => {
    try { await api(`/api/motores/${b.dataset.login}/login`, { method: "POST" }); toast("Se abrió el navegador: iniciá sesión y cerralo al terminar"); }
    catch (e) { toast(e.message, true); }
  }));
}

function progresoHTML(p) {
  if (!p) return `<h2>Progreso</h2><p class="muted">Todavía no hay corridas. Tocá “Leer Sheets y generar”.</p>`;
  const c = p.conteo;
  return `<div class="row"><h2 style="margin:0">Progreso · corrida #${p.run.id}</h2><span class="muted small">${esc(p.run.summary || "")} · ${fecha(p.run.started_at)}</span>
      <span class="spacer"></span><b class="num">${p.porcentaje}%</b></div>
    <div class="barra mt"><i style="width:${p.porcentaje}%"></i></div>
    <div class="pasos">${p.pasos.map((s, i) => `<div class="paso ${s.estado}"><span class="circ">${s.estado === "hecho" ? "✓" : i + 1}</span>
      <div><b>${esc(s.label)}</b><small>${esc(s.detalle || "")}</small></div></div>`).join("")}</div>
    <div class="row mt small muted">${c.listos} listos · ${c.procesando} procesando · ${c.en_cola} en cola · ${c.esperando} esperando subida · ${c.errores} errores</div>`;
}

function fuenteHTML(f) {
  const est = f.estado === "ok" ? badge("ok", "Conectada") : f.estado === "error" ? badge("error", "Error") : badge("pendiente", "Sin leer");
  return `<div class="fuente"><span class="fuente-ic">S</span><div style="flex:1;min-width:0"><b>${esc(f.nombre)}</b>
    <div class="small muted">Pestaña “${esc(f.pestana)}” · ${f.modo === "demo" ? "Modo demo (sin credenciales)" : "Google Sheets"}${f.filas != null ? ` · ${f.filas} filas` : ""}${f.ultima ? ` · ${fecha(f.ultima)}` : ""}</div>
    ${f.error ? `<div class="small" style="color:var(--rojo)">${esc(f.error)}</div>` : ""}</div>${f.activo ? est : badge("apagado", "Inactiva")}</div>`;
}

const nombreMotor = (motores, id) => (motores.find((m) => m.id === id) || {}).nombre || id;

function colaHTML(cola, motores) {
  if (!cola.length) return `<div class="vacio">La cola está vacía.</div>`;
  return `<div class="tabla-wrap"><table><thead><tr><th>Pieza</th><th>Motor</th><th>Estado</th><th>Paso</th><th></th></tr></thead><tbody>
    ${cola.map((j) => `<tr><td><b>${esc(j.piece_id)}</b><div class="small muted">${esc(j.fecha)}</div></td>
      <td>${esc(nombreMotor(motores, j.engine))}</td><td>${badge(j.status)}</td><td class="small paso-col">${esc(j.step || "—")}</td>
      <td style="text-align:right;white-space:nowrap">${j.status === "esperando_manual" ? `<button class="btn sm verde" data-subir="${j.id}" data-sim="${j.simulated}">Subir resultado</button> ` : ""}
      <button class="btn sm" data-cancelar="${j.id}">Cancelar</button></td></tr>`).join("")}
  </tbody></table></div>`;
}

function recientesHTML(rs, motores) {
  return `<div class="tabla-wrap"><table><tbody>${rs.map((j) => `<tr><td class="small"><b>${esc(j.piece_id)}</b></td><td class="small">${esc(nombreMotor(motores, j.engine))}</td>
    <td>${badge(j.status)}</td><td class="small muted" title="${esc(j.error || "")}">${j.status === "error" ? esc((j.error || "").slice(0, 60)) : usd(j.cost_usd)}</td>
    <td style="text-align:right">${j.status === "error" ? `<button class="btn sm" data-reintentar="${j.id}">Reintentar</button>` : `<button class="btn sm" data-ver="${j.id}">Ver</button>`}</td></tr>`).join("")}</tbody></table></div>`;
}

function bindCola(recargar) {
  $$("[data-cancelar]").forEach((b) => (b.onclick = async () => { await api(`/api/trabajos/${b.dataset.cancelar}/cancelar`, { method: "POST" }); recargar(); }));
  $$("[data-reintentar]").forEach((b) => (b.onclick = async () => { await api(`/api/trabajos/${b.dataset.reintentar}/reintentar`, { method: "POST" }); toast("Reencolado"); recargar(); }));
  $$("[data-ver]").forEach((b) => (b.onclick = () => abrirDetalle(b.dataset.ver, recargar)));
  $$("[data-subir]").forEach((b) => (b.onclick = () => modalSubida(b.dataset.subir, b.dataset.sim === "1", recargar)));
}

function modalSubida(jobId, simulado, recargar) {
  abrirModal(`<div class="modal-box chico"><h2>Subir resultado de Canva</h2>
    <p class="muted small">Exportá desde Canva los slides en PNG (o un ZIP con todos) y subilos en orden. Se guardan como 4:5 y se reexportan los demás formatos.</p>
    <input type="file" id="archivos" class="input" multiple accept=".png,.jpg,.jpeg,.webp,.zip,.pdf" style="width:100%">
    <div class="row mt">${simulado ? '<button class="btn" id="sim">Simular resultado</button>' : ""}<span class="spacer"></span>
    <button class="btn" data-no>Cancelar</button><button class="btn primario" id="enviar">Subir</button></div></div>`);
  $("#modal [data-no]").onclick = cerrarModal;
  const enviar = async (conArchivos) => {
    const fd = new FormData();
    if (conArchivos) [...$("#archivos").files].forEach((f) => fd.append("archivos", f));
    try { await api(`/api/trabajos/${jobId}/subir`, { method: "POST", body: fd }); cerrarModal(); toast("Resultado cargado"); recargar(); }
    catch (e) { toast(e.message, true); }
  };
  $("#enviar").onclick = () => enviar(true);
  if (simulado) $("#sim").onclick = () => enviar(false);
}

// ================================================================= CONTENIDO FINALIZADO
async function vistaContenido() {
  const [est, cfg] = await Promise.all([api("/api/estado"), api("/api/config")]);
  const f = S.filtros;
  if (!f.cliente && S.cliente !== "todos") f.cliente = S.cliente;
  const opt = (arr, sel) => arr.map(([v, t]) => `<option value="${esc(v)}" ${sel === v ? "selected" : ""}>${esc(t)}</option>`).join("");
  app.innerHTML = `
    <div class="topbar"><div><h1>Contenido finalizado</h1><p>Todo lo que hay en /output, con su evaluación y costo</p></div></div>
    <div class="card">
      <div class="filtros">
        <input class="input buscar" id="f-q" placeholder="Buscar por texto, pieza o cliente…" value="${esc(f.q)}">
        <select class="input" id="f-tipo">${opt([["", "Todos los tipos"], ["carrusel", "Carrusel 4:5"], ["historia", "Historia 9:16"], ["reel", "Reel 9:16"], ["post", "Post 1:1"], ["pdf", "PDF LinkedIn"]], f.tipo)}</select>
        <select class="input" id="f-motor">${opt([["", "Todas las herramientas"], ...cfg.motores.map((m) => [m.id, m.nombre])], f.motor)}</select>
        <select class="input" id="f-cliente">${opt([["", "Todos los clientes"], ...est.clientes.map((c) => [c.id, c.nombre])], f.cliente)}</select>
        <select class="input" id="f-estado">${opt([["", "Todos los estados"], ["pendiente", "Por revisar"], ["aprobado", "Aprobado"], ["descartado", "Descartado"], ["esperando_manual", "Esperando subida"]], f.estado)}</select>
        <input class="input" type="date" id="f-desde" value="${esc(f.desde)}" title="Desde">
        <input class="input" type="date" id="f-hasta" value="${esc(f.hasta)}" title="Hasta">
      </div>
      <div id="tabla-contenido"></div>
    </div>`;
  const leer = () => { for (const k of Object.keys(f)) f[k] = $(`#f-${k}`).value; cargarContenido(); };
  $$(".filtros select, .filtros input[type=date]").forEach((el) => (el.onchange = leer));
  let h; $("#f-q").oninput = () => { clearTimeout(h); h = setTimeout(leer, 250); };
  cargarContenido();
}

async function cargarContenido() {
  const qs = new URLSearchParams(Object.entries(S.filtros).filter(([, v]) => v)).toString();
  const { items } = await api(`/api/contenido?${qs}`);
  const cont = $("#tabla-contenido");
  if (!cont) return;
  if (!items.length) { cont.innerHTML = `<div class="vacio">No hay contenido con esos filtros.</div>`; return; }
  cont.innerHTML = `<div class="tabla-wrap"><table><thead><tr><th></th><th>Pieza</th><th>Cliente</th><th>Herramienta</th><th>Tipos</th><th>Estado</th><th>Puntaje</th><th>Costo</th><th></th></tr></thead><tbody>
    ${items.map((m) => {
      const thumb = (m.formatos?.["4x5"] || [])[0];
      const ev = m.evaluacion || {};
      const notas = [ev.diseno, ev.texto, ev.marca].filter((x) => x != null);
      const prom = notas.length ? notas.reduce((a, b) => a + b, 0) / notas.length : null;
      const estado = m.estado === "esperando_manual" ? "esperando_manual" : ev.estado || "pendiente";
      return `<tr>
        <td>${thumb ? `<img class="thumb" loading="lazy" src="/files/${esc(thumb)}">` : `<div class="thumb"></div>`}</td>
        <td><b>${esc(m.pieza_id)}</b><div class="small muted">${esc(m.fecha)} · ${esc((m.slides_sheet || [])[0] || "").slice(0, 48)}</div></td>
        <td>${esc(m.cliente_nombre)}</td>
        <td>${esc(m.motor_nombre)}${m.simulado ? ' <span class="badge sim">Sim</span>' : ""}</td>
        <td><div class="chips">${Object.keys(m.formatos || {}).map((k) => `<span class="chip">${FORMATO[k] || k}</span>`).join("")}</div></td>
        <td>${badge(estado)}</td>
        <td>${prom == null ? "—" : `<b>${prom.toFixed(1)}</b>/5`}</td>
        <td>${usd(m.costo_usd)}</td>
        <td style="text-align:right;white-space:nowrap"><button class="btn sm" data-ver="${m.job_id}">Ver</button>
          <button class="btn sm" disabled title="Próximamente">Programar</button></td></tr>`;
    }).join("")}</tbody></table></div>`;
  $$("[data-ver]", cont).forEach((b) => (b.onclick = () => abrirDetalle(b.dataset.ver, cargarContenido)));
}

// ---------------------------------------------------------------- detalle + evaluación
async function abrirDetalle(jobId, alCerrar) {
  const m = await api(`/api/contenido/${jobId}`);
  let fmt = m.formatos?.["4x5"] ? "4x5" : Object.keys(m.formatos || {})[0];
  const ev = m.evaluacion || {};
  const ig = m.instagram || {};
  const usos = m.uso || [];
  const render = () => {
    const archivos = (m.formatos || {})[fmt] || [];
    const vista = fmt === "pdf"
      ? archivos.map((a) => `<p><a class="btn" href="/files/${esc(a)}" target="_blank">Abrir PDF para LinkedIn ↗</a></p>`).join("")
      : `<div class="slides">${archivos.map((a) => `<a href="/files/${esc(a)}" target="_blank"><img src="/files/${esc(a)}"></a>`).join("")}</div>`;
    const estrellas = (campo) => `<div class="estrellas" data-campo="${campo}">${[1, 2, 3, 4, 5].map((n) => `<button data-n="${n}" class="${(ev[campo] || 0) >= n ? "on" : ""}">★</button>`).join("")}</div>`;
    abrirModal(`<div class="modal-box">
      <div class="row" style="margin-bottom:14px"><div><h2 style="margin:0">${esc(m.pieza_id)} · ${esc(m.motor_nombre)}</h2>
        <div class="small muted">${esc(m.cliente_nombre)} · ${esc(m.fecha)} · fila ${esc(m.fila_sheet)} del Sheet${m.simulado ? " · SIMULADO" : ""}</div></div>
        <span class="spacer"></span><button class="btn" data-cerrar>Cerrar</button></div>
      <div class="detalle">
        <div>
          <div class="seg">${Object.keys(m.formatos || {}).map((k) => `<button class="tab ${k === fmt ? "activo" : ""}" data-fmt="${k}">${FORMATO[k] || k}</button>`).join("")}
            ${m.reel_mp4 ? `<a class="btn sm" href="/files/${esc(m.reel_mp4)}" target="_blank">Reel MP4 ↗</a>` : ""}</div>
          ${m.estado === "esperando_manual" ? `<div class="alerta" style="background:#FFF8E6;border-color:#FFE1A6;color:#7A5200">Esperando que subas el resultado de Canva (desde la cola del Dashboard).</div>` : vista}
          <h3 class="mt">Texto por slide</h3>
          <ol class="small">${(m.textos || []).map((t) => `<li>${t.titulo ? `<b>${esc(t.titulo)}</b> ` : ""}${esc(t.texto || "")}</li>`).join("")}</ol>
          ${m.extra?.caption ? `<h3 class="mt">Caption</h3><p class="small">${esc(m.extra.caption)}<br><span class="muted">${(m.extra.hashtags || []).map((h) => esc(h.startsWith("#") ? h : "#" + h)).join(" ")}</span></p>` : ""}
        </div>
        <div>
          <div class="card" style="box-shadow:none">
            <h3 style="margin-bottom:8px">Evaluación</h3>
            <div class="eval-fila"><span>Diseño</span>${estrellas("diseno")}</div>
            <div class="eval-fila"><span>Texto</span>${estrellas("texto")}</div>
            <div class="eval-fila"><span>Fidelidad de marca</span>${estrellas("marca")}</div>
            <textarea class="input mt" id="ev-notas" rows="2" style="width:100%" placeholder="Notas (opcional)">${esc(ev.notas || "")}</textarea>
            <div class="row mt"><span>${badge(ev.estado || "pendiente")}</span><span class="spacer"></span>
              <button class="btn peligro" data-estado="descartado">Descartar</button>
              <button class="btn verde" data-estado="aprobado">Aprobar</button></div>
          </div>
          <div class="card mt" style="box-shadow:none">
            <h3 style="margin-bottom:8px">Costo y consumo</h3>
            <dl class="kv"><dt>Costo</dt><dd><b>${usd(m.costo_usd)}</b></dd><dt>Tiempo</dt><dd>${seg(m.duracion_s)}</dd>
              ${usos.map((u) => `<dt>${esc(u.modelo)}</dt><dd>${u.input_tokens ? `${u.input_tokens} in · ` : ""}${u.image_input_tokens ? `${u.image_input_tokens} img-in · ` : ""}${u.output_tokens ? `${u.output_tokens} out` : ""}${u.imagenes ? ` · ${u.imagenes} imágenes` : ""}</dd>`).join("")}
              <dt>Nativos</dt><dd>${(m.nativos || []).map((k) => FORMATO[k]).join(", ") || "—"}</dd>
              <dt>Reexportados</dt><dd>${(m.reexportados || []).map((k) => FORMATO[k]).join(", ") || "—"}</dd>
              <dt>Carpeta</dt><dd class="small">output/${esc(m._dir)}</dd></dl>
          </div>
          <div class="card mt" style="box-shadow:none">
            <h3 style="margin-bottom:8px">Métricas de Instagram <span class="muted small">(para cargar después)</span></h3>
            <div class="form-grid" style="grid-template-columns:1fr 1fr">${Object.keys(ig).map((k) => `<div class="campo"><label>${esc(k.replace("_", " "))}</label>
              <input class="input" type="number" min="0" data-ig="${k}" value="${ig[k] ?? ""}"></div>`).join("")}</div>
            <button class="btn sm mt" id="guardar-ig">Guardar métricas</button>
          </div>
        </div>
      </div></div>`);
    $("#modal [data-cerrar]").onclick = () => { cerrarModal(); alCerrar && alCerrar(); };
    $$("#modal [data-fmt]").forEach((b) => (b.onclick = () => { fmt = b.dataset.fmt; render(); }));
    $$("#modal .estrellas").forEach((box) => $$("button", box).forEach((b) => (b.onclick = async () => {
      ev[box.dataset.campo] = Number(b.dataset.n);
      await guardar({ [box.dataset.campo]: Number(b.dataset.n) });
    })));
    $$("#modal [data-estado]").forEach((b) => (b.onclick = async () => { ev.estado = b.dataset.estado; await guardar({ estado: b.dataset.estado, notas: $("#ev-notas").value }); toast(ev.estado === "aprobado" ? "Aprobado ✓" : "Descartado"); }));
    $("#guardar-ig").onclick = async () => {
      const vals = {};
      $$("#modal [data-ig]").forEach((i) => (vals[i.dataset.ig] = i.value === "" ? null : Number(i.value)));
      Object.assign(ig, vals);
      await guardar({ instagram: vals });
      toast("Métricas guardadas");
    };
  };
  const guardar = async (body) => {
    try { const r = await api(`/api/contenido/${jobId}/evaluar`, { method: "POST", body }); Object.assign(ev, r.evaluacion || {}); render(); }
    catch (e) { toast(e.message, true); }
  };
  render();
}

// ================================================================= MOTORES
async function vistaMotores() {
  const [d, est, cfg] = await Promise.all([api(`/api/motores?cliente=${encodeURIComponent(S.cliente)}`), api("/api/estado"), api("/api/config")]);
  const activos = d.ranking.filter((m) => !m.eliminado);
  const eliminados = d.ranking.filter((m) => m.eliminado);
  const o = S.orden;
  const val = (m) => { const v = m[o.col]; return v == null ? (o.dir > 0 ? Infinity : -Infinity) : v; };
  activos.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * o.dir);
  const th = (col, t) => `<th class="ord" data-orden="${col}">${t}${o.col === col ? (o.dir > 0 ? " ↑" : " ↓") : ""}</th>`;
  const sim = cfg.settings.simulacion;
  app.innerHTML = `
    <div class="topbar"><div><h1>Motores</h1><p>Ranking para descartar los malos y ver cuánto cuesta cada uno</p></div>${tabsClientes(est.clientes)}</div>
    <div class="card"><div class="tabla-wrap"><table><thead><tr><th>#</th><th>Motor</th><th>Estado</th>
      ${th("generadas", "Piezas")}${th("tasa_error", "Tasa de error")}${th("tiempo_medio_s", "Tiempo medio")}${th("costo_usd", "Costo total")}
      ${th("costo_por_pieza", "Costo / pieza")}${th("puntaje", "Puntaje")}${th("aprobados", "Aprobados")}${th("costo_por_aprobado", "Costo / aprobado")}<th></th></tr></thead><tbody>
      ${activos.map((m, i) => `<tr><td><b class="num">${i + 1}</b></td>
        <td class="nombre-motor"><b>${esc(m.nombre)}</b><div class="small muted">${TIPO_MOTOR[m.tipo]}${sim[m.id] ? " · simulado" : ""}</div></td>
        <td><label class="toggle-label"><span class="toggle"><input type="checkbox" data-toggle="${m.id}" ${m.encendido ? "checked" : ""}><span></span></span>
          ${m.bloqueado_hasta ? badge("bloqueado") : m.pausado ? badge("pausado") : ""}</label></td>
        <td>${m.generadas}</td><td>${pct(m.tasa_error)} <span class="small muted">(${m.errores})</span></td><td>${seg(m.tiempo_medio_s)}</td>
        <td>${usd(m.costo_usd, 3)}</td><td>${usd(m.costo_por_pieza)}</td>
        <td title="Diseño ${nota(m.p_diseno)} · Texto ${nota(m.p_texto)} · Marca ${nota(m.p_marca)}"><b>${nota(m.puntaje)}</b></td>
        <td>${m.aprobados}</td><td><b>${usd(m.costo_por_aprobado, 3)}</b></td>
        <td style="white-space:nowrap;text-align:right"><button class="btn sm" data-pausar="${m.id}" data-estado="${m.pausado || m.bloqueado_hasta ? 1 : 0}">${m.pausado || m.bloqueado_hasta ? "Reanudar" : "Pausar"}</button>
          <button class="btn sm peligro" data-eliminar="${m.id}" data-nombre="${esc(m.nombre)}">Eliminar</button></td></tr>`).join("")}
    </tbody></table></div>
    <p class="small muted">Puntaje = promedio de diseño, texto y fidelidad de marca (1 a 5). Costo por aprobado = costo total del motor ÷ carruseles aprobados.</p></div>

    <div class="card mt"><h2>Costo por día y por motor</h2>
      ${d.costos_por_dia.length ? `<div class="tabla-wrap"><table><thead><tr><th>Día</th><th>Motor</th><th>Piezas</th><th>Aprobadas</th><th>Costo</th></tr></thead><tbody>
      ${d.costos_por_dia.map((c) => `<tr><td>${esc(c.dia)}</td><td>${esc(nombreMotor(d.ranking, c.engine))}</td><td>${c.piezas}</td><td>${c.aprobados || 0}</td><td>${usd(c.costo, 4)}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="vacio">Sin datos todavía.</div>`}</div>

    ${eliminados.length ? `<div class="card mt"><h2>Motores eliminados</h2>${eliminados.map((m) => `<div class="fuente"><div style="flex:1"><b>${esc(m.nombre)}</b>
      <div class="small muted">${m.generadas} piezas · ${usd(m.costo_usd, 3)}</div></div><button class="btn sm" data-restaurar="${m.id}">Restaurar</button></div>`).join("")}</div>` : ""}`;
  bindTabs(vistaMotores);
  bindAccionesMotor(vistaMotores);
  $$("[data-orden]").forEach((t) => (t.onclick = () => {
    if (S.orden.col === t.dataset.orden) S.orden.dir *= -1; else S.orden = { col: t.dataset.orden, dir: -1 };
    vistaMotores();
  }));
  $$("[data-restaurar]").forEach((b) => (b.onclick = async () => { await api(`/api/motores/${b.dataset.restaurar}/restaurar`, { method: "POST" }); toast("Restaurado (apagado)"); vistaMotores(); }));
}

// ================================================================= HISTORIAL
async function vistaHistorial() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const nivel = params.get("nivel") || "", motor = params.get("motor") || "";
  const [d, cfg] = await Promise.all([api(`/api/historial?nivel=${nivel}&motor=${motor}`), api("/api/config")]);
  const nm = (id) => (cfg.motores.find((m) => m.id === id) || {}).nombre || id || "—";
  app.innerHTML = `
    <div class="topbar"><div><h1>Historial</h1><p>Cada corrida, cada trabajo y cada error</p></div></div>
    <div class="card"><h2>Corridas</h2>${d.corridas.length ? `<div class="tabla-wrap"><table><thead><tr><th>#</th><th>Inicio</th><th>Fin</th><th>Origen</th><th>Cliente</th><th>Resumen</th></tr></thead><tbody>
      ${d.corridas.map((r) => `<tr><td>${r.id}</td><td>${fecha(r.started_at)}</td><td>${fecha(r.finished_at)}</td><td>${esc(r.trigger)}</td><td>${esc(r.client)}</td><td>${esc(r.summary || "")}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="vacio">Sin corridas.</div>`}</div>
    <div class="card mt"><h2>Trabajos</h2><div class="tabla-wrap" style="max-height:420px;overflow:auto"><table><thead><tr><th>ID</th><th>Pieza</th><th>Motor</th><th>Estado</th><th>Intentos</th><th>Inicio</th><th>Duración</th><th>Costo</th><th>Error</th></tr></thead><tbody>
      ${d.trabajos.map((j) => `<tr><td>${j.id}</td><td>${esc(j.piece_id)}</td><td>${esc(nm(j.engine))}${j.simulated ? ' <span class="badge sim">Sim</span>' : ""}</td><td>${badge(j.status)}</td>
        <td>${j.attempts}</td><td>${fecha(j.started_at)}</td><td>${seg(j.duration_s)}</td><td>${usd(j.cost_usd)}</td><td class="small" style="color:var(--rojo)">${esc(j.error || "")}</td></tr>`).join("")}
    </tbody></table></div></div>
    <div class="card mt"><div class="row" style="margin-bottom:10px"><h2 style="margin:0">Log</h2><span class="spacer"></span>
      <select class="input" id="h-nivel"><option value="">Todos los niveles</option>${["info", "warning", "error", "alerta"].map((n) => `<option ${n === nivel ? "selected" : ""}>${n}</option>`).join("")}</select>
      <select class="input" id="h-motor"><option value="">Todos los motores</option>${cfg.motores.map((m) => `<option value="${m.id}" ${m.id === motor ? "selected" : ""}>${esc(m.nombre)}</option>`).join("")}</select></div>
      <div class="tabla-wrap" style="max-height:520px;overflow:auto"><table><tbody>
      ${d.logs.map((l) => `<tr><td class="small muted" style="white-space:nowrap">${fecha(l.ts)}</td><td>${badge(l.level === "info" ? "listo" : l.level === "warning" ? "esperando" : "error", l.level)}</td>
        <td class="small">${esc(nm(l.engine))}</td><td class="small muted">${l.job_id ? "#" + l.job_id : ""}</td><td><pre class="log">${esc(l.message)}</pre></td></tr>`).join("")}
      </tbody></table></div></div>`;
  const filtrar = () => { location.hash = `#/historial?nivel=${$("#h-nivel").value}&motor=${$("#h-motor").value}`; };
  $("#h-nivel").onchange = filtrar;
  $("#h-motor").onchange = filtrar;
}

// ================================================================= CONFIGURACIÓN
async function vistaConfig() {
  const { settings: s, motores } = await api("/api/config");
  const sec = S.cfgSeccion;
  const secciones = { claves: "Claves", clientes: "Clientes", simulacion: "Simulación", modelos: "Modelos", precios: "Precios", limites: "Límites", ritmo: "Ritmo humano", selectores: "Selectores web" };
  const campo = (label, path, val, type = "text", extra = "") => `<div class="campo"><label>${esc(label)}</label><input class="input" data-path="${path}" type="${type}" value="${esc(val ?? "")}" ${extra}></div>`;
  const rango = (label, path, v) => `<div class="campo"><label>${esc(label)}</label><div class="rango">
    <input class="input" type="number" step="any" data-path="${path}.0" value="${v[0]}"><span>a</span><input class="input" type="number" step="any" data-path="${path}.1" value="${v[1]}"></div></div>`;
  let cuerpo = "";
  if (sec === "claves") cuerpo = `<div class="form-grid">
      ${campo("OpenAI API key", "claves.openai_api_key", s.claves.openai_api_key, "password", 'autocomplete="off"')}
      ${campo("Anthropic API key", "claves.anthropic_api_key", s.claves.anthropic_api_key, "password", 'autocomplete="off"')}
      ${campo("JSON de la cuenta de servicio (ruta)", "claves.google_service_account_json", s.claves.google_service_account_json)}
      ${campo("ID del Google Sheet", "claves.spreadsheet_id", s.claves.spreadsheet_id)}</div>
    <p class="small muted">Las claves se guardan solo en tu computadora (data/lab.db). También podés usar las variables de entorno OPENAI_API_KEY y ANTHROPIC_API_KEY. Compartí el Sheet (y los archivos de Drive de referencia) con el email de la cuenta de servicio, como lector.</p>`;
  if (sec === "clientes") cuerpo = `<table><thead><tr><th>ID (carpeta)</th><th>Nombre</th><th>Pestaña del Sheet</th><th>Activo</th><th></th></tr></thead><tbody>
      ${s.clientes.map((c, i) => `<tr><td><input class="input" data-path="clientes.${i}.id" value="${esc(c.id)}"></td><td><input class="input" data-path="clientes.${i}.nombre" value="${esc(c.nombre)}"></td>
        <td><input class="input" data-path="clientes.${i}.pestana" value="${esc(c.pestana)}"></td>
        <td><label class="toggle"><input type="checkbox" data-path="clientes.${i}.activo" ${c.activo ? "checked" : ""}><span></span></label></td>
        <td><button class="btn sm peligro" data-quitar-cliente="${i}">Quitar</button></td></tr>`).join("")}</tbody></table>
      <button class="btn sm mt" id="agregar-cliente">+ Agregar cliente</button>
      <p class="small muted">Cada cliente usa /plantillas/{id}/ (brand.json, plantilla.html, plantilla.png) y /referencias/{id}/.</p>`;
  if (sec === "simulacion") cuerpo = `<p class="muted">Un motor simulado no llama a ninguna API ni abre el navegador: genera imágenes de prueba y costos ficticios para ver el flujo completo.</p>
      <div class="form-grid">${motores.map((m) => `<label class="toggle-label" style="font-size:14px;color:var(--texto)"><span class="toggle"><input type="checkbox" data-path="simulacion.${m.id}" ${s.simulacion[m.id] ? "checked" : ""}><span></span></span>${esc(m.nombre)}</label>`).join("")}</div>
      <div class="form-grid mt">${campo("Escala de tiempo (0.01 = 100× más rápido)", "simulacion_escala_tiempo", s.simulacion_escala_tiempo, "number", 'step="any"')}
      ${campo("Tasa de error simulada (0 a 1)", "simulacion_tasa_error", s.simulacion_tasa_error, "number", 'step="any"')}</div>`;
  if (sec === "modelos") cuerpo = `<div class="form-grid">${Object.entries(s.modelos).map(([k, v]) => campo(k.replaceAll("_", " "), `modelos.${k}`, v)).join("")}</div>
      <p class="small muted">Si cambiás de modelo, agregá su precio en la pestaña Precios (con el mismo nombre).</p>`;
  if (sec === "precios") cuerpo = `<table><thead><tr><th>Modelo</th><th>Input US$/M tokens</th><th>Input imagen US$/M</th><th>Output US$/M tokens</th><th>US$ por imagen</th><th></th></tr></thead><tbody>
      ${Object.entries(s.precios).map(([mod, p]) => `<tr data-precio="${esc(mod)}"><td><input class="input" data-pm="nombre" value="${esc(mod)}"></td>
        ${["input_mtok", "image_input_mtok", "output_mtok", "por_imagen"].map((k) => `<td><input class="input" type="number" step="any" data-pm="${k}" value="${p[k] ?? ""}"></td>`).join("")}
        <td><button class="btn sm peligro" data-quitar-precio>Quitar</button></td></tr>`).join("")}</tbody></table>
      <button class="btn sm mt" id="agregar-precio">+ Agregar modelo</button>
      <p class="small muted">Costo = tokens (o imágenes) que devuelve cada respuesta de la API × esta tabla. Los valores precargados son de referencia: verificalos en la página de precios de cada proveedor.</p>`;
  if (sec === "limites") cuerpo = `<div class="form-grid">
      ${campo("Presupuesto diario (US$, 0 = sin tope)", "limites.presupuesto_diario_usd", s.limites.presupuesto_diario_usd, "number", 'step="any"')}
      ${campo("Máx. piezas por día por motor de API", "limites.max_piezas_dia_por_motor", s.limites.max_piezas_dia_por_motor, "number")}
      ${campo("Espera mínima entre pedidos a la API (s)", "limites.api_espera_min_s", s.limites.api_espera_min_s, "number", 'step="any"')}
      ${campo("Espera máxima entre pedidos a la API (s)", "limites.api_espera_max_s", s.limites.api_espera_max_s, "number", 'step="any"')}
      ${campo("Reintentos por pedido", "limites.api_reintentos", s.limites.api_reintentos, "number")}
      ${campo("Base de la espera creciente (s)", "limites.api_backoff_base_s", s.limites.api_backoff_base_s, "number", 'step="any"')}
      ${campo("Leer el Sheet automáticamente cada (min, 0 = no)", "limites.sync_automatico_min", s.limites.sync_automatico_min, "number")}
      ${campo("Formatos que genera el motor 3 con la API (coma)", "motor3_formatos", s.motor3_formatos.join(", "))}
      <label class="toggle-label"><span class="toggle"><input type="checkbox" data-path="limites.solo_fechas_desde_hoy" ${s.limites.solo_fechas_desde_hoy ? "checked" : ""}><span></span></span>Solo filas con fecha de hoy en adelante</label></div>`;
  if (sec === "ritmo") { const r = s.ritmo_humano; cuerpo = `<p class="muted">Se aplica a los motores de navegador (Gemini web, ChatGPT web).</p><div class="form-grid">
      ${rango("Espera al cargar (s)", "ritmo_humano.espera_carga_s", r.espera_carga_s)}
      ${rango("Escritura (ms por letra)", "ritmo_humano.escritura_ms_por_letra", r.escritura_ms_por_letra)}
      ${rango("Pausa entre prompts (s)", "ritmo_humano.pausa_entre_prompts_s", r.pausa_entre_prompts_s)}
      ${rango("Pausa entre carruseles (min)", "ritmo_humano.pausa_entre_carruseles_min", r.pausa_entre_carruseles_min)}
      ${rango("Descanso cada N carruseles", "ritmo_humano.descanso_cada_n", r.descanso_cada_n)}
      ${rango("Duración del descanso (min)", "ritmo_humano.descanso_min", r.descanso_min)}
      ${rango("Tope de carruseles por día", "ritmo_humano.tope_diario", r.tope_diario)}
      ${campo("Pausa ante captcha / límite (horas)", "ritmo_humano.pausa_bloqueo_horas", r.pausa_bloqueo_horas, "number")}
      ${campo("Franjas horarias (separadas por coma)", "ritmo_humano.franjas", r.franjas.join(", "))}</div>`; }
  if (sec === "selectores") cuerpo = `<p class="muted">Selectores CSS de las webs automatizadas. Si Gemini o ChatGPT cambian su diseño, se corrigen acá sin tocar código.</p>
      <textarea class="input" id="selectores" rows="22" style="width:100%;font-family:ui-monospace,monospace;font-size:12px">${esc(JSON.stringify(s.selectores, null, 2))}</textarea>`;

  app.innerHTML = `<div class="topbar"><div><h1>Configuración</h1><p>Claves, precios, límites y ritmo humano</p></div>
      <button class="btn primario" id="guardar">Guardar cambios</button></div>
    <div class="cfg-nav tabs" style="display:inline-flex">${Object.entries(secciones).map(([k, t]) => `<button class="tab ${k === sec ? "activo" : ""}" data-sec="${k}">${t}</button>`).join("")}</div>
    <div class="card">${cuerpo}</div>`;
  $$("[data-sec]").forEach((b) => (b.onclick = () => { S.cfgSeccion = b.dataset.sec; vistaConfig(); }));

  const recolectar = () => {
    const n = JSON.parse(JSON.stringify(s));
    $$("[data-path]").forEach((el) => {
      const keys = el.dataset.path.split(".");
      let o = n;
      keys.slice(0, -1).forEach((k) => (o = o[k]));
      const last = keys[keys.length - 1];
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "number") v = v === "" ? 0 : Number(v);
      if (el.dataset.path === "motor3_formatos") v = String(v).split(",").map((x) => x.trim()).filter(Boolean);
      if (el.dataset.path === "ritmo_humano.franjas") v = String(v).split(",").map((x) => x.trim()).filter(Boolean);
      o[last] = v;
    });
    if (sec === "precios") {
      n.precios = {};
      $$("[data-precio]").forEach((tr) => {
        const nombre = $("[data-pm=nombre]", tr).value.trim();
        if (!nombre) return;
        const p = {};
        ["input_mtok", "image_input_mtok", "output_mtok", "por_imagen"].forEach((k) => { const v = $(`[data-pm=${k}]`, tr).value; if (v !== "") p[k] = Number(v); });
        n.precios[nombre] = p;
      });
    }
    if (sec === "selectores") n.selectores = JSON.parse($("#selectores").value);
    return n;
  };
  $("#guardar").onclick = async () => {
    try { await api("/api/config", { method: "PUT", body: { settings: recolectar() } }); toast("Configuración guardada"); vistaConfig(); }
    catch (e) { toast(e.message, true); }
  };
  const agregarCliente = $("#agregar-cliente");
  if (agregarCliente) agregarCliente.onclick = () => { const n = recolectar(); n.clientes.push({ id: "cliente-nuevo", nombre: "Cliente nuevo", pestana: "Cliente nuevo", activo: true }); Object.assign(s, n); rerender(); };
  $$("[data-quitar-cliente]").forEach((b) => (b.onclick = () => { const n = recolectar(); n.clientes.splice(Number(b.dataset.quitarCliente), 1); Object.assign(s, n); rerender(); }));
  const agregarPrecio = $("#agregar-precio");
  if (agregarPrecio) agregarPrecio.onclick = () => { const n = recolectar(); n.precios["modelo-nuevo"] = { input_mtok: 0, output_mtok: 0 }; Object.assign(s, n); rerender(); };
  $$("[data-quitar-precio]").forEach((b) => (b.onclick = () => b.closest("tr").remove()));
  // Cambios locales (agregar/quitar filas) se ven al instante y se persisten con "Guardar".
  async function rerender() {
    await api("/api/config", { method: "PUT", body: { settings: s } });
    vistaConfig();
  }
}

navegar();
