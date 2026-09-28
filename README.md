# Flaks Content Lab

App **local** (corre en tu computadora) que orquesta la generación automática de carruseles desde Google Sheets
y te deja comparar *motores* de generación: cuánto cuesta cada uno, cuántos errores tiene, cuánto tarda y qué
puntaje le das, para quedarte con los buenos.

- Python 3.11 · FastAPI · SQLite · frontend web servido en `http://127.0.0.1:8765`
- Playwright (render de plantillas HTML y motor de navegador con perfil persistente y visible)
- Google Sheets API con cuenta de servicio, solo lectura

## Instalación

```bash
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python -m flaks_lab                  # abre el navegador en http://127.0.0.1:8765
```

Sin configurar nada, la app arranca en **modo demo**: lee `datos/demo_sheet.json` en lugar del Sheet
y todos los motores están **simulados** (no llaman a ninguna API ni abren el navegador). Tocá
*Leer Sheets y generar* en el Dashboard para ver el flujo completo.

Si Playwright no encuentra Chromium, podés indicar el ejecutable con la variable `FLAKS_CHROMIUM`.

## Conectar el Google Sheet

1. En Google Cloud, creá una cuenta de servicio, habilitá **Google Sheets API** (y **Google Drive API** si vas a
   usar referencias de Drive) y descargá su JSON a `credenciales/service-account.json`.
2. Compartí el Sheet (y las imágenes de referencia de Drive) con el email de la cuenta de servicio, como **lector**.
3. En *Configuración → Claves* cargá el ID del Sheet (lo que está entre `/d/` y `/edit` en la URL).

Formato del Sheet: **una pestaña por cliente** (`Flaks`, `Cliente 1`, `Cliente 2`; se configuran en
*Configuración → Clientes*). Fila 1 = encabezados.

| A | B … F (extensible) | opcional | opcional |
|---|---|---|---|
| Fecha | Contenido Slide 1 … Contenido Slide 5 (Slide 6, 7…) | Referencia | Qué tomar |

- **Referencia**: link de Drive o nombre de archivo en `referencias/{cliente}/`.
- **Qué tomar**: estilo visual, estructura de slides o idea de contenido. Nunca se copia el texto de la referencia.
- Cada fila con fecha y contenido es una **pieza** (un carrusel). La pieza se encola en **cada motor encendido**,
  para comparar motores con el mismo contenido. Si editás la fila, se vuelve a encolar.

## Plantilla de marca por cliente

`plantillas/{cliente}/`:

- `brand.json`: nombre, handle, colores, tipografías, tono, reglas y estilo visual.
- `plantilla.html` (opcional): plantilla Jinja2 para los motores 1 y 2. Si no está, se usa `plantillas/_base/plantilla.html`.
- `plantilla.png` (opcional): imagen de la plantilla para los motores 3 y 5. Si no está, se genera
  renderizando la plantilla HTML.

## Salida

```
output/{cliente}/{YYYY-MM-DD}/{motor}/{pieza-id}/{formato}/slide-01.png
output/{cliente}/{YYYY-MM-DD}/{motor}/{pieza-id}/meta.json
```

Formatos: `4x5` (carrusel), `9x16` (historia/reel; si tenés ffmpeg también se arma `reel.mp4`),
`1x1` (post cuadrado) y `pdf` (LinkedIn). Los motores que no producen un formato de forma nativa lo
reexportan desde el 4:5. La pantalla *Contenido finalizado* se arma leyendo los `meta.json`.

## Pantallas

- **Dashboard**: tabs de cliente, tarjetas de motores con toggle / Pausar / Eliminar, barra de progreso con pasos,
  fuentes de Google Sheets con estado y cola de generación (incluye *Subir resultado* para Canva).
- **Contenido finalizado**: tabla con miniaturas, filtros por tipo, herramienta, cliente, estado, búsqueda y fechas.
  En cada pieza: puntaje 1 a 5 de diseño, texto y fidelidad de marca, Aprobar / Descartar y campos para métricas
  de Instagram. *Programar* queda deshabilitado por ahora.
- **Motores**: ranking con piezas, tasa de error, tiempo medio, costo, puntaje promedio y costo por carrusel aprobado.
- **Historial**: corridas, trabajos y log de cada error.
- **Configuración**: claves, clientes, simulación, modelos, precios, límites, ritmo humano y selectores web.

## Motores (plugins)

Cada motor es un archivo en `flaks_lab/engines/` que hereda de `Motor` e implementa
`generar(pieza, ctx) -> Resultado` (archivos por formato + consumo de la API). Se registran con `@registrar`;
para agregar uno nuevo alcanza con crear el archivo. *Eliminar* un motor desde la UI lo saca del laboratorio y
cancela su cola, pero conserva historial y archivos (se puede restaurar desde *Motores*).

