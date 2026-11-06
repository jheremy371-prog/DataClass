"""Evaluación de riesgo de deserción: probabilidad del modelo -> semáforo -> alerta.

Este módulo no depende de FastAPI: recibe una conexión SQLite y el modelo ya cargado,
de modo que se puede probar de forma aislada.

Semáforo (probabilidad P de riesgo de deserción, de 0.0 a 1.0):
    Bajo  : P < 0.30
    Medio : 0.30 <= P < 0.70
    Alto  : P >= 0.70
"""
import hashlib
import hmac
import json
import os
import warnings
from typing import Any, Optional

import pandas as pd

UMBRAL_MEDIO = 0.30
UMBRAL_ALTO = 0.70
MIN_NOTAS = 1          # calificaciones mínimas para evaluar
MIN_ASISTENCIAS = 5    # registros de asistencia mínimos para evaluar (evita decidir con 1 o 2 días)
VERSION_MODELO = "experimental-0.1"
# True cuando modelo_riesgo.json declara un modelo de demostración (o no declara su origen).
# Mientras sea True no se publica el semáforo ni se crean alertas automáticas, salvo con
# DATACLASS_MODO_DEMO=1 (solo para demostraciones con datos inventados).
MODELO_SINTETICO = False
NOTA_MODELO = (
    "Modelo experimental entrenado con datos sintéticos. Úsalo como señal de apoyo "
    "y contrasta siempre el resultado con el criterio del tutor."
)

ACCIONES = {
    "Alto": "Revisar el caso de inmediato con el tutor y contactar al apoderado.",
    "Medio": "Programar una tutoría preventiva breve (unos 15 minutos) y vigilar la asistencia.",
    "Bajo": "Mantener el seguimiento académico habitual.",
}


class RiesgoError(Exception):
    """Base de los errores previsibles de la evaluación."""


class EstudianteNoEncontrado(RiesgoError):
    pass


class DatosInsuficientes(RiesgoError):
    pass


class ModeloNoDisponible(RiesgoError):
    pass


class ErrorPrediccion(RiesgoError):
    pass


class ModeloSintetico(ModeloNoDisponible):
    """El modelo cargado es de demostración: no debe decidir sobre estudiantes reales."""


def modo_demostracion() -> bool:
    return os.environ.get("DATACLASS_MODO_DEMO", "").strip() == "1"


def evaluacion_automatica_activa() -> bool:
    """False si el modelo es sintético y no se pidió explícitamente el modo demostración."""
    return not MODELO_SINTETICO or modo_demostracion()


def estado_modelo() -> dict:
    """Resumen para la interfaz: qué modelo hay y si sus resultados se están publicando."""
    return {
        "version_modelo": VERSION_MODELO,
        "sintetico": MODELO_SINTETICO,
        "modo_demostracion": modo_demostracion(),
        "evaluacion_automatica_activa": evaluacion_automatica_activa(),
    }


def huella_sha256(ruta) -> str:
    """SHA-256 (hex) de un archivo, leído por bloques."""
    resumen = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def verificar_integridad_modelo(ruta_pkl, ruta_json) -> tuple[bool, str]:
    """Comprueba que el .pkl es el que registró el entrenamiento (campo `sha256_pkl` de modelo_riesgo.json).

    pickle.load ejecuta código al abrir un archivo: nunca debe cargarse uno cuya huella no coincide. Devuelve
    (True, "") si coincide, o (False, motivo). Si el JSON no trae la huella se rechaza el modelo: vuelve a
    ejecutar modelos/entrenamiento.py (o, si confías en el archivo, calcula su huella con
    `python modelos/entrenamiento.py --sellar`).

    Límite: protege contra un .pkl cambiado o dañado, no contra quien pueda escribir también el .json.
    """
    try:
        with open(ruta_json, encoding="utf-8") as archivo:
            esperado = str(json.load(archivo).get("sha256_pkl") or "").strip().lower()
    except (OSError, ValueError, AttributeError):
        return False, "no se pudo leer modelo_riesgo.json"
    if not esperado:
        return False, "modelo_riesgo.json no trae la huella sha256_pkl"
    try:
        real = huella_sha256(ruta_pkl)
    except OSError:
        return False, "no se pudo leer el archivo del modelo"
    if not hmac.compare_digest(real, esperado):
        return False, "la huella SHA-256 del modelo no coincide con la registrada"
    return True, ""


