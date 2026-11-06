"""Pruebas de api/sync.py (sincronización hacia Firestore) con un cliente falso: sin red ni credenciales."""
import sqlite3
import sys
import types

import pytest

import api.database as database
from api import sync


class DocumentoFalso:
    def __init__(self, cliente, id_documento):
        self.cliente = cliente
        self.id_documento = id_documento

    def set(self, datos, merge=False):
        if self.id_documento in self.cliente.fallar_en:
            raise ConnectionError("sin red")
        self.cliente.enviados.append((self.cliente.coleccion_usada, self.id_documento, datos, merge))


class ColeccionFalsa:
    def __init__(self, cliente, nombre):
        cliente.coleccion_usada = nombre
        self.cliente = cliente

    def document(self, id_documento):
        return DocumentoFalso(self.cliente, id_documento)


class ClienteFalso:
    """Imita lo mínimo de firestore.Client: collection(...).document(...).set(...)."""

    def __init__(self, fallar_en=()):
        self.fallar_en = set(fallar_en)
        self.enviados = []
        self.coleccion_usada = None

    def collection(self, nombre):
        return ColeccionFalsa(self, nombre)


@pytest.fixture
def bd(tmp_path, monkeypatch):
    """Base temporal con el esquema real; sync.DB_PATH apunta a ella."""
    ruta = tmp_path / "sync_test.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(sync, "DB_PATH", ruta)
    monkeypatch.delenv("FIREBASE_COLLECTION", raising=False)
    monkeypatch.delenv("FIREBASE_CREDENTIALS_PATH", raising=False)
    database.inicializar_esquema()
    return ruta


def insertar(ruta, id_estudiante, is_synced=0, **extra):
    with sqlite3.connect(ruta) as con:
        con.execute(
            "INSERT INTO estudiantes (id_estudiante, dni, nombre_completo, aula, telefono_apoderado, is_synced) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_estudiante, extra.get("dni", f"DNI-{id_estudiante}"), f"Alumno {id_estudiante}", "A-1", "999111222", is_synced),
        )


def marcas(ruta):
    with sqlite3.connect(ruta) as con:
        return dict(con.execute("SELECT id_estudiante, is_synced FROM estudiantes").fetchall())


def usar_cliente(monkeypatch, cliente):
    monkeypatch.setattr(sync, "_crear_cliente_firestore", lambda: cliente)


# ---------- sincronizar_estudiantes ----------

def test_sin_base_local_falla_con_mensaje_claro(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "DB_PATH", tmp_path / "no_existe.db")
    with pytest.raises(FileNotFoundError):
        sync.sincronizar_estudiantes()


def test_sin_pendientes_no_envia_nada(bd, monkeypatch, capsys):
    insertar(bd, "E1", is_synced=1)
    cliente = ClienteFalso()
    usar_cliente(monkeypatch, cliente)
    sync.sincronizar_estudiantes()
    assert cliente.enviados == []
    assert "Todo al día" in capsys.readouterr().out


def test_modo_simulacion_no_marca_registros_como_sincronizados(bd, monkeypatch, capsys):
    insertar(bd, "E1")
    insertar(bd, "E2")
    usar_cliente(monkeypatch, None)  # sin credenciales configuradas
    sync.sincronizar_estudiantes()
    assert marcas(bd) == {"E1": 0, "E2": 0}
    salida = capsys.readouterr().out
    assert "MODO SIMULACIÓN" in salida and "2 estudiante(s)" in salida


def test_sincroniza_solo_pendientes_y_los_marca(bd, monkeypatch):
    insertar(bd, "E1")
    insertar(bd, "E2", is_synced=1)  # ya estaba en la nube
    insertar(bd, "E3")
    cliente = ClienteFalso()
    usar_cliente(monkeypatch, cliente)
    sync.sincronizar_estudiantes()
    assert sorted(id_doc for _, id_doc, _, _ in cliente.enviados) == sorted([sync.seudonimo("E1"), sync.seudonimo("E3")])
    assert marcas(bd) == {"E1": 1, "E2": 1, "E3": 1}


def test_documento_enviado_usa_merge_y_solo_lleva_lo_minimo(bd, monkeypatch):
    insertar(bd, "E1", dni="12345678")
    cliente = ClienteFalso()
    usar_cliente(monkeypatch, cliente)
    sync.sincronizar_estudiantes()
    coleccion, id_doc, documento, merge = cliente.enviados[0]
    seudonimo = sync.seudonimo("E1")
    assert (coleccion, id_doc, merge) == ("estudiantes", seudonimo, True)
    assert documento == {
        "id_anonimo": seudonimo,
        "aula": "A-1",
        "riesgo_desercion": "Pendiente",
        "riesgo_reprobacion": "Pendiente",
    }
    # H-03: nada que identifique a la persona sale a la nube
    texto = repr(cliente.enviados)
    for dato in ("12345678", "Alumno E1", "999111222", "E1"):
        assert dato not in texto.replace(seudonimo, "")


def test_el_seudonimo_es_estable_distinto_por_estudiante_y_depende_de_la_clave():
    a = sync.seudonimo("E1")
    assert a == sync.seudonimo("E1") and len(a) == 24
    assert a != sync.seudonimo("E2")
    assert a != sync.seudonimo("E1", clave="otra-clave-distinta-de-mas-de-32-caracteres")
    assert "E1" not in a


