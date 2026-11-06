"""Lectura de modelo_riesgo.json por la API (versión real del modelo y aviso de versiones de scikit-learn)."""
import json
import warnings

import pytest

from api import riesgo


@pytest.fixture(autouse=True)
def restaurar_version():
    original = riesgo.VERSION_MODELO
    yield
    riesgo.VERSION_MODELO = original


def escribir(tmp_path, contenido):
    ruta = tmp_path / "modelo_riesgo.json"
    ruta.write_text(contenido if isinstance(contenido, str) else json.dumps(contenido), encoding="utf-8")
    return ruta


def test_la_version_del_json_reemplaza_a_la_version_por_defecto(tmp_path):
    ruta = escribir(tmp_path, {"version_modelo": "rf-20261023", "sklearn_version": "1.9.1"})
    metadatos = riesgo.aplicar_metadatos_modelo(ruta, "1.9.1")
    assert metadatos["version_modelo"] == "rf-20261023"
    assert riesgo.VERSION_MODELO == "rf-20261023"


def test_sin_archivo_se_conserva_la_version_por_defecto(tmp_path):
    antes = riesgo.VERSION_MODELO
    assert riesgo.aplicar_metadatos_modelo(tmp_path / "no_existe.json", "1.9.1") is None
    assert riesgo.VERSION_MODELO == antes


@pytest.mark.parametrize("contenido", ["{no es json", "[]", '{"otra_clave": 1}', "null"])
def test_json_danado_o_incompleto_se_ignora(tmp_path, contenido):
    antes = riesgo.VERSION_MODELO
    assert riesgo.aplicar_metadatos_modelo(escribir(tmp_path, contenido), "1.9.1") is None
    assert riesgo.VERSION_MODELO == antes


def test_version_distinta_de_sklearn_emite_advertencia(tmp_path):
    ruta = escribir(tmp_path, {"version_modelo": "rf-1", "sklearn_version": "1.8.0"})
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        riesgo.aplicar_metadatos_modelo(ruta, "1.9.1")
    mensajes = [str(a.message) for a in avisos if issubclass(a.category, RuntimeWarning)]
    assert len(mensajes) == 1 and "1.8.0" in mensajes[0] and "1.9.1" in mensajes[0]


def test_misma_version_de_sklearn_no_advierte(tmp_path):
    ruta = escribir(tmp_path, {"version_modelo": "rf-1", "sklearn_version": "1.9.1"})
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        riesgo.aplicar_metadatos_modelo(ruta, "1.9.1")
    assert not [a for a in avisos if issubclass(a.category, RuntimeWarning)]
