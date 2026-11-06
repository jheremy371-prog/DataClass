"""Fija como regla los valores por defecto seguros que pide el informe de auditoría (P0 n.º 5 y H-01)."""
import re
from pathlib import Path

from api import riesgo

RAIZ = Path(__file__).resolve().parent.parent


def test_modo_demo_apagado_por_defecto(monkeypatch):
    monkeypatch.delenv("DATACLASS_MODO_DEMO", raising=False)
    assert riesgo.modo_demostracion() is False


def test_modelo_sintetico_sin_modo_demo_no_evalua_automaticamente(monkeypatch):
    monkeypatch.delenv("DATACLASS_MODO_DEMO", raising=False)
    monkeypatch.setattr(riesgo, "MODELO_SINTETICO", True)
    assert riesgo.evaluacion_automatica_activa() is False


def test_el_ejemplo_de_entorno_deja_el_modo_demo_y_la_cookie_apagados():
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^DATACLASS_MODO_DEMO=0\s*$", texto, re.M)
    assert re.search(r"^DATACLASS_SESION_PERSISTENTE=0\s*$", texto, re.M)
    assert re.search(r"^DATACLASS_DOCS=0\s*$", texto, re.M)


def test_la_sesion_no_es_persistente_por_defecto():
    """app.py no se puede importar sin Streamlit en ejecución: se comprueba el valor por defecto en el código."""
    codigo = (RAIZ / "app.py").read_text(encoding="utf-8")
    assert 'os.getenv("DATACLASS_SESION_PERSISTENTE", "0")' in codigo