def test_sin_clave_de_seudonimo_no_se_envia_nada(bd, monkeypatch, capsys):
    insertar(bd, "E1")
    monkeypatch.delenv("DATACLASS_SEUDONIMO_CLAVE", raising=False)
    cliente = ClienteFalso()
    usar_cliente(monkeypatch, cliente)
    assert sync.sincronizar_estudiantes() == {"enviados": 0, "errores": 1}
    assert cliente.enviados == [] and marcas(bd) == {"E1": 0}
    assert "DATACLASS_SEUDONIMO_CLAVE" in capsys.readouterr().out
    with pytest.raises(RuntimeError):
        sync.seudonimo("E1")
    monkeypatch.setenv("DATACLASS_SEUDONIMO_CLAVE", "corta")
    with pytest.raises(RuntimeError):
        sync.seudonimo("E1")


def test_coleccion_configurable_por_variable_de_entorno(bd, monkeypatch):
    insertar(bd, "E1")
    monkeypatch.setenv("FIREBASE_COLLECTION", "alumnos_prod")
    cliente = ClienteFalso()
    usar_cliente(monkeypatch, cliente)
    sync.sincronizar_estudiantes()
    assert cliente.enviados[0][0] == "alumnos_prod"


def test_un_fallo_de_red_deja_pendiente_solo_a_ese_estudiante(bd, monkeypatch, capsys):
    for id_estudiante in ("E1", "E2", "E3"):
        insertar(bd, id_estudiante)
    cliente = ClienteFalso(fallar_en={sync.seudonimo("E2")})
    usar_cliente(monkeypatch, cliente)
    sync.sincronizar_estudiantes()
    assert marcas(bd) == {"E1": 1, "E2": 0, "E3": 1}
    assert "Exitosos en la nube: 2; Pendientes por error: 1" in capsys.readouterr().out


def test_reintento_posterior_sincroniza_lo_que_fallo(bd, monkeypatch):
    insertar(bd, "E1")
    usar_cliente(monkeypatch, ClienteFalso(fallar_en={sync.seudonimo("E1")}))
    sync.sincronizar_estudiantes()
    assert marcas(bd) == {"E1": 0}
    recuperado = ClienteFalso()
    usar_cliente(monkeypatch, recuperado)
    sync.sincronizar_estudiantes()
    assert marcas(bd) == {"E1": 1} and len(recuperado.enviados) == 1


def test_error_al_crear_el_cliente_no_toca_la_base(bd, monkeypatch, capsys):
    insertar(bd, "E1")

    def explotar():
        raise RuntimeError("credenciales inválidas")

    monkeypatch.setattr(sync, "_crear_cliente_firestore", explotar)
    sync.sincronizar_estudiantes()  # no debe propagar la excepción
    assert marcas(bd) == {"E1": 0}
    assert "Error al inicializar Firebase" in capsys.readouterr().out


# ---------- _crear_cliente_firestore ----------

def instalar_firebase_falso(monkeypatch, app_existente):
    registro = {"inicializaciones": [], "certificados": []}
    firebase_admin = types.ModuleType("firebase_admin")
    credentials = types.ModuleType("firebase_admin.credentials")
    firestore = types.ModuleType("firebase_admin.firestore")

    def get_app():
        if app_existente:
            return "app-existente"
        raise ValueError("no hay app")

    def initialize_app(certificado):
        registro["inicializaciones"].append(certificado)
        return "app-nueva"

    def certificate(ruta):
        registro["certificados"].append(ruta)
        return f"cert:{ruta}"

    firebase_admin.get_app = get_app
    firebase_admin.initialize_app = initialize_app
    credentials.Certificate = certificate
    firestore.client = lambda app: f"cliente({app})"
    firebase_admin.credentials = credentials
    firebase_admin.firestore = firestore
    for nombre, modulo in (("firebase_admin", firebase_admin), ("firebase_admin.credentials", credentials), ("firebase_admin.firestore", firestore)):
        monkeypatch.setitem(sys.modules, nombre, modulo)
    return registro


def test_sin_variable_de_credenciales_no_hay_cliente(monkeypatch):
    monkeypatch.delenv("FIREBASE_CREDENTIALS_PATH", raising=False)
    assert sync._crear_cliente_firestore() is None


def test_ruta_de_credenciales_inexistente_da_error_explicito(tmp_path, monkeypatch):
    instalar_firebase_falso(monkeypatch, app_existente=False)
    monkeypatch.setenv("FIREBASE_CREDENTIALS_PATH", str(tmp_path / "falta.json"))
    with pytest.raises(RuntimeError, match="no existe"):
        sync._crear_cliente_firestore()


def test_firebase_admin_no_instalado_da_instruccion_de_instalacion(monkeypatch):
    monkeypatch.setenv("FIREBASE_CREDENTIALS_PATH", "cualquiera.json")
    monkeypatch.setitem(sys.modules, "firebase_admin", None)  # fuerza ImportError
    with pytest.raises(RuntimeError, match="pip install firebase-admin"):
        sync._crear_cliente_firestore()


def test_inicializa_la_app_una_sola_vez(tmp_path, monkeypatch):
    clave = tmp_path / "clave.json"
    clave.write_text("{}")
    monkeypatch.setenv("FIREBASE_CREDENTIALS_PATH", str(clave))

    registro = instalar_firebase_falso(monkeypatch, app_existente=False)
    assert sync._crear_cliente_firestore() == "cliente(app-nueva)"
    assert registro["inicializaciones"] == [f"cert:{clave}"]

    registro = instalar_firebase_falso(monkeypatch, app_existente=True)
    assert sync._crear_cliente_firestore() == "cliente(app-existente)"
    assert registro["inicializaciones"] == []  # reutiliza la app, no reinicializa
