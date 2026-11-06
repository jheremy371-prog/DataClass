"""Frontend Streamlit de DataClass. Consume la API protegida mediante JWT."""
import html
import json
import os
import secrets
import time
from datetime import date, timedelta

import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from api import validaciones

load_dotenv()

API_URL = os.getenv("DATACLASS_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")

st.set_page_config(
    page_title="DataClass | Radar Académico",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root { --dc-navy:#12305A; --dc-blue:#1769AA; --dc-cyan:#27A9E0; --dc-pale:#EAF4FC; --dc-ink:#172B4D; --dc-muted:#4A6283; }
.stApp { background: linear-gradient(180deg,#F5F9FE 0%,#FFFFFF 44%); color:var(--dc-ink); }
header[data-testid="stHeader"] { background:transparent; }
.block-container { padding-top:3.5rem; padding-bottom:2.5rem; max-width:1450px; }
[data-testid="stSidebar"] { background:linear-gradient(180deg,#12305A 0%,#174A7E 100%); }
[data-testid="stSidebar"] * { color:#F7FBFF !important; }
[data-testid="stSidebar"] [data-baseweb="select"] * { color:#172B4D !important; }
.dc-hero { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; background:linear-gradient(120deg,#12305A 0%,#1769AA 70%,#27A9E0 100%); padding:1.35rem 1.7rem; border-radius:18px; color:white; margin-bottom:1.2rem; box-shadow:0 12px 28px rgba(18,48,90,.14); }
.dc-hero h1 { color:white; margin:0; padding:0; line-height:1.15; font-size:1.85rem; font-weight:750; letter-spacing:-.03em; }
.dc-hero p { color:#E4F3FF; margin:.45rem 0 0 0; font-size:1rem; }
.dc-eyebrow { text-transform:uppercase; font-size:.72rem; letter-spacing:.14em; color:#BFEAFF; font-weight:700; margin-bottom:.45rem; }
div[data-testid="stMetric"] { background:white; border:1px solid #D9E7F5; border-left:4px solid var(--dc-cyan); border-radius:14px; padding:1rem 1.1rem; box-shadow:0 4px 14px rgba(18,48,90,.045); }
div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] * { color:var(--dc-muted) !important; font-weight:600; }
div[data-testid="stMetricValue"], div[data-testid="stMetricValue"] * { color:var(--dc-navy) !important; font-weight:750; }
.stButton > button, .stFormSubmitButton > button { border-radius:9px; font-weight:650; border:1px solid #1769AA; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background:linear-gradient(100deg,#1769AA,#1688C9); color:white; }
[data-testid="stTabs"] button[aria-selected="true"] { color:#1769AA; border-bottom-color:#27A9E0; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; background:white; }
.dc-note { border-left:4px solid #27A9E0; padding:.75rem 1rem; background:#EAF4FC; border-radius:0 10px 10px 0; color:#23466B; }
.dc-login { background:white; border:1px solid #D9E7F5; border-radius:18px; padding:1.5rem; box-shadow:0 14px 38px rgba(18,48,90,.09); }
[data-testid="stDataFrame"] { border:1px solid #D9E7F5; border-radius:12px; overflow:hidden; }
footer {visibility:hidden;}
.stApp, .stApp button, .stApp input, .stApp textarea { font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif; }
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { border-radius:10px !important; }
.dc-brand { display:flex; align-items:center; gap:.75rem; padding:.3rem 0 1.3rem; }
.dc-logo { width:42px; height:42px; border-radius:12px; background:linear-gradient(135deg,#27A9E0,#1769AA); display:flex; align-items:center; justify-content:center; font-weight:800; font-size:1.25rem; color:white; box-shadow:0 8px 18px rgba(0,0,0,.25); }
.dc-brand-name { font-size:1.3rem; font-weight:800; letter-spacing:-.02em; line-height:1.1; }
.dc-brand-sub { font-size:.74rem; opacity:.75; }
.dc-user { display:flex; gap:.75rem; align-items:center; background:rgba(255,255,255,.09); border-radius:12px; padding:.7rem .85rem; margin-bottom:.4rem; }
.dc-avatar { width:36px; height:36px; border-radius:50%; background:#27A9E0; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:.9rem; flex-shrink:0; }
.dc-user-name { font-size:.88rem; font-weight:650; line-height:1.2; }
.dc-user-role { font-size:.68rem; letter-spacing:.1em; text-transform:uppercase; opacity:.7; }
.dc-status { display:flex; align-items:center; gap:.55rem; font-size:.78rem; opacity:.9; }
.dc-dot { width:8px; height:8px; border-radius:50%; background:#3DDC97; box-shadow:0 0 0 3px rgba(61,220,151,.22); }
.dc-kpi { background:white; border:1px solid #DDE8F4; border-radius:16px; padding:1.1rem 1.25rem; box-shadow:0 1px 2px rgba(18,48,90,.04), 0 8px 22px rgba(18,48,90,.05); height:100%; }
.dc-kpi-top { display:flex; justify-content:space-between; align-items:center; }
.dc-kpi-label { font-size:.74rem; font-weight:700; color:#5B7190; text-transform:uppercase; letter-spacing:.07em; }
.dc-kpi-icon { width:34px; height:34px; border-radius:10px; display:flex; align-items:center; justify-content:center; }
.dc-kpi-icon svg { width:18px; height:18px; }
.dc-kpi-value { font-size:2.3rem; font-weight:800; color:#12305A; letter-spacing:-.03em; margin:.55rem 0 .15rem; line-height:1; }
.dc-kpi-sub { font-size:.82rem; color:#6B7F99; }
.dc-section { font-size:1.08rem; font-weight:750; color:#12305A; margin:.1rem 0 0; letter-spacing:-.01em; }
.dc-section-sub { font-size:.85rem; color:#6B7F99; margin:.1rem 0 .7rem; }
.dc-alert { background:#FFF5F5; border:1px solid #F5C2C2; border-left:4px solid #D64545; border-radius:12px; padding:.85rem 1.1rem; color:#7A1F1F; margin:1rem 0 .2rem; font-size:.93rem; }
.dc-hero-date { font-size:.78rem; font-weight:600; color:#DDF1FF; background:rgba(255,255,255,.14); padding:.4rem .85rem; border-radius:999px; white-space:nowrap; }
[data-testid="stAppDeployButton"], .stDeployButton { display:none; }
.dc-nav-title { font-size:.72rem; font-weight:700; letter-spacing:.14em; opacity:.65; margin:.9rem 0 .5rem .2rem; }
[data-testid="stSidebar"] [class*="st-key-nav_"] button { background:transparent !important; border:none !important; box-shadow:none !important; border-radius:10px; padding:.62rem .85rem; margin-bottom:.1rem; }
[data-testid="stSidebar"] [class*="st-key-nav_"] button > div { justify-content:flex-start; width:100%; }
[data-testid="stSidebar"] [class*="st-key-nav_"] button:hover { background:rgba(255,255,255,.09) !important; }
[data-testid="stSidebar"] [class*="st-key-nav_"] button[kind="primary"] { background:rgba(39,169,224,.30) !important; font-weight:700; }
[data-testid="stSidebar"] .st-key-logout button { background:rgba(255,255,255,.08) !important; border:1px solid rgba(255,255,255,.28) !important; }
[data-testid="stSidebar"] .st-key-logout button:hover { background:rgba(255,255,255,.16) !important; }
</style>
""", unsafe_allow_html=True)

if "token" not in st.session_state:
    st.session_state.token = None
    st.session_state.debe_cambiar = False
    st.session_state.rol = None
    st.session_state.nombre_usuario = None


def cabeceras_ip_cliente():
    """Reenvía a la API la IP real del navegador (la pone el proxy inverso en X-Forwarded-For).

    Sin esto la API vería siempre 127.0.0.1 y el límite de login por IP sería compartido por toda la institución.
    """
    try:
        ip_real = validaciones.primera_ip_valida(st.context.headers.get("X-Forwarded-For"))
    except Exception:  # versiones de Streamlit sin st.context o ejecución fuera de una sesión
        ip_real = None
    return {"X-Forwarded-For": ip_real} if ip_real else {}


COOKIE_SESION = "dc_token"


def _programar_cookie(accion, token=None):
    """Pide escribir/borrar la cookie de sesión en la próxima ejecución (donde sí se dibuja el iframe)."""
    st.session_state["_cookie_op"] = (accion, token)


# Minutos sin usar la pantalla antes de cerrar la sesión (0 = sin límite). Se revisa en cada interacción.
INACTIVIDAD_MIN = int(os.getenv("DATACLASS_INACTIVIDAD_MIN", "30"))


def _vaciar_sesion():
    st.session_state.pop("_ultima_actividad", None)
    st.session_state.token = None
    st.session_state.rol = None
    st.session_state.nombre_usuario = None
    st.session_state.debe_cambiar = False
    _programar_cookie("borrar")


def cerrar_sesion():
    """Cierra la sesión: primero se invalida el token en la API (si no, seguiría valiendo hasta 8 h) y luego se limpia todo."""
    if st.session_state.get("token"):
        try:
            requests.post(f"{API_URL}/auth/cerrar-sesion", headers={"Authorization": f"Bearer {st.session_state.token}", **cabeceras_ip_cliente()}, timeout=4)
        except requests.RequestException:
            pass  # sin conexión: igual se cierra aquí; el token vencerá solo
    _vaciar_sesion()


def vigilar_inactividad():
    """Cierra la sesión si pasó más de INACTIVIDAD_MIN minutos desde la última interacción (evita pantallas abiertas con datos)."""
    ahora = time.time()
    ultimo = st.session_state.get("_ultima_actividad")
    if INACTIVIDAD_MIN > 0 and ultimo and ahora - ultimo > INACTIVIDAD_MIN * 60:
        cerrar_sesion()
        st.session_state["_aviso_inactividad"] = True
        st.rerun()
    st.session_state["_ultima_actividad"] = ahora


def aplicar_cookie_pendiente():
    """Inyecta el JS mínimo que guarda o borra la cookie (8 h, SameSite=Strict, solo en este sitio)."""
    op = st.session_state.pop("_cookie_op", None)
    if not op:
        return
    accion, token = op
    if accion == "guardar" and token:
        js = (f"document.cookie = '{COOKIE_SESION}=' + encodeURIComponent({json.dumps(token)}) + '; path=/; max-age=28800; SameSite=Strict'"
              " + (window.parent.location.protocol === 'https:' ? '; Secure' : '');")  # Secure solo viaja por HTTPS
    else:
        js = (f"document.cookie = '{COOKIE_SESION}=; path=/; max-age=0; SameSite=Strict'"
              " + (window.parent.location.protocol === 'https:' ? '; Secure' : '');")
    components.html(f"<script>try{{const d=window.parent.document;{js.replace('document.cookie','d.cookie')}}}catch(e){{}}</script>", height=0)


def restaurar_sesion_desde_cookie():
    """Tras recargar la página, recupera la sesión si la cookie trae un token que la API aún acepta."""
    if st.session_state.token or st.session_state.get("_cookie_revisada"):
        return
    st.session_state["_cookie_revisada"] = True
    try:
        token = st.context.cookies.get(COOKIE_SESION)
    except Exception:
        token = None
    if not token:
        return
    try:
        r = requests.get(f"{API_URL}/auth/sesion", headers={"Authorization": f"Bearer {token}", **cabeceras_ip_cliente()}, timeout=8)
    except requests.RequestException:
        return
    if r.ok:
        d = r.json()
        st.session_state.token = token
        st.session_state.rol = d["rol"]
        st.session_state.nombre_usuario = d["nombre_completo"]
        st.session_state.debe_cambiar = bool(d.get("debe_cambiar"))
    else:
        _programar_cookie("borrar")



def api_request(method, path, **kwargs):
    headers = {**cabeceras_ip_cliente(), **kwargs.pop("headers", {})}
    timeout = kwargs.pop("timeout", 8)
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        response = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        st.error(f"No se pudo conectar con DataClass API: {exc}")
        return None
    if response.status_code == 401 and path != "/auth/login":
        _vaciar_sesion()
        st.warning("La sesión venció o se cerró desde otro lugar. Inicia sesión nuevamente.")
        st.rerun()
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        st.error(f"La API respondió {response.status_code}: {detail}")
        return None
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


@st.cache_data(ttl=20, show_spinner=False)
def estado_servicio():
    """Estado real de la API (público, sin token). None si no responde."""
    try:
        r = requests.get(f"{API_URL}/estado", timeout=3)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def aviso_modelo(estado):
    """Aviso permanente cuando el modelo es de demostración (H-01)."""
    modelo = (estado or {}).get("modelo") or {}
    if not modelo.get("sintetico"):
        return
    if modelo.get("evaluacion_automatica_activa"):
        st.error("**MODO DEMOSTRACIÓN.** El semáforo y las alertas automáticas vienen de un modelo entrenado con datos inventados. No los uses para decidir sobre estudiantes reales.")
    else:
        st.warning("**Semáforo de riesgo desactivado.** El modelo disponible es de demostración (datos sintéticos), por eso no se calcula el riesgo ni se crean alertas automáticas. Las alertas e intervenciones manuales siguen disponibles.")


def get_students():
    result = api_request("GET", "/estudiantes", params={"limite": 500})
    if result is None:
        return pd.DataFrame()
    items = result.get("items", []) if isinstance(result, dict) else result
    return pd.DataFrame(items)


DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_hoy():
    d = date.today()
    return f"{DIAS[d.weekday()]}, {d.day} de {MESES[d.month - 1]} de {d.year}"


def hero(title, subtitle, eyebrow="RADAR ACADÉMICO"):
    st.markdown(
        f'<div class="dc-hero"><div><div class="dc-eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>'
        f'<div class="dc-hero-date">{fecha_hoy()}</div></div>',
        unsafe_allow_html=True,
    )


def no_data(message):
    st.info(message)


def section(title, subtitle=""):
    st.markdown(f'<div class="dc-section">{title}</div><div class="dc-section-sub">{subtitle}</div>', unsafe_allow_html=True)


IMPORT_PLANTILLAS = {
    "estudiantes": ("plantilla_estudiantes.csv", "nombre_completo,id_estudiante,dni,aula,telefono_apoderado\nAna Pérez Rojas,,12345678,1° SECUNDARIA A,987654321\n"),
    "aulas": ("plantilla_aulas.csv", "grado,secciones,materias\n1° Secundaria,A;B;C,Matemática;Comunicación;Ciencia y Tecnología\n2° Secundaria,A;B,Matemática;Comunicación\n"),
    "calificaciones": ("plantilla_calificaciones.csv", "id_estudiante,curso_modulo,nota_obtenida,periodo_evaluacion\nEST-001,Matemática,14.5,2026-II\n"),
    "asistencias": ("plantilla_asistencias.csv", "id_estudiante,fecha,estado_asistencia\nEST-001,2026-10-01,presente\n"),
}


def df_seguro_csv(df):
    """Copia del DataFrame con los textos que empiezan con = + - @ neutralizados, para exportar a CSV/Excel."""
    return df.map(lambda x: _celda_segura(x) if isinstance(x, str) else x)


def _celda_segura(valor):
    """Evita que Excel interprete como fórmula un texto que empieza con = + - @ al abrir el CSV de errores."""
    texto = str(valor)
    return "'" + texto if texto.startswith(("=", "+", "-", "@")) else texto


@st.cache_data(show_spinner=False)
def _plantilla_xlsx(tipo):
    """El .xlsx se genera una sola vez por tipo (tarda ~0,2 s y Streamlit vuelve a ejecutar la página en cada clic)."""
    from api import plantillas

    return plantillas.crear_plantilla_xlsx(tipo)


def render_importacion(tipo, clave):
    """Carga masiva en dos pasos: validar (no guarda nada) y confirmar. Todo o nada: con errores no se guarda."""
    import hashlib

    nombres = {"estudiantes": "estudiantes", "calificaciones": "calificaciones", "asistencias": "asistencias", "aulas": "aulas y materias"}
    st.caption(
        f"Sube un archivo CSV o Excel (.xlsx) de {nombres[tipo]}. Primero se valida sin guardar nada; si todo está bien, "
        "confirmas la importación. Si hay algún error no se guarda ninguna fila. Volver a subir el mismo archivo no duplica datos."
    )
    if tipo == "aulas":
        st.caption("Una fila por año o grado: sus secciones y las materias de su malla, separadas por punto y coma (;). "
                   "La plantilla trae una hoja «Instrucciones» con ejemplos y la hoja «Datos» lista para llenar.")
    elif tipo == "estudiantes":
        st.caption("La plantilla trae una hoja «Instrucciones» y la hoja «Datos» lista para llenar (el DNI ya tiene formato Texto). "
                   "Deja vacía la columna id_estudiante para que el sistema asigne los IDs solo. Si ya creaste las aulas, el aula debe existir.")
    else:
        st.caption("La plantilla de Excel trae una hoja «Instrucciones» y la hoja «Datos» lista para llenar.")
    nombre_plantilla, contenido_plantilla = IMPORT_PLANTILLAS[tipo]
    col_xlsx, col_csv = st.columns(2)
    col_xlsx.download_button(
        "Descargar plantilla Excel (con instrucciones)", _plantilla_xlsx(tipo), file_name=f"plantilla_{tipo}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"imp_plantilla_xlsx_{clave}",
        icon=":material/download:", type="primary", use_container_width=True)
    col_csv.download_button(
        "Plantilla CSV simple", ("\ufeff" + contenido_plantilla).encode("utf-8"), file_name=nombre_plantilla,
        mime="text/csv", key=f"imp_plantilla_csv_{clave}", icon=":material/description:", use_container_width=True)
    archivo = st.file_uploader("Archivo CSV o Excel", type=["csv", "xlsx"], key=f"imp_archivo_{clave}")
    estado_clave = f"imp_estado_{clave}"
    if archivo is None:
        st.session_state.pop(estado_clave, None)
        return
    contenido = archivo.getvalue()
    firma = (archivo.name, hashlib.sha256(contenido).hexdigest())
    mime = "text/csv" if archivo.name.lower().endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    archivos = {"archivo": (archivo.name, contenido, mime)}

    if st.button("Validar archivo", key=f"imp_validar_{clave}", type="primary", icon=":material/fact_check:"):
        informe = api_request("POST", f"/importaciones/{tipo}", params={"simular": "true"}, files=archivos, timeout=120)
        st.session_state[estado_clave] = {"firma": firma, "informe": informe} if informe is not None else None
    estado = st.session_state.get(estado_clave)
    if not estado or estado["firma"] != firma:
        return

    informe = estado["informe"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Filas leídas", informe["total_filas"])
    c2.metric("Nuevas", informe["nuevas"])
    c3.metric("Ya existían", informe["ya_existentes"])
    c4.metric("Filas con error", informe["filas_con_error"])

    if informe["advertencias_total"]:
        with st.expander(f"Avisos ({informe['advertencias_total']})"):
            st.dataframe(pd.DataFrame(informe["advertencias"]).rename(columns={"fila": "Fila", "motivo": "Aviso"}), hide_index=True, use_container_width=True)

    if informe["errores_total"]:
        st.error(f"Hay {informe['errores_total']} error(es). No se guardó nada. Corrige el archivo y vuelve a validarlo.")
        tabla = pd.DataFrame(informe["errores"]).rename(columns={"fila": "Fila", "campo": "Campo", "motivo": "Qué corregir"})
        st.dataframe(tabla, hide_index=True, use_container_width=True)
        if informe["errores_total"] > len(informe["errores"]):
            st.caption(f"Se muestran los primeros {len(informe['errores'])} errores.")
        seguro = tabla.map(_celda_segura)
        st.download_button("Descargar errores (CSV)", ("\ufeff" + seguro.to_csv(index=False)).encode("utf-8"),
                           file_name=f"errores_{tipo}.csv", mime="text/csv", key=f"imp_errores_{clave}", icon=":material/download:")
    elif informe["nuevas"] == 0:
        st.info("No hay nada nuevo que importar: todas las filas ya existen.")
    else:
        st.success(f"Archivo válido: se importarán {informe['nuevas']} registro(s) nuevo(s).")
        if st.button(f"Confirmar e importar {informe['nuevas']} registro(s)", key=f"imp_confirmar_{clave}", type="primary", icon=":material/upload:"):
            resultado = api_request("POST", f"/importaciones/{tipo}", params={"simular": "false"}, files=archivos, timeout=300)
            st.session_state.pop(estado_clave, None)
            if resultado is not None:
                if resultado.get("aplicado"):
                    st.session_state.flash = f"Importación completada: {resultado['nuevas']} registro(s) guardado(s)."
                    st.rerun()
                else:
                    st.warning("El archivo cambió desde la validación y no se guardó nada. Vuelve a validarlo.")


def aulas_para_docentes():
    """Aulas que se pueden asignar a un docente: las del catálogo; sin catálogo, las que ya tienen estudiantes."""
    nombres = [x["nombre"] for x in (api_request("GET", "/aulas") or [])]
    if nombres:
        return nombres
    if not students.empty and "aula" in students.columns:
        return sorted(students["aula"].dropna().astype(str).unique().tolist())
    return []


def render_aulas_y_materias():
    """Aulas por año/grado y malla curricular (materias de cada año). Solo directivos; cada institución define la suya."""
    st.caption(
        "Cada institución tiene su propia estructura: crea los años (grados) con sus secciones y las materias de cada año. "
        "Cada aula (año + sección) usa las materias de su año. Para cargar todo de una vez usa la carga masiva, al final."
    )
    grados = api_request("GET", "/grados") or []
    aulas = api_request("GET", "/aulas") or []

    section("1. Crear aulas por año", "Cada sección crea un aula: «1° Secundaria» + A, B → «1° SECUNDARIA A» y «1° SECUNDARIA B».")
    with st.form("form_crear_aulas", clear_on_submit=True):
        c1, c2 = st.columns(2)
        grado_nuevo = c1.text_input("Año o grado", placeholder="1° Secundaria", max_chars=40)
        secciones_txt = c2.text_input("Secciones (separadas por coma)", placeholder="A, B, C", max_chars=200)
        crear = st.form_submit_button("Crear aulas", type="primary")
    if crear:
        lista = [s.strip() for s in secciones_txt.replace(";", ",").split(",") if s.strip()]
        if not grado_nuevo.strip() or not lista:
            st.warning("Escribe el año y al menos una sección.")
        else:
            res = api_request("POST", "/aulas", json={"grado": grado_nuevo.strip(), "secciones": lista})
            if res is not None:
                creadas = ", ".join(res["creadas"]) or "ninguna (ya existían)"
                st.session_state.flash = f"Aulas creadas: {creadas}."
                st.rerun()

    section("2. Materias de cada año (malla curricular)", "Todas las secciones de un año comparten sus materias.")
    if not grados:
        no_data("Aún no hay años creados. Crea las aulas arriba o usa la carga masiva.")
    else:
        grado_sel = st.selectbox("Año o grado", [g["grado"] for g in grados], key="malla_grado")
        info = next(g for g in grados if g["grado"] == grado_sel)
        st.caption("Secciones: " + (", ".join(info["secciones"]) or "ninguna todavía"))
        if info["materias"]:
            st.markdown("**Materias:** " + " · ".join(info["materias"]))
        else:
            st.info("Este año todavía no tiene materias. Añádelas aquí abajo.")
        with st.form("form_agregar_materias", clear_on_submit=True):
            materias_txt = st.text_input("Añadir materias (separadas por punto y coma)", placeholder="Matemática; Comunicación; Inglés", max_chars=600)
            anadir = st.form_submit_button("Añadir a la malla")
        if anadir:
            nuevas = [m.strip() for m in materias_txt.split(";") if m.strip()]
            if not nuevas:
                st.warning("Escribe al menos una materia.")
            else:
                agregadas = []
                for materia in nuevas:
                    res = api_request("POST", "/grados/materias", json={"grado": grado_sel, "materia": materia})
                    if res is None:
                        break
                    if res["nueva"]:
                        agregadas.append(res["materia"])
                else:
                    st.session_state.flash = ("Materias añadidas: " + ", ".join(agregadas) + ".") if agregadas else "Esas materias ya estaban en la malla."
                    st.rerun()
        if info["materias"]:
            quitar = st.multiselect("Quitar materias de este año", info["materias"], key=f"malla_quitar_{grado_sel}")
            if quitar and st.button("Quitar las seleccionadas", key=f"malla_quitar_btn_{grado_sel}"):
                if all(api_request("DELETE", "/grados/materias", params={"grado": grado_sel, "materia": m}) is not None for m in quitar):
                    st.session_state.flash = "Materias quitadas de la malla. Las notas ya registradas se conservan."
                    st.rerun()

    section("3. Aulas creadas", "Las materias de cada aula vienen de su año.")
    if not aulas:
        no_data("No hay aulas creadas.")
    else:
        tabla = pd.DataFrame([
            {"Aula": x["nombre"], "Año": x["grado"], "Sección": x["seccion"],
             "Materias": ", ".join(x["materias"]) or "—", "Estudiantes": x["estudiantes"]}
            for x in aulas
        ])
        st.dataframe(tabla, hide_index=True, use_container_width=True)
        vacias = [x["nombre"] for x in aulas if x["estudiantes"] == 0]
        if vacias:
            with st.expander("Eliminar un aula sin estudiantes"):
                borrar = st.selectbox("Aula", vacias, key="aula_borrar")
                if st.button("Eliminar aula", key="aula_borrar_btn"):
                    if api_request("DELETE", "/aulas", params={"nombre": borrar}) is not None:
                        st.session_state.flash = f"Aula {borrar} eliminada."
                        st.rerun()

    section("4. Carga masiva de aulas y materias", "Descarga la plantilla, llénala con la estructura de tu institución y súbela.")
    render_importacion("aulas", "aulas")


KPI_ICONS = {
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "alert": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "sync": '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
}
KPI_TONES = {"blue": ("#EAF4FC", "#1769AA"), "red": ("#FDE8E8", "#D64545"), "green": ("#E6F5EE", "#2E9E6B"), "amber": ("#FDF3DC", "#C98A00")}


def kpi(container, label, value, sub, icon, tone="blue"):
    bg, fg = KPI_TONES[tone]
    svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{KPI_ICONS[icon]}</svg>'
    container.markdown(
        f'<div class="dc-kpi"><div class="dc-kpi-top"><span class="dc-kpi-label">{label}</span>'
        f'<span class="dc-kpi-icon" style="background:{bg};color:{fg}">{svg}</span></div>'
        f'<div class="dc-kpi-value">{value}</div><div class="dc-kpi-sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


RISK_ORDER = ["Bajo", "Medio", "Alto"]
RISK_COLORS = {"Bajo": "#2E9E6B", "Medio": "#E8A317", "Alto": "#D64545", "Sin clasificar": "#9AA9BC"}
RISK_ALIASES = {"verde": "Bajo", "low": "Bajo", "amarillo": "Medio", "medium": "Medio", "rojo": "Alto", "high": "Alto"}
RISK_CELL_STYLE = {
    "Bajo": "background-color:#E6F5EE;color:#1E6B47;font-weight:600",
    "Medio": "background-color:#FDF3DC;color:#8A5A00;font-weight:600",
    "Alto": "background-color:#FDE8E8;color:#9B1C1C;font-weight:600",
}
NOTA_APROBATORIA = 11
RISK_PRIORITY = {"Alto": 0, "Medio": 1, "Bajo": 2, "Sin clasificar": 3}
TABLE_LABELS = {
    "id_estudiante": "ID",
    "nombre_completo": "Estudiante",
    "dni": "DNI",
    "aula": "Aula",
    "telefono_apoderado": "Teléfono apoderado",
    "riesgo_desercion": "Riesgo de deserción",
    "riesgo_reprobacion": "Riesgo de reprobación",
    "is_synced": "Sincronizado",
    "nivel_riesgo": "Nivel de riesgo",
}


def norm_risk(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "Sin clasificar"
    text = str(value).strip()
    if not text:
        return "Sin clasificar"
    if text.lower() in RISK_ALIASES:
        return RISK_ALIASES[text.lower()]
    return text.capitalize() if text.capitalize() in RISK_ORDER else "Sin clasificar"


def risk_chart(series):
    counts = series.map(norm_risk).value_counts()
    order = RISK_ORDER + (["Sin clasificar"] if counts.get("Sin clasificar", 0) else [])
    data = pd.DataFrame({"Nivel": order, "Estudiantes": [int(counts.get(n, 0)) for n in order]})
    total_n = max(int(data["Estudiantes"].sum()), 1)
    data["Etiqueta"] = [f"{n} · {n / total_n:.0%}" for n in data["Estudiantes"]]
    yscale = alt.Scale(domainMin=0, domainMax=max(data["Estudiantes"].max() * 1.3, 1))
    base = alt.Chart(data).encode(
        x=alt.X("Nivel:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=13, ticks=False)),
    )
    bars = base.mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8, size=64).encode(
        y=alt.Y("Estudiantes:Q", title=None, scale=yscale, axis=None),
        color=alt.Color("Nivel:N", scale=alt.Scale(domain=order, range=[RISK_COLORS[n] for n in order]), legend=None),
        tooltip=["Nivel", "Estudiantes"],
    )
    labels = base.mark_text(dy=-10, fontSize=14, fontWeight="bold", color="#12305A").encode(
        y=alt.Y("Estudiantes:Q", scale=yscale), text="Etiqueta:N"
    )
    chart = (
        (bars + labels)
        .properties(height=250)
        .configure(background="rgba(0,0,0,0)")
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#4A6283", gridColor="#E6EEF7", domain=False)
    )
    st.altair_chart(chart, theme=None)


def render_table(df):
    data = df.copy()
    # «Sincronizado» (con Firestore) no se muestra: la nube está apagada y la columna confundiría con el modo sin conexión.
    data = data.drop(columns=["is_synced"], errors="ignore")
    config = {}
    for col in data.columns:
        if col == "is_synced":
            config[col] = st.column_config.CheckboxColumn(TABLE_LABELS[col])
        elif col in TABLE_LABELS:
            config[col] = st.column_config.Column(TABLE_LABELS[col])
    risk_cols = [c for c in ("riesgo_desercion", "riesgo_reprobacion", "nivel_riesgo") if c in data.columns]
    shown = data.style.map(lambda v: RISK_CELL_STYLE.get(norm_risk(v), ""), subset=risk_cols) if risk_cols else data
    st.dataframe(shown, column_config=config, width='stretch', hide_index=True)


def render_cambiar_password(forzado=False):
    """Formulario para cambiar la propia contraseña. Con forzado=True es lo único que se puede hacer."""
    st.caption("Mínimo 12 caracteres. Evita tu correo y las claves repetitivas. Al cambiarla se cierran tus otras sesiones.")
    with st.form("form_cambiar_password", clear_on_submit=True):
        actual = st.text_input("Contraseña actual" + (" (la temporal que recibiste)" if forzado else ""), type="password")
        nueva = st.text_input("Contraseña nueva", type="password")
        repetida = st.text_input("Repite la contraseña nueva", type="password")
        enviar = st.form_submit_button("Cambiar contraseña", type="primary")
    if enviar:
        if not actual or not nueva:
            st.warning("Completa todos los campos.")
        elif nueva != repetida:
            st.warning("Las contraseñas nuevas no coinciden.")
        else:
            res = api_request("POST", "/auth/cambiar-password", json={"password_actual": actual, "password_nueva": nueva})
            if res:
                st.session_state.token = res["access_token"]
                st.session_state.debe_cambiar = False
                _programar_cookie("guardar", res["access_token"])
                st.session_state.flash = "Contraseña actualizada."
                st.rerun()


restaurar_sesion_desde_cookie()
aplicar_cookie_pendiente()

if not st.session_state.token:
    left, center, right = st.columns([1, 1.05, 1])
    with center:
        st.markdown('<div style="text-align:center;margin:1.5rem 0 1rem"><div style="display:flex;justify-content:center;margin-bottom:.7rem"><div class="dc-logo" style="width:58px;height:58px;font-size:1.8rem;border-radius:16px">D</div></div><div style="font-size:2rem;font-weight:800;color:#12305A;letter-spacing:-.02em">DataClass</div><div style="color:#58708D">Radar Académico · Alertas tempranas</div></div>', unsafe_allow_html=True)
        if st.session_state.pop("_aviso_inactividad", False):
            st.info(f"Cerramos tu sesión por inactividad ({INACTIVIDAD_MIN} min). Inicia sesión de nuevo.")
        with st.container(border=True):
            st.subheader("Bienvenido")
            st.caption("Ingresa con tu cuenta institucional para continuar.")
            with st.form("login_form"):
                correo = st.text_input("Correo institucional", placeholder="usuario@institucion.edu")
                password = st.text_input("Contraseña", type="password")
                submit = st.form_submit_button("Iniciar sesión", type="primary", use_container_width=True)
            if submit:
                if not correo.strip() or not password:
                    st.warning("Ingresa tu correo y contraseña.")
                else:
                    try:
                        response = requests.post(
                            f"{API_URL}/auth/login", data={"username": correo.strip(), "password": password},
                            headers=cabeceras_ip_cliente(), timeout=8,
                        )
                        if response.ok:
                            data = response.json()
                            st.session_state.token = data["access_token"]
                            st.session_state.rol = data["rol"]
                            st.session_state.nombre_usuario = data["nombre_completo"]
                            st.session_state.debe_cambiar = bool(data.get("debe_cambiar"))
                            _programar_cookie("guardar", data["access_token"])
                            st.rerun()
                        elif response.status_code == 429:
                            try:
                                st.error(response.json().get("detail", "Demasiados intentos. Espera unos minutos."))
                            except ValueError:
                                st.error("Demasiados intentos. Espera unos minutos.")
                        else:
                            st.error("No se pudo iniciar sesión. Revisa tus credenciales o la configuración del administrador.")
                    except requests.RequestException as exc:
                        st.error(f"No se pudo conectar con el backend: {exc}")
    st.stop()

vigilar_inactividad()

if st.session_state.get("debe_cambiar"):
    _, centro, _ = st.columns([1, 1.4, 1])
    with centro:
        st.subheader("Debes cambiar tu contraseña")
        st.info("Tu cuenta tiene una contraseña temporal. Elige una propia para continuar.")
        render_cambiar_password(forzado=True)
        if st.button("Cerrar sesión", key="logout_forzado"):
            cerrar_sesion()
            st.rerun()
    st.stop()

with st.sidebar:
    nombre_sb = html.escape(st.session_state.nombre_usuario or "Usuario")
    iniciales = "".join(p[0] for p in nombre_sb.split()[:2]).upper() or "U"
    st.markdown(
        '<div class="dc-brand"><div class="dc-logo">D</div><div><div class="dc-brand-name">DataClass</div><div class="dc-brand-sub">Inteligencia académica</div></div></div>'
        f'<div class="dc-user"><div class="dc-avatar">{iniciales}</div><div><div class="dc-user-name">{nombre_sb}</div><div class="dc-user-role">{html.escape(st.session_state.rol or "")}</div></div></div>',
        unsafe_allow_html=True,
    )
    st.divider()

    rol_actual = str(st.session_state.get("rol", "")).lower()

    if rol_actual == "docente":
        NAV_ITEMS = [
            ("Dashboard", ":material/dashboard:"),
            ("Estudiantes", ":material/groups:"),
            ("Perfil del estudiante", ":material/badge:"),
            ("Registro académico", ":material/edit_note:"),
            ("Alertas e intervenciones", ":material/notifications_active:"),
            ("Mi cuenta", ":material/lock:"),
        ]
    elif rol_actual == "directivo":
        NAV_ITEMS = [
            ("Dashboard", ":material/dashboard:"),
            ("Estudiantes", ":material/groups:"),
            ("Perfil del estudiante", ":material/badge:"),
            ("Registro académico", ":material/edit_note:"),
            ("Alertas e intervenciones", ":material/notifications_active:"),
            ("Gestión de docentes", ":material/badge:"),
            ("Indicadores institucionales", ":material/monitoring:"),
            ("Mi cuenta", ":material/lock:"),
        ]
    else:
        NAV_ITEMS = [
            ("Dashboard", ":material/dashboard:"),
            ("Mi cuenta", ":material/lock:"),
        ]

    st.markdown('<div class="dc-nav-title">NAVEGACIÓN SEGURA (RBAC)</div>', unsafe_allow_html=True)
    
    nombres_permitidos = [item[0] for item in NAV_ITEMS]
    if "menu" not in st.session_state:
        # Al recargar la página la sesión de Streamlit es nueva: la página en la que estabas viaja en la URL (?p=...).
        pedida = st.query_params.get("p")
        if pedida in nombres_permitidos:
            st.session_state.menu = pedida
    if "menu" not in st.session_state or st.session_state.menu not in nombres_permitidos:
        st.session_state.menu = nombres_permitidos[0]

    for i, (nombre_menu, icono) in enumerate(NAV_ITEMS):
        activo = st.session_state.menu == nombre_menu
        if st.button(nombre_menu, key=f"nav_{i}", icon=icono, type="primary" if activo else "secondary", use_container_width=True) and not activo:
            st.session_state.menu = nombre_menu
            st.rerun()
            
    menu = st.session_state.menu
    if st.query_params.get("p") != menu:
        st.query_params["p"] = menu
    
    st.divider()
    estado_api = estado_servicio()
    if estado_api and estado_api.get("api") == "operativa":
        st.markdown('<div class="dc-status"><span class="dc-dot"></span>API conectada</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="dc-status">⚠️ API no disponible</div>', unsafe_allow_html=True)
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
    if st.button("Cerrar sesión", key="logout", icon=":material/logout:", use_container_width=True):
        cerrar_sesion()
        st.rerun()

students = get_students()
aviso_modelo(estado_api)
if st.session_state.get("flash"):
    st.success(st.session_state.pop("flash"))

if menu == "Dashboard":
    hero("Panorama académico", "Una vista clara para priorizar el acompañamiento y dar seguimiento a los estudiantes.")
    if students.empty:
        no_data("No hay estudiantes disponibles o la API no devolvió registros. Registra un estudiante en la sección Estudiantes.")
    else:
        total = len(students)
        risk = students.get("riesgo_desercion", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
        high = int(risk.isin(["alto", "rojo", "high"]).sum())
        if st.session_state.rol == "directivo":
            _, col_boton = st.columns([4, 1])
            if col_boton.button("Recalcular semáforo", icon=":material/autorenew:", use_container_width=True):
                res = api_request("POST", "/analitica/evaluar-todos")
                if res is not None:
                    niveles = res["por_nivel"]
                    st.session_state.flash = (
                        f"Semáforo actualizado: {res['evaluados']} evaluados (Alto {niveles['Alto']}, Medio {niveles['Medio']}, "
                        f"Bajo {niveles['Bajo']}), {res['alertas_creadas']} alertas nuevas y {res['sin_datos_suficientes']} sin datos suficientes."
                    )
                    st.rerun()
        alerts_total = len(api_request("GET", "/alertas", params={"limite": 500}) or [])
        pct = lambda n: f"{n / total:.0%} del total"
        k1, k2, k3, k4 = st.columns(4)
        kpi(k1, "Estudiantes", total, "registrados en el padrón", "users")
        kpi(k2, "Riesgo alto", high, f"{pct(high)} · deserción", "alert", "red" if high else "green")
        n_aulas = int(students["aula"].nunique()) if "aula" in students else 0
        kpi(k3, "Aulas", n_aulas, "con estudiantes registrados", "users", "blue")
        kpi(k4, "Alertas", alerts_total, "registradas en seguimiento", "bell", "amber" if alerts_total else "blue")
        if {"riesgo_desercion", "riesgo_reprobacion"} <= set(students.columns):
            criticos = int(((students["riesgo_desercion"].map(norm_risk) == "Alto") & (students["riesgo_reprobacion"].map(norm_risk) == "Alto")).sum())
            if criticos:
                st.markdown(f'<div class="dc-alert"><b>Atención prioritaria:</b> {criticos} estudiante{"s" if criticos != 1 else ""} con riesgo alto de deserción y de reprobación. Aparece{"n" if criticos != 1 else ""} primero en la tabla inferior.</div>', unsafe_allow_html=True)
        st.markdown("<div style='height:.9rem'></div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                section("Riesgo de deserción", "Estudiantes por nivel de riesgo registrado")
                if "riesgo_desercion" in students:
                    risk_chart(students["riesgo_desercion"])
                else:
                    no_data("Sin datos de riesgo de deserción.")
        with c2:
            with st.container(border=True):
                section("Riesgo de reprobación", "Estudiantes por nivel de riesgo registrado")
                if "riesgo_reprobacion" in students:
                    risk_chart(students["riesgo_reprobacion"])
                else:
                    no_data("Sin datos de riesgo de reprobación.")
        st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
        section("Estudiantes para revisar", "Ordenados por prioridad: primero los casos de mayor riesgo")
        f1, f2 = st.columns([3, 1])
        with f1:
            filtro_aula = st.selectbox("Aula", ["Todas"] + sorted(students["aula"].dropna().astype(str).unique().tolist()) if "aula" in students else ["Todas"])
        with f2:
            st.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
            solo_alto = st.toggle("Solo riesgo alto")
        view = students.copy()
        if filtro_aula != "Todas" and "aula" in view:
            view = view[view.aula.astype(str) == filtro_aula]
        risk_columns = [c for c in ("riesgo_desercion", "riesgo_reprobacion") if c in view]
        if risk_columns:
            niveles = pd.concat([view[c].map(norm_risk) for c in risk_columns], axis=1)
            if solo_alto:
                view = view[(niveles == "Alto").any(axis=1)]
                niveles = niveles.loc[view.index]
            prioridad = niveles.apply(lambda col: col.map(RISK_PRIORITY)).sum(axis=1)
            view = view.loc[prioridad.sort_values(kind="stable").index]
        cols = [c for c in ["id_estudiante", "nombre_completo", "aula", "riesgo_desercion", "riesgo_reprobacion"] if c in view]
        if view.empty:
            no_data("Ningún estudiante coincide con los filtros seleccionados.")
        else:
            render_table(view[cols])

elif menu == "Estudiantes":
    hero("Gestión de estudiantes", "Consulta el padrón institucional y registra nuevos estudiantes.", "GESTIÓN ACADÉMICA")
    _pestanas_est = st.tabs(["Listado", "Nuevo estudiante"] + (["Aulas y materias", "Carga masiva"] if rol_actual == "directivo" else []))
    tab_list, tab_create = _pestanas_est[0], _pestanas_est[1]
    tab_aulas_est = _pestanas_est[2] if len(_pestanas_est) > 3 else None
    tab_import_est = _pestanas_est[3] if len(_pestanas_est) > 3 else None
    with tab_list:
        if students.empty:
            no_data("No hay estudiantes registrados.")
        else:
            search = st.text_input("Buscar por nombre, ID o aula")
            view = students.copy()
            if search.strip():
                mask = view.astype(str).apply(lambda col: col.str.contains(search.strip(), case=False, na=False, regex=False)).any(axis=1)
                view = view[mask]
            render_table(view)
            if st.session_state.get("rol") == "directivo":
                # Dos pasos para que la exportación quede en la bitácora (la descarga en sí ocurre en el navegador).
                firma = (len(view), tuple(view.columns))
                if st.session_state.get("_export_listo") != firma:
                    if st.button("Preparar exportación CSV", icon=":material/download:"):
                        if api_request("POST", "/exportaciones", json={"recurso": "estudiantes", "filas": int(len(view))}) is not None:
                            st.session_state["_export_listo"] = firma
                            st.rerun()
                else:
                    st.download_button("Descargar listado CSV", df_seguro_csv(view).to_csv(index=False).encode("utf-8-sig"), "dataclass_estudiantes.csv", "text/csv")
            else:
                st.caption("La exportación del listado está disponible solo para directivos.")
    with tab_create:
        if st.session_state.get("rol") != "directivo":
            st.info("Solo el personal directivo puede registrar estudiantes.")
        else:
            # Tras guardar, se vacían los campos antes de volver a dibujarlos.
            if st.session_state.pop("_reset_nuevo_estudiante", False):
                for clave in ("nuevo_nombre", "nuevo_dni", "nuevo_aula", "nuevo_tel", "nuevo_dni_aviso"):
                    st.session_state[clave] = ""
                st.session_state.pop("nuevo_aula_sel", None)
                st.session_state.pop("_dni_reniec", None)

            def _filtrar_dni():
                """Se ejecuta al confirmar el campo (Enter o al salir de él): deja solo dígitos y avisa si quitó algo."""
                escrito = st.session_state.get("nuevo_dni", "")
                limpio = validaciones.solo_digitos_ascii(escrito)[:8]
                st.session_state["nuevo_dni"] = limpio
                st.session_state["nuevo_dni_aviso"] = (
                    "El DNI solo admite números del 0 al 9; se quitaron los demás caracteres." if limpio != escrito.strip() else ""
                )

            def _verificar_reniec():
                """Callback del botón: corre ANTES de dibujar los campos, así puede rellenar 'Nombre completo' sin error."""
                try:
                    dni_ok = validaciones.normalizar_dni(st.session_state.get("nuevo_dni", ""))
                except ValueError as exc:
                    st.session_state["_reniec_aviso"] = ("error", f"DNI: {exc}")
                    return
                if dni_ok is None:
                    st.session_state["_reniec_aviso"] = ("warning", "Escribe primero un DNI de 8 dígitos.")
                    return
                verificado = api_request("POST", "/personas/validar-dni", json={"dni": dni_ok})
                if verificado:
                    d = verificado["datos"]
                    nombre_reniec = " ".join(p for p in (d.get("nombres"), d.get("apellido_paterno"), d.get("apellido_materno")) if p).title()
                    st.session_state["_dni_reniec"] = {"dni": dni_ok, "nombre": nombre_reniec}
                    st.session_state["nuevo_nombre"] = nombre_reniec

            aulas_cat = api_request("GET", "/aulas") or []
            a, b = st.columns(2)
            with a:
                st.caption("El ID del estudiante se genera solo al guardar (por ejemplo 2026-0001).")
                nombre = st.text_input("Nombre completo *", key="nuevo_nombre", max_chars=150)
                dni = st.text_input(
                    "DNI * (8 dígitos)", key="nuevo_dni", max_chars=8, on_change=_filtrar_dni,
                    help="Solo números, exactamente 8 dígitos. Los demás caracteres se eliminan al confirmar el campo.",
                )
                if st.session_state.get("nuevo_dni_aviso"):
                    st.warning(st.session_state["nuevo_dni_aviso"])
                st.button("Verificar en RENIEC", key="nuevo_verificar_dni", on_click=_verificar_reniec)
                aviso = st.session_state.pop("_reniec_aviso", None)
                if aviso:
                    getattr(st, aviso[0])(aviso[1])
                reniec = st.session_state.get("_dni_reniec")
                if reniec and reniec["dni"] == dni:
                    st.success(f"RENIEC: {reniec['nombre']} (nombre completado automáticamente)")
            with b:
                nombres_aulas = [x["nombre"] for x in aulas_cat]
                if nombres_aulas:
                    sin_aula = "— Sin aula —"
                    elegida = st.selectbox("Aula / sección", [sin_aula] + nombres_aulas, key="nuevo_aula_sel")
                    aula = "" if elegida == sin_aula else elegida
                    if aula:
                        materias_aula = next((x["materias"] for x in aulas_cat if x["nombre"] == aula), [])
                        st.caption("Materias del aula: " + (", ".join(materias_aula) or "aún no definidas (agrégalas en «Aulas y materias»)."))
                else:
                    aula = st.text_input("Aula / sección", key="nuevo_aula", max_chars=50)
                    st.caption("Aún no hay aulas creadas. Créalas por año en la pestaña «Aulas y materias».")
                telefono = st.text_input("Teléfono del apoderado (opcional)", key="nuevo_tel", max_chars=20)

            if st.button("Guardar estudiante", type="primary", key="nuevo_guardar"):
                errores, datos = [], {}
                for campo, funcion, valor in (
                    ("Nombre completo", validaciones.normalizar_nombre, nombre),
                    ("Teléfono del apoderado", validaciones.normalizar_telefono, telefono),
                ):
                    try:
                        datos[campo] = funcion(valor)
                    except ValueError as exc:
                        errores.append(f"{campo}: {exc}")
                try:
                    datos["DNI"] = validaciones.normalizar_dni(dni)
                    if datos["DNI"] is None:
                        errores.append("DNI: es obligatorio y debe tener exactamente 8 dígitos numéricos.")
                except ValueError as exc:
                    errores.append(f"DNI: {exc}")
                if errores:
                    for mensaje in errores:
                        st.error(mensaje)
                else:
                    payload = {
                        "nombre_completo": datos["Nombre completo"],
                        "dni": datos["DNI"],
                        "aula": aula.strip() or None,
                        "telefono_apoderado": datos["Teléfono del apoderado"],
                    }
                    result = api_request("POST", "/estudiantes", json=payload)
                    if result is not None:
                        # flash sobrevive al st.rerun(); un st.success() directo se perdería.
                        st.session_state.flash = f"Estudiante registrado correctamente con el ID {result.get('id_estudiante', '')}."
                        st.session_state["_reset_nuevo_estudiante"] = True
                        st.rerun()

    if tab_aulas_est is not None:
        with tab_aulas_est:
            render_aulas_y_materias()

    if tab_import_est is not None:
        with tab_import_est:
            render_importacion("estudiantes", "estudiantes")

elif menu == "Perfil del estudiante":
    hero("Perfil del estudiante", "Ficha individual con rendimiento, asistencia y seguimiento.", "SEGUIMIENTO INDIVIDUAL")
    if students.empty:
        no_data("No hay estudiantes registrados.")
    else:
        opciones = {}
        for _, fila in students.iterrows():
            dni_txt = f" · DNI {fila['dni']}" if isinstance(fila.get("dni"), str) and fila.get("dni") else ""
            opciones[f"{fila['nombre_completo']} · {fila['id_estudiante']}{dni_txt}"] = str(fila["id_estudiante"])
        elegido = st.selectbox("Buscar estudiante (escribe nombre, ID o DNI)", list(opciones))
        sid = opciones[elegido]
        ficha = students[students["id_estudiante"].astype(str) == sid].iloc[0]
        detalle = api_request("GET", f"/estudiantes/{sid}") or {}
        notas = api_request("GET", f"/estudiantes/{sid}/calificaciones") or []
        asistencias = api_request("GET", f"/estudiantes/{sid}/asistencias") or []
        alertas_est = api_request("GET", "/alertas", params={"id_estudiante": sid, "limite": 100}) or []
        intervenciones_est = api_request("GET", "/intervenciones", params={"id_estudiante": sid, "limite": 100}) or []

        def valor(v):
            return "—" if v is None or (not isinstance(v, str) and pd.isna(v)) or v == "" else html.escape(str(v))

        def insignia(etiqueta, v):
            nivel = norm_risk(v)
            fondo, texto = {"Alto": ("#FDE8E8", "#9B1C1C"), "Medio": ("#FDF3DC", "#8A5A00"), "Bajo": ("#E6F5EE", "#1E6B47")}.get(nivel, ("#EEF2F7", "#4A6283"))
            etiqueta_nivel = nivel if nivel != "Sin clasificar" else (valor(v) if valor(v) != "—" else "Pendiente")
            return f'<span style="background:{fondo};color:{texto};padding:.3rem .75rem;border-radius:999px;font-size:.78rem;font-weight:700">{etiqueta}: {etiqueta_nivel}</span>'

        def dato(etiqueta, v):
            return f'<div><div class="dc-kpi-label">{etiqueta}</div><div style="font-weight:650;color:#12305A">{valor(v)}</div></div>'

        nombre_ficha = str(ficha["nombre_completo"])
        iniciales_ficha = "".join(p[0] for p in nombre_ficha.split()[:2]).upper() or "?"
        st.markdown(
            '<div class="dc-kpi" style="display:flex;gap:1.3rem;align-items:center;flex-wrap:wrap">'
            f'<div class="dc-avatar" style="width:64px;height:64px;font-size:1.4rem;color:white">{html.escape(iniciales_ficha)}</div>'
            f'<div style="flex:1;min-width:220px"><div style="font-size:1.35rem;font-weight:800;color:#12305A">{html.escape(nombre_ficha)}</div>'
            f'<div class="dc-kpi-sub">ID {valor(ficha["id_estudiante"])} · Aula {valor(ficha.get("aula"))}</div></div>'
            f'<div style="display:flex;gap:2rem;flex-wrap:wrap">{dato("DNI", ficha.get("dni"))}{dato("Teléfono del apoderado", detalle.get("telefono_apoderado"))}</div>'
            f'<div style="display:flex;gap:.5rem;flex-wrap:wrap">{insignia("Deserción", ficha.get("riesgo_desercion"))}{insignia("Reprobación", ficha.get("riesgo_reprobacion"))}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        df_notas = pd.DataFrame(notas)
        df_asist = pd.DataFrame(asistencias)
        promedio = df_notas["nota_obtenida"].mean() if not df_notas.empty else None
        conteo = df_asist["estado_asistencia"].value_counts().to_dict() if not df_asist.empty else {}
        asistio = conteo.get("presente", 0) + conteo.get("tardanza", 0)
        penalizable = asistio + conteo.get("falta", 0)
        pct_asistencia = round(100 * asistio / penalizable) if penalizable else None
        abiertas = sum(1 for a in alertas_est if a.get("estado") in ("pendiente", "en_seguimiento"))
        st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)
        k1, k2, k3, k4 = st.columns(4)
        kpi(k1, "Promedio general", f"{promedio:.1f}" if promedio is not None else "—", f"sobre 20 · {len(notas)} nota(s)", "book", "red" if promedio is not None and promedio < NOTA_APROBATORIA else "blue")
        kpi(k2, "Asistencia", f"{pct_asistencia}%" if pct_asistencia is not None else "—", "faltas justificadas no penalizan", "calendar")
        kpi(k3, "Registros de asistencia", len(asistencias), f"{conteo.get('falta', 0)} falta(s) · {conteo.get('tardanza', 0)} tardanza(s)", "users")
        kpi(k4, "Alertas abiertas", abiertas, f"{len(alertas_est)} en total", "bell", "amber" if abiertas else "green")
        st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

        tab_rend, tab_asist, tab_seg = st.tabs(["Rendimiento", "Asistencia", "Seguimiento"])
        with tab_rend:
            if df_notas.empty:
                no_data("Este estudiante aún no tiene calificaciones registradas.")
            else:
                por_curso = df_notas.groupby("curso_modulo", as_index=False)["nota_obtenida"].mean().rename(columns={"curso_modulo": "Curso", "nota_obtenida": "Promedio"})
                por_curso["Promedio"] = por_curso["Promedio"].round(1)
                grafico = (
                    alt.Chart(por_curso).mark_bar(cornerRadiusEnd=6, size=26).encode(
                        y=alt.Y("Curso:N", sort="-x", title=None),
                        x=alt.X("Promedio:Q", scale=alt.Scale(domain=[0, 20]), title="Promedio (0–20)"),
                        color=alt.condition(alt.datum.Promedio < NOTA_APROBATORIA, alt.value("#D64545"), alt.value("#1769AA")),
                        tooltip=["Curso", "Promedio"],
                    ).properties(height=max(120, 46 * len(por_curso))).configure(background="rgba(0,0,0,0)").configure_view(strokeWidth=0)
                )
                st.altair_chart(grafico, theme=None)
                st.dataframe(df_notas[["curso_modulo", "periodo_evaluacion", "nota_obtenida"]].rename(columns={"curso_modulo": "Curso", "periodo_evaluacion": "Periodo", "nota_obtenida": "Nota"}), use_container_width=True, hide_index=True)
        with tab_asist:
            if df_asist.empty:
                no_data("Este estudiante aún no tiene asistencias registradas.")
            else:
                estados = ["presente", "tardanza", "falta", "justificada"]
                nombres = [e.capitalize() for e in estados]
                datos_asist = pd.DataFrame({"Estado": nombres, "Días": [int(conteo.get(e, 0)) for e in estados]})
                base = alt.Chart(datos_asist).encode(x=alt.X("Estado:N", sort=nombres, title=None, axis=alt.Axis(labelAngle=0, ticks=False)))
                barras = base.mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8, size=64).encode(
                    y=alt.Y("Días:Q", axis=None, scale=alt.Scale(domainMin=0, domainMax=max(datos_asist["Días"].max() * 1.3, 1))),
                    color=alt.Color("Estado:N", scale=alt.Scale(domain=nombres, range=["#2E9E6B", "#E8A317", "#D64545", "#9AA9BC"]), legend=None),
                    tooltip=["Estado", "Días"],
                )
                etiquetas = base.mark_text(dy=-10, fontSize=14, fontWeight="bold", color="#12305A").encode(y=alt.Y("Días:Q", scale=alt.Scale(domainMin=0, domainMax=max(datos_asist["Días"].max() * 1.3, 1))), text="Días:Q")
                st.altair_chart((barras + etiquetas).properties(height=230).configure(background="rgba(0,0,0,0)").configure_view(strokeWidth=0), theme=None)
        with tab_seg:
            section("Alertas", "Señales de riesgo registradas para este estudiante")
            if alertas_est:
                render_table(pd.DataFrame(alertas_est))
            else:
                no_data("Sin alertas registradas.")
            section("Intervenciones", "Acciones de acompañamiento documentadas")
            if intervenciones_est:
                st.dataframe(pd.DataFrame(intervenciones_est), use_container_width=True, hide_index=True)
            else:
                no_data("Sin intervenciones registradas.")

elif menu == "Registro académico":
    hero("Registro académico", "Guarda calificaciones y asistencia con validación de datos.", "SEGUIMIENTO")
    tab_grade, tab_attendance, tab_fix, tab_import_reg = st.tabs(["Calificaciones", "Asistencias", "Corregir registros", "Carga masiva"])
    with tab_grade:
        student_ids = students.get("id_estudiante", pd.Series(dtype=str)).astype(str).tolist() if not students.empty else []
        # El estudiante se elige fuera del formulario para poder mostrar las materias de SU aula.
        id_est = st.selectbox("Estudiante", student_ids, key="nota_estudiante") if student_ids else st.text_input("ID del estudiante", key="nota_estudiante_txt")
        materias_est = []
        if student_ids and "aula" in students.columns:
            aula_est = students.loc[students["id_estudiante"].astype(str) == str(id_est), "aula"]
            aula_est = aula_est.iloc[0] if len(aula_est) else None
            if isinstance(aula_est, str) and aula_est:
                materias_est = next((x["materias"] for x in (api_request("GET", "/aulas") or []) if x["nombre"] == aula_est), [])
        with st.form("crear_nota"):
            c1, c2 = st.columns(2)
            with c1:
                if materias_est:
                    otra = "Otra (escribir)"
                    curso_sel = st.selectbox("Materia", materias_est + [otra])
                    curso_otro = st.text_input("Si elegiste «Otra», escribe la materia")
                    curso = curso_otro if curso_sel == otra else curso_sel
                else:
                    curso = st.text_input("Curso o módulo")
                periodo = st.selectbox("Periodo académico", ["2026-I", "2026-II", "Semestre I", "Semestre II", "Módulo 1", "Módulo 2"])
            with c2:
                nota = st.number_input("Nota (0 a 20)", min_value=0.0, max_value=20.0, value=14.0, step=0.5)
            submit_grade = st.form_submit_button("Guardar calificación", type="primary")

        if submit_grade:
            if not id_est or not curso.strip():
                st.warning("Completa estudiante y curso.")
            else:
                result = api_request("POST", "/calificaciones", json={"id_estudiante": id_est, "curso_modulo": curso.strip(), "nota_obtenida": nota, "periodo_evaluacion": periodo})
                if result is not None:
                    st.success("Calificación guardada.")
    with tab_attendance:
        with st.form("crear_asistencia"):
            student_ids = students.get("id_estudiante", pd.Series(dtype=str)).astype(str).tolist() if not students.empty else []
            id_asist = st.selectbox("Estudiante", student_ids, key="asistencia_estudiante") if student_ids else st.text_input("ID del estudiante", key="asistencia_id")
            fecha = st.date_input("Fecha", value=date.today())
            estado = st.selectbox("Estado", ["presente", "tardanza", "falta", "justificada"], format_func=lambda x: {"presente":"Presente", "tardanza":"Tardanza", "falta":"Falta", "justificada":"Justificada"}[x])
            submit_attendance = st.form_submit_button("Registrar asistencia", type="primary")
        if submit_attendance:
            if not id_asist:
                st.warning("Selecciona un estudiante.")
            else:
                result = api_request("POST", "/asistencias", json={"id_estudiante": id_asist, "fecha": fecha.isoformat(), "estado_asistencia": estado})
                if result is not None:
                    st.success("Asistencia registrada.")

    with tab_fix:
        st.caption("Corrige o elimina una nota o una asistencia mal registrada. Cada cambio queda en la bitácora.")
        ids_fix = students.get("id_estudiante", pd.Series(dtype=str)).astype(str).tolist() if not students.empty else []
        if not ids_fix:
            no_data("No hay estudiantes disponibles.")
        else:
            id_fix = st.selectbox("Estudiante", ids_fix, key="fix_estudiante")
            tipo_fix = st.radio("Qué quieres corregir", ["calificaciones", "asistencias"], horizontal=True, key="fix_tipo",
                                format_func=lambda x: "Una calificación" if x == "calificaciones" else "Una asistencia")
            registros = api_request("GET", f"/estudiantes/{id_fix}/{tipo_fix}") or []
            if not registros:
                no_data("Este estudiante no tiene registros de este tipo.")
            elif tipo_fix == "calificaciones":
                opciones = {r["id_calificacion"]: f"{r['periodo_evaluacion']} · {r['curso_modulo']} · nota {r['nota_obtenida']:g}" for r in registros}
                elegido = st.selectbox("Registro", list(opciones), format_func=opciones.get, key="fix_nota_sel")
                actual = next(r for r in registros if r["id_calificacion"] == elegido)
                with st.form(f"fix_nota_{elegido}"):
                    nueva_nota = st.number_input("Nota (0 a 20)", min_value=0.0, max_value=20.0, value=float(actual["nota_obtenida"]), step=0.5)
                    nuevo_curso = st.text_input("Curso o módulo", value=actual["curso_modulo"])
                    nuevo_periodo = st.text_input("Periodo académico", value=actual["periodo_evaluacion"])
                    guardar_fix = st.form_submit_button("Guardar corrección", type="primary")
                if guardar_fix:
                    cambios = {}
                    if float(nueva_nota) != float(actual["nota_obtenida"]):
                        cambios["nota_obtenida"] = nueva_nota
                    if nuevo_curso.strip() != actual["curso_modulo"]:
                        cambios["curso_modulo"] = nuevo_curso.strip()
                    if nuevo_periodo.strip() != actual["periodo_evaluacion"]:
                        cambios["periodo_evaluacion"] = nuevo_periodo.strip()
                    if not cambios:
                        st.info("No cambiaste nada.")
                    elif api_request("PATCH", f"/calificaciones/{elegido}", json=cambios) is not None:
                        st.success("Calificación corregida.")
                        st.rerun()
                confirmar = st.checkbox("Confirmo que quiero eliminar esta calificación", key=f"fix_nota_conf_{elegido}")
                if st.button("Eliminar calificación", disabled=not confirmar, key=f"fix_nota_del_{elegido}"):
                    if api_request("DELETE", f"/calificaciones/{elegido}") is not None:
                        st.success("Calificación eliminada.")
                        st.rerun()
            else:
                opciones = {r["id_asistencia"]: f"{r['fecha']} · {r['estado_asistencia']}" for r in registros}
                elegido = st.selectbox("Registro", list(opciones), format_func=opciones.get, key="fix_asist_sel")
                actual = next(r for r in registros if r["id_asistencia"] == elegido)
                estados = ["presente", "tardanza", "falta", "justificada"]
                with st.form(f"fix_asist_{elegido}"):
                    nueva_fecha = st.date_input("Fecha", value=date.fromisoformat(actual["fecha"]), max_value=date.today())
                    nuevo_estado = st.selectbox("Estado", estados, index=estados.index(actual["estado_asistencia"]), format_func=str.title)
                    guardar_fix = st.form_submit_button("Guardar corrección", type="primary")
                if guardar_fix:
                    cambios = {}
                    if nueva_fecha.isoformat() != actual["fecha"]:
                        cambios["fecha"] = nueva_fecha.isoformat()
                    if nuevo_estado != actual["estado_asistencia"]:
                        cambios["estado_asistencia"] = nuevo_estado
                    if not cambios:
                        st.info("No cambiaste nada.")
                    elif api_request("PATCH", f"/asistencias/{elegido}", json=cambios) is not None:
                        st.success("Asistencia corregida.")
                        st.rerun()
                confirmar = st.checkbox("Confirmo que quiero eliminar esta asistencia", key=f"fix_asist_conf_{elegido}")
                if st.button("Eliminar asistencia", disabled=not confirmar, key=f"fix_asist_del_{elegido}"):
                    if api_request("DELETE", f"/asistencias/{elegido}") is not None:
                        st.success("Asistencia eliminada.")
                        st.rerun()

    with tab_import_reg:
        tipo_carga = st.radio("¿Qué vas a importar?", ["calificaciones", "asistencias"], horizontal=True,
                              format_func=lambda x: {"calificaciones": "Calificaciones", "asistencias": "Asistencias"}[x], key="imp_tipo_registro")
        render_importacion(tipo_carga, f"registro_{tipo_carga}")

elif menu == "Alertas e intervenciones":
    hero("Alertas e intervenciones", "Registra señales de riesgo y documenta el acompañamiento del tutor.", "ACOMPAÑAMIENTO")
    tab_alert, tab_intervention, tab_history = st.tabs(["Nueva alerta", "Nueva intervención", "Historial y seguimiento"])
    student_ids = students.get("id_estudiante", pd.Series(dtype=str)).astype(str).tolist() if not students.empty else []
    ESTADOS_ALERTA = {"pendiente": "Pendiente", "en_seguimiento": "En seguimiento", "resuelta": "Resuelta", "descartada": "Descartada"}
    alerts = api_request("GET", "/alertas", params={"limite": 500}) or []
    abiertas = [a for a in alerts if a.get("estado") in ("pendiente", "en_seguimiento")]

    with tab_alert:
        st.caption("Alerta manual: la crea una persona, no el modelo, y queda marcada como «manual».")
        with st.form("crear_alerta"):
            sid = st.selectbox("Estudiante", student_ids) if student_ids else st.text_input("ID del estudiante")
            c1, c2 = st.columns(2)
            with c1:
                kind = st.selectbox("Tipo", ["bajo_rendimiento", "desercion"], format_func=lambda x: "Bajo rendimiento" if x == "bajo_rendimiento" else "Riesgo de deserción")
            with c2:
                level = st.selectbox("Nivel", ["alto", "medio", "bajo"], format_func=str.title)
            description = st.text_area("Descripción / evidencia")
            submit_alert = st.form_submit_button("Guardar alerta", type="primary")
        if submit_alert:
            if not sid or len(description.strip()) < 5:
                st.warning("Selecciona un estudiante e incluye una descripción.")
            else:
                payload = {"id_estudiante": sid, "tipo_alerta": kind, "nivel_riesgo": level, "descripcion": description.strip()}
                result = api_request("POST", "/alertas", json=payload)
                if result is not None:
                    st.success("Alerta registrada.")
                    st.rerun()

    with tab_intervention:
        st.caption("Documenta qué se hizo con el estudiante. El tutor es quien ha iniciado sesión.")
        opciones_alerta = {"Sin alerta asociada": None}
        for a in abiertas:
            opciones_alerta[f"#{a['id_alerta']} · {a['id_estudiante']} · {str(a.get('nivel_riesgo', '')).title()} · {ESTADOS_ALERTA.get(a.get('estado'), a.get('estado'))}"] = a
        with st.form("crear_intervencion", clear_on_submit=True):
            alerta_sel = opciones_alerta[st.selectbox("Alerta asociada (opcional)", list(opciones_alerta.keys()))]
            sid_i = st.selectbox("Estudiante (si no eliges alerta)", student_ids) if student_ids else st.text_input("ID del estudiante", key="sid_int")
            c1, c2 = st.columns(2)
            with c1:
                tipo_i = st.selectbox("Tipo de intervención", ["Tutoría individual", "Contacto con el apoderado", "Reunión con el estudiante", "Derivación a psicología", "Plan de refuerzo académico", "Otro"])
                fecha_i = st.date_input("Fecha", value=date.today(), max_value=date.today())
            with c2:
                revision_i = st.date_input("Próxima revisión (opcional)", value=None, min_value=date.today())
                marcar_seg = st.checkbox("Marcar la alerta como «en seguimiento»", value=True)
            descr_i = st.text_area("Qué se hizo")
            resultado_i = st.text_area("Resultado (opcional)")
            enviar_i = st.form_submit_button("Guardar intervención", type="primary")
        if enviar_i:
            id_est = alerta_sel["id_estudiante"] if alerta_sel else sid_i
            if not id_est or len(descr_i.strip()) < 5:
                st.warning("Indica el estudiante (o una alerta) y describe lo que se hizo.")
            else:
                payload = {
                    "id_estudiante": id_est, "id_alerta": alerta_sel["id_alerta"] if alerta_sel else None,
                    "tutor": st.session_state.nombre_usuario or "Tutor", "tipo_intervencion": tipo_i,
                    "descripcion": descr_i.strip(), "fecha_intervencion": fecha_i.isoformat(),
                    "resultado": resultado_i.strip() or None,
                    "proxima_revision": revision_i.isoformat() if revision_i else None,
                }
                if api_request("POST", "/intervenciones", json=payload) is not None:
                    if alerta_sel and marcar_seg and alerta_sel.get("estado") == "pendiente":
                        api_request("PATCH", f"/alertas/{alerta_sel['id_alerta']}", json={"estado": "en_seguimiento"})
                    st.session_state.flash = "Intervención registrada."
                    st.rerun()

    with tab_history:
        section("Cambiar el estado de una alerta", "Cerrar una alerta (resuelta o descartada) permite que el sistema vuelva a avisar si el riesgo reaparece.")
        if abiertas:
            with st.form("cambiar_estado_alerta"):
                op_estado = {f"#{a['id_alerta']} · {a['id_estudiante']} · {str(a.get('nivel_riesgo', '')).title()} · {ESTADOS_ALERTA.get(a.get('estado'), a.get('estado'))}": a["id_alerta"] for a in abiertas}
                sel_alerta = st.selectbox("Alerta", list(op_estado.keys()))
                nuevo_estado = st.selectbox("Nuevo estado", list(ESTADOS_ALERTA.keys()), format_func=lambda x: ESTADOS_ALERTA[x], index=1)
                enviar_estado = st.form_submit_button("Actualizar estado", type="primary")
            if enviar_estado:
                if api_request("PATCH", f"/alertas/{op_estado[sel_alerta]}", json={"estado": nuevo_estado}) is not None:
                    st.session_state.flash = "Estado de la alerta actualizado."
                    st.rerun()
        else:
            st.caption("No hay alertas abiertas.")

        section("Alertas", "")
        if alerts:
            df_alertas = pd.DataFrame(alerts)
            if "estado" in df_alertas:
                df_alertas["estado"] = df_alertas["estado"].map(ESTADOS_ALERTA).fillna(df_alertas["estado"])
            render_table(df_alertas)
        else:
            no_data("Aún no hay alertas registradas.")

        section("Intervenciones", "Actualiza el resultado o la próxima revisión de una intervención.")
        intervenciones = api_request("GET", "/intervenciones", params={"limite": 500}) or []
        if intervenciones:
            render_table(pd.DataFrame(intervenciones))
            with st.form("editar_intervencion"):
                op_int = {f"#{i['id_intervencion']} · {i['id_estudiante']} · {i['tipo_intervencion']} · {i['fecha_intervencion']}": i["id_intervencion"] for i in intervenciones}
                sel_int = st.selectbox("Intervención", list(op_int.keys()))
                resultado_n = st.text_area("Resultado")
                revision_n = st.date_input("Próxima revisión (opcional)", value=None, key="rev_edit")
                enviar_res = st.form_submit_button("Guardar resultado", type="primary")
            if enviar_res:
                if len(resultado_n.strip()) < 2:
                    st.warning("Escribe el resultado.")
                else:
                    cuerpo = {"resultado": resultado_n.strip(), "proxima_revision": revision_n.isoformat() if revision_n else None}
                    if api_request("PATCH", f"/intervenciones/{op_int[sel_int]}", json=cuerpo) is not None:
                        st.session_state.flash = "Intervención actualizada."
                        st.rerun()
        else:
            no_data("Aún no hay intervenciones registradas.")

elif menu == "Gestión de docentes":
    hero("Supervisión de docentes y aulas", "Asigna, cambia o retira las aulas asignadas a cada docente del padrón.", "CONTROL DIRECTIVO")
    
    usuarios_list = api_request("GET", "/usuarios") or []
    docentes = [u for u in usuarios_list if u.get("rol") == "docente"]

    if "clave_temporal" in st.session_state:
        aviso = st.session_state.pop("clave_temporal")
        st.success(f"Contraseña temporal para {aviso['correo']}: **{aviso['clave']}**")
        st.caption("Cópiala ahora y entrégala por un canal seguro: no se vuelve a mostrar. La persona deberá cambiarla al entrar.")

    if not docentes:
        no_data("No hay docentes registrados en el sistema.")
    else:
        df_docentes = pd.DataFrame(docentes)
        st.subheader("Docentes registrados")
        st.dataframe(df_docentes[["id_usuario", "nombre_completo", "correo", "aula", "activo"]], use_container_width=True, hide_index=True)

        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        section("Asignar o modificar aula de docente", "Selecciona un docente para actualizar su sección asignada")

        with st.form("form_asignar_aula"):
            docente_opciones = {f"{d['nombre_completo']} ({d['correo']}) - Aula actual: {d.get('aula') or 'Ninguna'}": d["id_usuario"] for d in docentes}
            seleccion_doc = st.selectbox("Seleccionar docente", list(docente_opciones.keys()))
            uid_docente = docente_opciones[seleccion_doc]

            aulas_disponibles = aulas_para_docentes()
            nueva_aula = st.selectbox("Asignar aula", ["Ninguna (Sin aula)"] + aulas_disponibles)

            submit_aula = st.form_submit_button("Guardar asignación de aula", type="primary")

        if submit_aula:
            aula_a_guardar = None if nueva_aula.startswith("Ninguna") else nueva_aula
            res = api_request("PATCH", f"/usuarios/{uid_docente}", json={"aula": aula_a_guardar})
            if res is not None:
                st.success(f"Se actualizó correctamente el aula del docente a: {aula_a_guardar or 'Sin aula'}")
                st.rerun()

        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        section("Restablecer contraseña", "Genera una clave temporal; la persona deberá cambiarla al entrar y sus sesiones abiertas se cierran")
        with st.form("form_restablecer"):
            sel_reset = st.selectbox("Docente", list(docente_opciones.keys()), key="sel_reset")
            enviar_reset = st.form_submit_button("Generar contraseña temporal")
        if enviar_reset:
            uid_reset = docente_opciones[sel_reset]
            res = api_request("POST", f"/usuarios/{uid_reset}/restablecer-password")
            if res:
                correo_reset = next((d["correo"] for d in docentes if d["id_usuario"] == uid_reset), "")
                st.session_state.clave_temporal = {"correo": correo_reset, "clave": res["password_temporal"]}
                st.rerun()

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    section("Crear cuenta de docente", "La cuenta nace con una contraseña temporal que el docente deberá cambiar al entrar")
    with st.form("form_crear_docente", clear_on_submit=True):
        nuevo_nombre = st.text_input("Nombre completo")
        nuevo_correo = st.text_input("Correo institucional")
        _aulas_doc = aulas_para_docentes()
        if _aulas_doc:
            _elegida = st.selectbox("Aula (opcional)", ["Ninguna (Sin aula)"] + _aulas_doc)
            nueva_aula_doc = "" if _elegida.startswith("Ninguna") else _elegida
        else:
            nueva_aula_doc = st.text_input("Aula (opcional)", placeholder="A-302")
        crear_doc = st.form_submit_button("Crear docente", type="primary")
    if crear_doc:
        if not nuevo_nombre.strip() or "@" not in nuevo_correo:
            st.warning("Ingresa el nombre y un correo válido.")
        else:
            temporal = secrets.token_urlsafe(12)
            payload = {"correo": nuevo_correo.strip(), "nombre_completo": nuevo_nombre.strip(), "rol": "docente",
                       "password": temporal, "debe_cambiar": True}
            if nueva_aula_doc.strip():
                payload["aula"] = nueva_aula_doc.strip()
            res = api_request("POST", "/usuarios", json=payload)
            if res:
                st.session_state.clave_temporal = {"correo": res["correo"], "clave": temporal}
                st.rerun()

elif menu == "Mi cuenta":
    hero("Mi cuenta", "Cambia tu contraseña. Al hacerlo se cierran tus otras sesiones abiertas.", "SEGURIDAD")
    render_cambiar_password()

elif menu == "Indicadores institucionales":
    hero("Indicadores institucionales", "Explora el alcance del seguimiento y calcula escenarios financieros hipotéticos.", "GESTIÓN ESTRATÉGICA")
    total = len(students)
    alerts = api_request("GET", "/alertas", params={"limite": 500}) or []
    interventions = api_request("GET", "/intervenciones", params={"limite": 500}) or []
    c1, c2, c3 = st.columns(3)
    c1.metric("Estudiantes", total)
    c2.metric("Alertas registradas", len(alerts))
    c3.metric("Intervenciones registradas", len(interventions))
    st.subheader("Simulador de retención")
    retained = st.number_input("Estudiantes que hipotéticamente se retendrían", min_value=0, max_value=10000, value=10, step=1)
    tuition = st.number_input("Ingreso anual estimado por estudiante (S/)", min_value=0.0, value=1800.0, step=100.0)
    st.metric("Ingreso potencial estimado", f"S/ {retained * tuition:,.2f}")