"""Pruebas de modelos/entrenamiento.py con datos generados en memoria (no toca el modelo real)."""
import json
import pickle

import numpy as np
import pandas as pd
import pytest

from modelos import entrenamiento as ent


def dataset(n=120, semilla=0):
    """Abandono más probable con notas y asistencia bajas, con algo de ruido."""
    azar = np.random.default_rng(semilla)
    notas = azar.uniform(4, 19, n)
    asistencia = azar.uniform(30, 100, n)
    puntaje = (20 - notas) / 20 + (100 - asistencia) / 100 + azar.normal(0, 0.15, n)
    return pd.DataFrame({
        "Notas_Detalladas": notas.round(1),
        "Registro_Asistencia": asistencia.round(),
        "Estado_Abandono": (puntaje > 0.9).astype(int),
    })


def guardar_csv(tmp_path, df, nombre="datos.csv"):
    ruta = tmp_path / nombre
    df.to_csv(ruta, index=False)
    return ruta


# ---------- cargar_datos ----------

def test_carga_un_csv_valido_sin_avisos(tmp_path):
    df, avisos = ent.cargar_datos(guardar_csv(tmp_path, dataset(60)))
    assert len(df) == 60 and avisos == []
    assert list(df.columns) == ["Notas_Detalladas", "Registro_Asistencia", "Estado_Abandono"]


def test_acepta_si_no_en_el_estado_de_abandono(tmp_path):
    df = pd.DataFrame({"Notas_Detalladas": [10, 12, 8], "Registro_Asistencia": [80, 90, 50], "Estado_Abandono": ["Sí", "No", "si"]})
    cargado, _ = ent.cargar_datos(guardar_csv(tmp_path, df))
    assert cargado["Estado_Abandono"].tolist() == [1, 0, 1]


def test_columnas_faltantes_dan_error_claro(tmp_path):
    ruta = guardar_csv(tmp_path, pd.DataFrame({"Notas_Detalladas": [10]}))
    with pytest.raises(ent.DatosInvalidos, match="Registro_Asistencia"):
        ent.cargar_datos(ruta)


def test_descarta_filas_vacias_ilegibles_o_fuera_de_rango(tmp_path):
    df = pd.DataFrame({
        "Notas_Detalladas": [10, None, "abc", 25, 12, 14],
        "Registro_Asistencia": [80, 90, 70, 60, 120, 85],
        "Estado_Abandono": [1, 0, 0, 1, 0, "quizás"],
    })
    cargado, avisos = ent.cargar_datos(guardar_csv(tmp_path, df))
    assert len(cargado) == 1 and cargado.iloc[0]["Notas_Detalladas"] == 10
    assert len(avisos) == 2


def test_avisa_si_el_csv_trae_datos_personales_y_no_los_usa(tmp_path):
    df = dataset(10)
    df["DNI"] = "12345678"
    df["nombre_completo"] = "Alguien"
    cargado, avisos = ent.cargar_datos(guardar_csv(tmp_path, df))
    assert list(cargado.columns) == ["Notas_Detalladas", "Registro_Asistencia", "Estado_Abandono"]
    assert any("DNI" in a and "nombre_completo" in a for a in avisos)


# ---------- validar_tamano ----------

def test_pocas_filas_no_se_entrenan():
    with pytest.raises(ent.DatosInvalidos, match="al menos 50"):
        ent.validar_tamano(dataset(30))


def test_una_sola_clase_o_clase_muy_pequena_no_se_entrena():
    df = dataset(100)
    df["Estado_Abandono"] = 0
    with pytest.raises(ent.DatosInvalidos, match="al menos 10"):
        ent.validar_tamano(df)
    df.loc[:4, "Estado_Abandono"] = 1  # solo 5 casos de abandono
    with pytest.raises(ent.DatosInvalidos, match="al menos 10"):
        ent.validar_tamano(df)


# ---------- entrenar ----------

def test_entrenar_con_datos_reales_guarda_modelo_y_metadatos(tmp_path):
    modelo_pkl, meta_json = tmp_path / "m.pkl", tmp_path / "m.json"
    metadatos = ent.entrenar(dataset(150), "historico.csv", modelo_pkl, meta_json)

    with open(modelo_pkl, "rb") as f:
        modelo = pickle.load(f)
    assert list(modelo.classes_) == [0, 1]
    entrada = pd.DataFrame({"Notas_Detalladas": [5.0], "Registro_Asistencia": [35]})
    assert modelo.predict_proba(entrada)[0][1] > 0.5  # notas y asistencia muy bajas -> riesgo alto

    guardado = json.loads(meta_json.read_text(encoding="utf-8"))
    assert guardado == metadatos
    assert guardado["sintetico"] is False and guardado["n_filas"] == 150
    assert guardado["version_modelo"].startswith("rf-") and not guardado["version_modelo"].endswith("sintetico")
    metricas = guardado["metricas_validacion_cruzada"]
    assert metricas["pliegues"] == 5
    for nombre in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        assert 0.0 <= metricas[nombre]["media"] <= 1.0
    assert metricas["roc_auc"]["media"] > 0.8  # los datos generados sí tienen señal


def test_entrenar_con_datos_insuficientes_no_escribe_archivos(tmp_path):
    modelo_pkl, meta_json = tmp_path / "m.pkl", tmp_path / "m.json"
    with pytest.raises(ent.DatosInvalidos):
        ent.entrenar(dataset(20), "poco.csv", modelo_pkl, meta_json)
    assert not modelo_pkl.exists() and not meta_json.exists()


def test_entrenar_sintetico_se_marca_y_no_calcula_metricas(tmp_path):
    metadatos = ent.entrenar(ent.datos_sinteticos(), "demo", tmp_path / "m.pkl", tmp_path / "m.json", sintetico=True)
    assert metadatos["sintetico"] is True and metadatos["metricas_validacion_cruzada"] is None
    assert metadatos["version_modelo"].endswith("-sintetico")
    assert "no usar" in metadatos["advertencia"].lower()


# ---------- main ----------

def test_main_sin_csv_explica_que_hacer(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ent, "RUTA_DATOS_DEFECTO", tmp_path / "no_existe.csv")
    assert ent.main([]) == 1
    assert "--sintetico" in capsys.readouterr().out


def test_main_con_csv_insuficiente_devuelve_error_sin_traceback(tmp_path, capsys):
    ruta = guardar_csv(tmp_path, dataset(20))
    assert ent.main(["--datos", str(ruta)]) == 1
    assert "No se entrenó el modelo" in capsys.readouterr().out