def aplicar_metadatos_modelo(ruta_json, version_sklearn_actual: Optional[str] = None) -> Optional[dict]:
    """Lee modelo_riesgo.json (lo escribe modelos/entrenamiento.py) y ajusta la versión que se registra en las alertas.

    Devuelve los metadatos, o None si no existe o está dañado (se conserva la versión por defecto).
    Si la versión de scikit-learn con la que se entrenó difiere de la actual, emite una advertencia:
    conviene volver a entrenar el modelo en este entorno.
    """
    global VERSION_MODELO, MODELO_SINTETICO
    try:
        with open(ruta_json, encoding="utf-8") as archivo:
            metadatos = json.load(archivo)
        version = str(metadatos["version_modelo"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    VERSION_MODELO = version
    # Solo un «sintetico: false» explícito autoriza las alertas automáticas.
    MODELO_SINTETICO = metadatos.get("sintetico") is not False
    entrenado_con = metadatos.get("sklearn_version")
    if version_sklearn_actual and entrenado_con and entrenado_con != version_sklearn_actual:
        warnings.warn(
            f"El modelo se entrenó con scikit-learn {entrenado_con} y se usa con {version_sklearn_actual}. "
            "Vuelve a ejecutar modelos/entrenamiento.py en este entorno.",
            RuntimeWarning,
            stacklevel=2,
        )
    return metadatos


def clasificar_probabilidad(probabilidad: float) -> str:
    """Convierte la probabilidad en Bajo, Medio o Alto según los umbrales del semáforo."""
    if probabilidad is None or not 0.0 <= probabilidad <= 1.0:
        raise ValueError("La probabilidad debe estar entre 0.0 y 1.0.")
    if probabilidad >= UMBRAL_ALTO:
        return "Alto"
    if probabilidad >= UMBRAL_MEDIO:
        return "Medio"
    return "Bajo"


def calcular_indicadores(conexion, id_estudiante: str) -> dict:
    """Promedio de notas (0-20) y porcentaje de asistencia calculados desde la base.

    Asistió = presente + tardanza. Las faltas justificadas no penalizan: se excluyen
    del denominador. Si todas las ausencias fueron justificadas, la asistencia es 100 %.
    """
    promedio, n_notas = conexion.execute(
        "SELECT AVG(nota_obtenida), COUNT(*) FROM calificaciones WHERE id_estudiante = ?",
        (id_estudiante,),
    ).fetchone()
    conteo = {
        estado: cantidad
        for estado, cantidad in conexion.execute(
            "SELECT estado_asistencia, COUNT(*) FROM asistencias WHERE id_estudiante = ? GROUP BY estado_asistencia",
            (id_estudiante,),
        ).fetchall()
    }
    asistio = conteo.get("presente", 0) + conteo.get("tardanza", 0)
    penalizable = asistio + conteo.get("falta", 0)
    porcentaje = round(100 * asistio / penalizable) if penalizable else 100
    return {
        "notas_promedio": round(promedio, 2) if promedio is not None else None,
        "porcentaje_asistencia": int(porcentaje),
        "n_notas": int(n_notas),
        "n_asistencias": int(sum(conteo.values())),
    }


def predecir_probabilidad(modelo: Any, notas_promedio: float, porcentaje_asistencia: int) -> float:
    """Probabilidad (0-1) de la clase 'riesgo de deserción' según el modelo."""
    if modelo is None:
        raise ModeloNoDisponible("El modelo predictivo no está disponible. Ejecuta modelos/entrenamiento.py primero.")
    entrada = pd.DataFrame({"Notas_Detalladas": [notas_promedio], "Registro_Asistencia": [porcentaje_asistencia]})
    try:
        if not hasattr(modelo, "predict_proba"):
            raise ErrorPrediccion("El modelo cargado no entrega probabilidades.")
        probabilidades = modelo.predict_proba(entrada)[0]
        clases = list(modelo.classes_)
        if 1 not in clases:
            raise ErrorPrediccion("El modelo no contiene la clase de riesgo.")
        return float(probabilidades[clases.index(1)])
    except (ValueError, TypeError, AttributeError, IndexError) as exc:
        raise ErrorPrediccion("No se pudo procesar la predicción.") from exc


def evaluar_estudiante(conexion, id_estudiante: str, modelo: Any) -> dict:
    """Calcula la probabilidad, actualiza el semáforo del estudiante y crea la alerta si corresponde.

    Crea alerta de deserción cuando el nivel es Medio (preventiva) o Alto, salvo que ya exista
    una alerta abierta (pendiente o en seguimiento) del mismo nivel para ese estudiante.
    """
    fila = conexion.execute(
        "SELECT riesgo_desercion FROM estudiantes WHERE id_estudiante = ?", (id_estudiante,)
    ).fetchone()
    if fila is None:
        raise EstudianteNoEncontrado("Estudiante no encontrado.")
    riesgo_anterior = fila[0]

    if not evaluacion_automatica_activa():
        raise ModeloSintetico(
            "El modelo cargado es de demostración (entrenado con datos sintéticos): no se publica el semáforo "
            "ni se crean alertas automáticas. Entrena un modelo con datos reales autorizados."
        )

    indicadores = calcular_indicadores(conexion, id_estudiante)
    if indicadores["n_notas"] < MIN_NOTAS or indicadores["n_asistencias"] < MIN_ASISTENCIAS:
        raise DatosInsuficientes(
            f"Datos insuficientes: se necesitan al menos {MIN_NOTAS} calificación(es) y {MIN_ASISTENCIAS} "
            f"registros de asistencia (hay {indicadores['n_notas']} y {indicadores['n_asistencias']})."
        )

    probabilidad = round(
        predecir_probabilidad(modelo, indicadores["notas_promedio"], indicadores["porcentaje_asistencia"]), 4
    )
    nivel = clasificar_probabilidad(probabilidad)
    cambio = nivel != riesgo_anterior
    if cambio:
        conexion.execute(
            "UPDATE estudiantes SET riesgo_desercion = ?, is_synced = 0 WHERE id_estudiante = ?",
            (nivel, id_estudiante),
        )

    id_alerta: Optional[int] = None
    if nivel in ("Alto", "Medio"):
        abierta = conexion.execute(
            "SELECT 1 FROM alertas WHERE id_estudiante = ? AND tipo_alerta = 'desercion' AND nivel_riesgo = ? "
            "AND estado IN ('pendiente', 'en_seguimiento')",
            (id_estudiante, nivel.lower()),
        ).fetchone()
        if abierta is None:
            descripcion = (
                f"Evaluación automática: probabilidad de riesgo de deserción {probabilidad:.2f} "
                f"(promedio {indicadores['notas_promedio']}/20, asistencia {indicadores['porcentaje_asistencia']} %). "
                f"{ACCIONES[nivel]}"
            )
            cursor = conexion.execute(
                "INSERT INTO alertas (id_estudiante, tipo_alerta, nivel_riesgo, descripcion, version_modelo, probabilidad) "
                "VALUES (?, 'desercion', ?, ?, ?, ?)",
                (id_estudiante, nivel.lower(), descripcion, VERSION_MODELO, probabilidad),
            )
            id_alerta = cursor.lastrowid

    return {
        "id_estudiante": id_estudiante,
        "probabilidad_riesgo": probabilidad,
        "nivel_riesgo": nivel,
        "riesgo_anterior": riesgo_anterior,
        "cambio": cambio,
        "notas_promedio": indicadores["notas_promedio"],
        "porcentaje_asistencia": indicadores["porcentaje_asistencia"],
        "registros": {"calificaciones": indicadores["n_notas"], "asistencias": indicadores["n_asistencias"]},
        "alerta_creada": id_alerta,
        "accion_sugerida": ACCIONES[nivel],
        "version_modelo": VERSION_MODELO,
        "nota_importante": NOTA_MODELO,
    }


def evaluar_todos(conexion, modelo: Any) -> dict:
    """Evalúa a todos los estudiantes con datos suficientes y resume el resultado."""
    ids = [fila[0] for fila in conexion.execute("SELECT id_estudiante FROM estudiantes ORDER BY id_estudiante").fetchall()]
    resumen = {"evaluados": 0, "sin_datos_suficientes": 0, "alertas_creadas": 0, "por_nivel": {"Bajo": 0, "Medio": 0, "Alto": 0}}
    for id_estudiante in ids:
        try:
            resultado = evaluar_estudiante(conexion, id_estudiante, modelo)
        except DatosInsuficientes:
            resumen["sin_datos_suficientes"] += 1
            continue
        resumen["evaluados"] += 1
        resumen["por_nivel"][resultado["nivel_riesgo"]] += 1
        resumen["alertas_creadas"] += 1 if resultado["alerta_creada"] else 0
    resumen["total_estudiantes"] = len(ids)
    return resumen
