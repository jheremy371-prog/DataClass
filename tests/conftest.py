"""Configuración común: cada prueba parte con el modelo declarado como entrenado (no sintético).

Así las pruebas que usan un modelo simulado no dependen del modelo_riesgo.json real del
repositorio, que es de demostración; las pruebas de H-01 lo activan explícitamente.
"""
import pytest

from api import riesgo


@pytest.fixture(autouse=True)
def modelo_no_sintetico_por_defecto(monkeypatch):
    monkeypatch.setattr(riesgo, "MODELO_SINTETICO", False)
    monkeypatch.delenv("DATACLASS_MODO_DEMO", raising=False)


@pytest.fixture(autouse=True)
def clave_de_seudonimo_de_prueba(monkeypatch):
    """H-03: la sincronización con la nube exige una clave para seudonimizar; las pruebas usan una fija."""
    monkeypatch.setenv("DATACLASS_SEUDONIMO_CLAVE", "clave-de-prueba-para-seudonimos-0123456789")
