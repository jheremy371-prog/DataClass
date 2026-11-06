"""Informe de auditoría P1 n.º 1: copia cifrada con restauración probada."""
import sqlite3
from contextlib import closing

import pytest

from api import respaldo

CLAVE = "clave-de-respaldo-de-prueba-0123456789abcdef"


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("DATACLASS_RESPALDO_CLAVE", CLAVE)
    monkeypatch.setattr(respaldo, "ITERACIONES", 1000)  # rápido en pruebas
    ruta = tmp_path / "origen.db"
    with closing(sqlite3.connect(ruta)) as c:
        c.execute("CREATE TABLE estudiantes (id_estudiante TEXT, nombre_completo TEXT)")
        c.execute("INSERT INTO estudiantes VALUES ('E1', 'Nombre Secreto Único')")
        c.commit()
    return ruta


def test_el_respaldo_no_contiene_datos_legibles(base, tmp_path):
    archivo = respaldo.crear(tmp_path / "out", base)
    assert b"Nombre Secreto" not in archivo.read_bytes()
    assert b"SQLite format" not in archivo.read_bytes()


def test_crear_verificar_y_restaurar(base, tmp_path):
    archivo = respaldo.crear(tmp_path / "out", base)
    assert respaldo.verificar(archivo) == 1
    destino = tmp_path / "restaurada.db"
    respaldo.restaurar(archivo, destino)
    with closing(sqlite3.connect(destino)) as c:
        assert c.execute("SELECT nombre_completo FROM estudiantes").fetchone()[0] == "Nombre Secreto Único"


def test_no_sobrescribe_una_base_existente(base, tmp_path):
    archivo = respaldo.crear(tmp_path / "out", base)
    with pytest.raises(SystemExit):
        respaldo.restaurar(archivo, base)


def test_clave_incorrecta_falla(base, tmp_path, monkeypatch):
    archivo = respaldo.crear(tmp_path / "out", base)
    monkeypatch.setenv("DATACLASS_RESPALDO_CLAVE", "otra-clave-distinta-0123456789abcdef012345")
    with pytest.raises(SystemExit):
        respaldo.verificar(archivo)


def test_sin_clave_no_crea_respaldo(base, tmp_path, monkeypatch):
    monkeypatch.delenv("DATACLASS_RESPALDO_CLAVE")
    with pytest.raises(SystemExit):
        respaldo.crear(tmp_path / "out", base)