| # | Motor | Referencia | Formatos nativos |
|---|---|---|---|
| 1 | GPT API + plantillas HTML | estructura y tono del texto | todos |
| 2 | Claude API + plantillas HTML | estructura y tono del texto | todos |
| 3 | Python local + GPT imagen | imagen | todos |
| 4 | GPT + Canva (semi-manual) | la ignora | 4:5 (resto reexportado) |
| 5 | Scraping Gemini web | imagen | 4:5 (resto reexportado) |
| – | Claude + Canva (desactivado) | la ignora | 4:5 |
| – | Scraping ChatGPT web (desactivado) | imagen | 4:5 |

### Pasar un motor de simulado a real

Todos los motores arrancan **simulados**. Para usar uno de verdad: cargá la clave que necesita en
*Configuración → Claves*, apagá su simulación en *Configuración → Simulación* y guardá.

- **1 · GPT + HTML** (`OPENAI_API_KEY`): la Responses API devuelve el texto final de cada slide en JSON
  (título, texto, etiqueta, CTA, caption y hashtags). Se renderiza `plantilla.html` con Playwright en 4:5, 9:16 y
  1:1, y un PDF vectorial para LinkedIn. Modelo en *Configuración → Modelos* (`openai_texto`).
- **2 · Claude + HTML** (`ANTHROPIC_API_KEY`): mismo flujo con la API de Anthropic (`claude-opus-5-5` por defecto,
  `anthropic_effort` configurable). Si el modelo declina un pedido, la API lo reintenta en el modelo de respaldo
  recomendado y el costo se calcula con el modelo que respondió.
- **3 · Python + GPT imagen** (`OPENAI_API_KEY`): una llamada a la API de imágenes por slide y por formato,
  con la plantilla (y la referencia) como imágenes de entrada. Por defecto genera 4:5, 9:16 y 1:1 (15 imágenes
  para 5 slides); en *Configuración → Límites* podés dejar solo `4x5` y reexportar el resto para gastar un tercio.
- **4 · GPT + Canva** (`OPENAI_API_KEY`): deja `canva/bulk-create.csv` (una fila por carrusel:
  `slide1_titulo`, `slide1_texto`, …). En Canva: *Apps → Bulk create → subir CSV*, conectá cada campo con su
  texto, generá y descargá los slides (PNG, ZIP o PDF). En el Dashboard, *Subir resultado* en la cola.
- **5 · Gemini web**: tocá *Sesión* en la tarjeta del motor, iniciá sesión en la ventana que se abre y cerrala.
  El perfil queda en `data/navegador/gemini_web/`. Usa tu Google Chrome si está instalado (Google suele bloquear
  el login en Chromium); se cambia en *Configuración → Selectores web*. Solo trabaja dentro de las franjas
  horarias. Si Gemini cambia su diseño, corregí los selectores CSS en esa misma pantalla.

## Costos

Los motores de API guardan por pieza los tokens / imágenes que devuelve cada respuesta y los multiplican por la
tabla de *Configuración → Precios* (editable; los valores precargados son de referencia, verificalos contra la
página de precios de cada proveedor). Se muestra costo por pieza, por día, por motor y por carrusel aprobado.

## Ritmo humano (motores de navegador)

Configurable en *Configuración → Ritmo humano*: espera al cargar 2–6 s, escritura 40–120 ms por letra, 30–120 s
entre prompts, 5–12 min entre carruseles, descanso de 15–30 min cada 4–5, tope de 8–10 por día y franjas
9–11, 14–16 y 20–22. Ante captcha, aviso de actividad inusual o límite de uso, el motor se pausa 24 h y avisa
(dashboard + notificación del sistema). Los motores de API solo esperan 1–3 s entre pedidos y reintentan con
espera creciente.

## Tests

```bash
pytest -q        # no llaman a ninguna API: usan clientes y una página de chat falsos
```

## Estructura

```
flaks_lab/
  main.py            API local (FastAPI) + archivos estáticos
  orchestrator.py    lectura del Sheet, colas por motor, ritmo humano, bloqueos, costos, meta.json
  engines/           un archivo por motor (plugins) · base.py = interfaz · _navegador.py = base de chats web
  sheets.py          Google Sheets (cuenta de servicio, solo lectura) y modo demo
  plantillas.py      plantilla de marca por cliente y referencias (Drive o /referencias)
  redaccion.py       instrucciones y esquema JSON del texto de los carruseles
  render.py          plantilla HTML → PNG / PDF con Playwright
  formats.py         reexportación 4:5 → 9:16, 1:1, PDF y reel MP4
  costs.py, stats.py costos y métricas del ranking
  static/            frontend (HTML + CSS + JS, sin build)
plantillas/{cliente}/  brand.json, plantilla.html, plantilla.png
referencias/{cliente}/ imágenes de referencia
output/                resultados (se crea al generar)
data/                  base SQLite, perfiles de navegador (se crea al iniciar)
```
