"""Entrenamiento del modelo de riesgo de deserción de DataClass.

Uso (desde la carpeta raíz del proyecto):
    python modelos/entrenamiento.py                  # usa data/historico_anonimizado.csv si existe
    python modelos/entrenamiento.py --datos ruta.csv # usa otro CSV
    python modelos/entrenamiento.py --sintetico      # datos de demostración (NO sirven para decidir nada)
    python modelos/entrenamiento.py --sellar         # solo registra la huella SHA-256 del .pkl actual en el JSON

El CSV debe tener las columnas:
    Notas_Detalladas     promedio de notas, de 0 a 20
    Registro_Asistencia  porcentaje de asistencia, de 0 a 100
    Estado_Abandono      1/0 (o Sí/No): si el estudiante terminó abandonando

No incluyas DNI, nombres ni teléfonos en el CSV: el modelo no los necesita.

Además del .pkl se guarda modelo_riesgo.json con la versión, las métricas de validación cruzada y la versión
de scikit-learn usada. La API lo lee para informar la versión real del modelo y avisar si hay desajuste.
"""
import argparse
import hashlib
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_validate

CARPETA = Path(__file__).resolve().parent
RUTA_DATOS_DEFECTO = CARPETA.parent / "data" / "historico_anonimizado.csv"
RUTA_MODELO = CARPETA / "modelo_riesgo.pkl"
RUTA_METADATOS = CARPETA / "modelo_riesgo.json"

COLUMNAS = ["Notas_Detalladas", "Registro_Asistencia"]
OBJETIVO = "Estado_Abandono"
MIN_FILAS = 50          # con menos filas las métricas no son confiables
MIN_POR_CLASE = 10      # mínimo de casos de abandono y de no abandono
PALABRAS_PERSONALES = ("dni", "nombre", "telefono", "teléfono", "correo", "email")
_BOOLEANOS = {"1": 1, "si": 1, "sí": 1, "true": 1, "0": 0, "no": 0, "false": 0}


class DatosInvalidos(Exception):
    """El conjunto de datos no sirve para entrenar (faltan columnas, pocas filas, una sola clase...)."""


def datos_sinteticos() -> pd.DataFrame:
    """Los 10 casos de demostración originales. Solo sirven para probar que el sistema funciona."""
    return pd.DataFrame({
        "Notas_Detalladas": [10.5, 15.0, 12.0, 8.0, 9.5, 16.0, 11.0, 7.5, 14.0, 6.0],
        "Registro_Asistencia": [75, 95, 80, 50, 60, 98, 85, 45, 90, 40],
        OBJETIVO: [1, 0, 0, 1, 1, 0, 0, 1, 0, 1],
    })


def cargar_datos(ruta) -> tuple[pd.DataFrame, list[str]]:
    """Lee y limpia el CSV. Devuelve (datos, avisos). Descarta filas incompletas o fuera de rango."""
    df = pd.read_csv(ruta)
    faltantes = [c for c in COLUMNAS + [OBJETIVO] if c not in df.columns]
    if faltantes:
        raise DatosInvalidos(f"Faltan columnas en el CSV: {', '.join(faltantes)}.")

    avisos = []
    personales = [c for c in df.columns if any(p in c.lower() for p in PALABRAS_PERSONALES)]
    if personales:
        avisos.append(
            f"El CSV contiene columnas que parecen datos personales ({', '.join(personales)}). "
            "No se usan para entrenar; conviene quitarlas del archivo."
        )

    df = df[COLUMNAS + [OBJETIVO]].copy()
    df[OBJETIVO] = df[OBJETIVO].astype(str).str.strip().str.lower().map(_BOOLEANOS)
    df["Notas_Detalladas"] = pd.to_numeric(df["Notas_Detalladas"], errors="coerce")
    df["Registro_Asistencia"] = pd.to_numeric(df["Registro_Asistencia"], errors="coerce")

    total = len(df)
    df = df.dropna()
    incompletas = total - len(df)
    fuera = ~(df["Notas_Detalladas"].between(0, 20) & df["Registro_Asistencia"].between(0, 100))
    n_fuera = int(fuera.sum())
    df = df[~fuera]
    if incompletas:
        avisos.append(f"Se descartaron {incompletas} fila(s) con valores vacíos o ilegibles.")
    if n_fuera:
        avisos.append(f"Se descartaron {n_fuera} fila(s) con notas fuera de 0-20 o asistencia fuera de 0-100.")
    df[OBJETIVO] = df[OBJETIVO].astype(int)
    return df.reset_index(drop=True), avisos


def validar_tamano(df: pd.DataFrame) -> None:
    """Exige un mínimo de filas y de casos por clase para que las métricas tengan sentido."""
    if len(df) < MIN_FILAS:
        raise DatosInvalidos(f"Hay {len(df)} filas útiles y se necesitan al menos {MIN_FILAS} para entrenar con confianza.")
    conteo = df[OBJETIVO].value_counts()
    if len(conteo) < 2 or conteo.min() < MIN_POR_CLASE:
        raise DatosInvalidos(
            f"Cada clase necesita al menos {MIN_POR_CLASE} casos; hay {dict(conteo)} (1 = abandonó, 0 = no)."
        )


