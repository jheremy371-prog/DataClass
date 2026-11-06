"""Eliminación de estudiantes en Firestore (derecho de supresión), con un cliente falso y sin red."""
import sqlite3

import pytest

import api.database as database
from api import sync


class Doc:
    def __init__(self, cliente, ruta):
        self.cliente, self.ruta = cliente, ruta
        self.reference = self

    def collection(self, nombre):
        return Col(self.cliente, self.ruta + (nombre,))

    def delete(self):
        self.cliente.almacen.pop(self.ruta, None)


class Col:
    def __init__(self, cliente, ruta):
        self.cliente, self.ruta, self.tope = cliente, ruta, None

    def document(self, id_documento):
        return Doc(self.cliente, self.ruta + (id_documento,))

    def limit(self, n):
        self.tope = n
        return self

    def stream(self):
        hijos = [Doc(self.cliente, k) for k in list(self.cliente.almacen)
                 if len(k) == len(self.ruta) + 1 and k[:len(self.ruta)] == self.ruta]
        return hijos[: self.tope] if self.tope else hijos


class Lote:
    def __init__(self, cliente):
        self.cliente, self.refs = cliente, []

    def delete(self, referencia):
        self.refs.append(referencia)

    def commit(self):
        if self.cliente.sin_red:
            raise ConnectionError("sin red")
        for referencia in self.refs:
            referencia.delete()


class Cliente:
    def __init__(self, sin_red=False):
        self.almacen, self.sin_red = {}, sin_red

    def collection(self, nombre):
        return Col(self, (nombre,))

    def batch(self):
        return Lote(self)


def poblar(cliente, notas=3):
    p1, p2 = sync.seudonimo("E1"), sync.seudonimo("E2")  # en la nube los documentos llevan el seudónimo
    cliente.almacen[("estudiantes", p1)] = 1
    for i in range(notas):
        cliente.almacen[("estudiantes", p1, "calificaciones", str(i))] = 1
    cliente.almacen[("estudiantes", p1, "asistencias", "2026-10-01")] = 1
    cliente.almacen[("estudiantes", p2)] = 1
    cliente.almacen[("estudiantes", p2, "calificaciones", "1")] = 1


@pytest.fixture
def bd(tmp_path, monkeypatch):
    ruta = tmp_path / "eliminacion.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(sync, "DB_PATH", ruta)
    monkeypatch.delenv("FIREBASE_COLLECTION", raising=False)
    database.inicializar_esquema()
    with sqlite3.connect(ruta) as con:
        con.execute("INSERT INTO eliminaciones_nube (id_estudiante) VALUES ('E1')")
    return ruta


def pendientes(ruta):
    with sqlite3.connect(ruta) as con:
        return [f[0] for f in con.execute("SELECT id_estudiante FROM eliminaciones_nube")]


def test_borra_documento_y_subcolecciones_sin_tocar_a_otros(bd):
    cliente = Cliente()
    poblar(cliente)
    assert sync.sincronizar_eliminaciones(cliente) == {"enviados": 1, "errores": 0}
    assert [k for k in cliente.almacen if k[1] == sync.seudonimo("E1")] == []
    assert ("estudiantes", sync.seudonimo("E2"), "calificaciones", "1") in cliente.almacen
    assert pendientes(bd) == []


def test_vacia_subcolecciones_grandes_por_lotes(bd):
    cliente = Cliente()
    poblar(cliente, notas=1203)  # más de dos lotes de 500
    assert sync.sincronizar_eliminaciones(cliente)["enviados"] == 1
    assert [k for k in cliente.almacen if k[1] == sync.seudonimo("E1")] == []


def test_sin_red_queda_pendiente_y_se_reintenta(bd):
    cliente = Cliente(sin_red=True)
    poblar(cliente)
    assert sync.sincronizar_eliminaciones(cliente) == {"enviados": 0, "errores": 1}
    assert pendientes(bd) == ["E1"]
    cliente.sin_red = False
    assert sync.sincronizar_eliminaciones(cliente) == {"enviados": 1, "errores": 0}
    assert pendientes(bd) == []


def test_modo_simulacion_no_borra_la_solicitud(bd):
    assert sync.sincronizar_eliminaciones(None) == {"enviados": 0, "errores": 0}
    assert pendientes(bd) == ["E1"]


def test_base_antigua_sin_tabla_no_falla(tmp_path, monkeypatch):
    ruta = tmp_path / "vieja.db"
    sqlite3.connect(ruta).execute("CREATE TABLE otra (a)")
    monkeypatch.setattr(sync, "DB_PATH", ruta)
    assert sync.sincronizar_eliminaciones(Cliente()) == {"enviados": 0, "errores": 0}


def test_sincronizar_todo_procesa_eliminaciones(bd, monkeypatch):
    cliente = Cliente()
    poblar(cliente)
    monkeypatch.setattr(sync, "_obtener_cliente", lambda c: (cliente if c is sync._CREAR else c, False))
    assert sync.sincronizar_todo()["errores"] == 0
    assert [k for k in cliente.almacen if k[1] == sync.seudonimo("E1")] == []