def _crear_modelo() -> RandomForestClassifier:
    # class_weight="balanced": el abandono suele ser minoritario y no queremos que el modelo lo ignore.
    return RandomForestClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced", random_state=42)


def validar_modelo(df: pd.DataFrame) -> dict:
    """Validación cruzada estratificada. Devuelve media y desviación de cada métrica."""
    pliegues = int(min(5, df[OBJETIVO].value_counts().min()))
    resultado = cross_validate(
        _crear_modelo(), df[COLUMNAS], df[OBJETIVO],
        cv=StratifiedKFold(n_splits=pliegues, shuffle=True, random_state=42),
        scoring=["accuracy", "precision", "recall", "f1", "roc_auc"],
    )
    metricas = {"pliegues": pliegues}
    for nombre in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        valores = resultado[f"test_{nombre}"]
        metricas[nombre] = {"media": round(float(valores.mean()), 4), "desviacion": round(float(valores.std()), 4)}
    return metricas


def _huella(ruta) -> str:
    resumen = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def sellar(ruta_modelo=RUTA_MODELO, ruta_metadatos=RUTA_METADATOS) -> str:
    """Registra en el JSON la huella del .pkl actual (para un modelo entrenado antes de que existiera este control)."""
    metadatos = json.loads(Path(ruta_metadatos).read_text(encoding="utf-8"))
    metadatos["sha256_pkl"] = _huella(ruta_modelo)
    Path(ruta_metadatos).write_text(json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadatos["sha256_pkl"]


def entrenar(df: pd.DataFrame, origen: str, ruta_modelo=RUTA_MODELO, ruta_metadatos=RUTA_METADATOS, sintetico=False) -> dict:
    """Entrena con todos los datos, guarda el .pkl y el .json de metadatos, y devuelve los metadatos."""
    metricas = None
    if not sintetico:
        validar_tamano(df)
        metricas = validar_modelo(df)

    modelo = _crear_modelo().fit(df[COLUMNAS], df[OBJETIVO])
    ahora = datetime.now(timezone.utc)
    metadatos = {
        "version_modelo": f"rf-{ahora:%Y%m%d}" + ("-sintetico" if sintetico else ""),
        "fecha_entrenamiento": ahora.isoformat(timespec="seconds"),
        "origen_datos": origen,
        "sintetico": sintetico,
        "n_filas": int(len(df)),
        "n_abandono": int((df[OBJETIVO] == 1).sum()),
        "columnas": COLUMNAS,
        "sklearn_version": sklearn.__version__,
        "metricas_validacion_cruzada": metricas,
        "advertencia": (
            "Entrenado con datos sintéticos de demostración; no usar para decidir sobre estudiantes."
            if sintetico else
            "Señal de apoyo: contrastar siempre con el criterio del tutor."
        ),
    }
    with open(ruta_modelo, "wb") as archivo:
        pickle.dump(modelo, archivo)
    metadatos["sha256_pkl"] = _huella(ruta_modelo)  # la API no carga el .pkl si esta huella no coincide
    Path(ruta_metadatos).write_text(json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadatos


def imprimir_resumen(metadatos: dict) -> None:
    print(f"Modelo {metadatos['version_modelo']} entrenado con {metadatos['n_filas']} filas "
          f"({metadatos['n_abandono']} de abandono). Origen: {metadatos['origen_datos']}")
    metricas = metadatos["metricas_validacion_cruzada"]
    if metricas is None:
        print("Sin métricas: son datos sintéticos.")
    else:
        print(f"Validación cruzada ({metricas['pliegues']} pliegues):")
        for nombre in ("accuracy", "precision", "recall", "f1", "roc_auc"):
            m = metricas[nombre]
            print(f"  {nombre:<9} {m['media']:.3f} ± {m['desviacion']:.3f}")
        print("  Para deserción importa sobre todo el recall: cuántos abandonos reales detecta el modelo.")
    print(f"Advertencia: {metadatos['advertencia']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Entrena el modelo de riesgo de deserción.")
    parser.add_argument("--datos", help="CSV con el historial anonimizado.")
    parser.add_argument("--sintetico", action="store_true", help="Usar los datos de demostración.")
    parser.add_argument("--sellar", action="store_true", help="No entrena: registra en el JSON la huella SHA-256 del .pkl actual.")
    args = parser.parse_args(argv)
    if args.sellar:
        print(f"Huella registrada en {RUTA_METADATOS.name}: {sellar()}")
        return 0

    try:
        if args.sintetico:
            df, origen = datos_sinteticos(), "sintético (demostración)"
        else:
            ruta = Path(args.datos) if args.datos else RUTA_DATOS_DEFECTO
            if not ruta.is_file():
                print(f"No se encontró {ruta}.\nColoca ahí el historial anonimizado o ejecuta con --sintetico para una demostración.")
                return 1
            df, avisos = cargar_datos(ruta)
            for aviso in avisos:
                print(f"Aviso: {aviso}")
            origen = str(ruta.name)
        metadatos = entrenar(df, origen, sintetico=args.sintetico)
    except DatosInvalidos as exc:
        print(f"No se entrenó el modelo: {exc}")
        return 1

    imprimir_resumen(metadatos)
    print(f"Guardado en: {RUTA_MODELO} y {RUTA_METADATOS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
