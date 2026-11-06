"""Sincronización por lotes de calificaciones y asistencias, sincronizar_todo y SyncWorker (cliente falso, sin red)."""
import sqlite3
import threading

import pytest

import api.database as database
from api import sync


class ReferenciaFalsa:
    def __init__(self, cliente, ruta):
        self.cliente, self.ruta = cliente, ruta

    def collection(self, nombre):
        return ReferenciaFalsa(self.cliente, self.ruta + (nombre,))

    def document(self, id_documento):
        return ReferenciaFalsa(self.cliente, self.ruta + (id_documento,))

    def set(self, datos, merge=False):  # escritura directa (la usa sincronizar_estudiantes)
        self.cliente.directos.append((self.ruta, datos, merge))


class LoteFalso:
    def __init__(self, cliente):
        self.cliente, self.operaciones = cliente, []

    def set(self, referencia, datos, merge=False):
        self.operaciones.append((referencia.ruta, datos, merge))

    def commit(self):
        self.cliente.intentos_de_commit += 1
        if self.cliente.intentos_de_commit in self.cliente.commits_que_fallan:
            raise ConnectionError("sin red")
        self.cliente.confirmados.append(self.operaciones)


class ClienteFalso:
    def __init__(self, commits_que_fallan=()):
        self.commits_que_fallan = set(commits_que_fallan)
        self.intentos_de_commit = 0
        self.confirmados = []  # lista de lotes confirmados
        self.directos = []

    def collection(self, nombre):
        return ReferenciaFalsa(self, (nombre,))

    def batch(self):
        return LoteFalso(self)


@pytest.fixture
def bd(tmp_path, monkeypatch):
    ruta = tmp_path / "lotes.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(sync, "DB_PATH", ruta)
    monkeypatch.delenv("FIREBASE_COLLECTION", raising=False)
    database.inicializar_esquema()
    with sqlite3.connect(ruta) as con:
        con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo, aula) VALUES ('E1', 'Alumno 1', 'A-1')")
        con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo, aula) VALUES ('E2', 'Alumno 2', 'A-1')")
    return ruta


def notas(ruta, cantidad, estudiante="E1", is_synced=0):
    with sqlite3.connect(ruta) as con:
        for i in range(cantidad):
            con.execute(
                "INSERT INTO calificaciones (id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion, is_synced) VALUES (?, ?, ?, 'B1', ?)",
                (estudiante, f"Curso {i}", 10 + i % 10, is_synced),
            )


def asistencias(ruta, estados, estudiante="E1"):
    with sqlite3.connect(ruta) as con:
        for i, estado in enumerate(estados):
            con.execute("INSERT INTO asistencias (id_estudiante, fecha, estado_asistencia) VALUES (?, ?, ?)", (estudiante, f"2026-10-{i + 1:02d}", estado))


def pendientes(ruta, tabla):
    with sqlite3.connect(ruta) as con:
        return con.execute(f"SELECT COUNT(*) FROM {tabla} WHERE is_synced = 0").fetchone()[0]


# ---------- sincronizar_tabla ----------

def test_envia_calificaciones_bajo_el_estudiante_y_las_marca(bd):
    notas(bd, 2)
    cliente = ClienteFalso()
    assert sync.sincronizar_tabla("calificaciones", cliente) == {"enviados": 2, "errores": 0}
    (lote,) = cliente.confirmados
    rutas = [ruta for ruta, _, _ in lote]
    p = sync.seudonimo("E1")
    assert rutas == [("estudiantes", p, "calificaciones", "1"), ("estudiantes", p, "calificaciones", "2")]
    assert lote[0][1] == {"id_anonimo": p, "id_calificacion": 1, "curso_modulo": "Curso 0", "nota_obtenida": 10.0, "periodo_evaluacion": "B1"}
    assert "E1" not in repr(lote[0][1])  # el ID real no sale a la nube
    assert all(merge is True for _, _, merge in lote)
    assert pendientes(bd, "calificaciones") == 0


def test_la_asistencia_usa_la_fecha_como_id_de_documento(bd):
    asistencias(bd, ["presente", "falta"])
    cliente = ClienteFalso()
    sync.sincronizar_tabla("asistencias", cliente)
    rutas = [ruta for ruta, _, _ in cliente.confirmados[0]]
    p = sync.seudonimo("E1")
    assert rutas == [("estudiantes", p, "asistencias", "2026-10-01"), ("estudiantes", p, "asistencias", "2026-10-02")]


def test_la_coleccion_raiz_es_configurable(bd, monkeypatch):
    notas(bd, 1)
    monkeypatch.setenv("FIREBASE_COLLECTION", "alumnos_prod")
    cliente = ClienteFalso()
    sync.sincronizar_tabla("calificaciones", cliente)
    assert cliente.confirmados[0][0][0][0] == "alumnos_prod"


def test_no_reenvia_lo_ya_sincronizado(bd):
    notas(bd, 3, is_synced=1)
    cliente = ClienteFalso()
    assert sync.sincronizar_tabla("calificaciones", cliente) == {"enviados": 0, "errores": 0}
    assert cliente.confirmados == []


def test_divide_en_lotes_del_tamano_indicado(bd):
    notas(bd, 5)
    cliente = ClienteFalso()
    assert sync.sincronizar_tabla("calificaciones", cliente, tamano_lote=2)["enviados"] == 5
    assert [len(lote) for lote in cliente.confirmados] == [2, 2, 1]


def test_un_lote_fallido_queda_pendiente_y_los_demas_se_sincronizan(bd):
    notas(bd, 5)
    cliente = ClienteFalso(commits_que_fallan={2})  # falla el segundo lote (filas 3 y 4)
    assert sync.sincronizar_tabla("calificaciones", cliente, tamano_lote=2) == {"enviados": 3, "errores": 2}
    with sqlite3.connect(bd) as con:
        sin_sincronizar = [f[0] for f in con.execute("SELECT id_calificacion FROM calificaciones WHERE is_synced = 0")]
    assert sin_sincronizar == [3, 4]


def test_reintento_envia_solo_lo_que_fallo(bd):
    notas(bd, 3)
    sync.sincronizar_tabla("calificaciones", ClienteFalso(commits_que_fallan={1}))
    assert pendientes(bd, "calificaciones") == 3
    cliente = ClienteFalso()
    assert sync.sincronizar_tabla("calificaciones", cliente)["enviados"] == 3
    assert pendientes(bd, "calificaciones") == 0


def test_modo_simulacion_no_marca_nada(bd, capsys):
    notas(bd, 2)
    assert sync.sincronizar_tabla("calificaciones", None) == {"enviados": 0, "errores": 0}
    assert pendientes(bd, "calificaciones") == 2
    assert "MODO SIMULACIÓN" in capsys.readouterr().out


def test_tabla_o_tamano_de_lote_invalidos(bd):
    with pytest.raises(ValueError):
        sync.sincronizar_tabla("usuarios", ClienteFalso())
    for tamano in (0, 501):
        with pytest.raises(ValueError):
            sync.sincronizar_tabla("calificaciones", ClienteFalso(), tamano_lote=tamano)


def test_error_al_crear_el_cliente_se_informa_como_error(bd, monkeypatch):
    notas(bd, 1)

    def explotar():
        raise RuntimeError("credenciales inválidas")

    monkeypatch.setattr(sync, "_crear_cliente_firestore", explotar)
    assert sync.sincronizar_tabla("calificaciones") == {"enviados": 0, "errores": 1}
    assert pendientes(bd, "calificaciones") == 1


# ---------- sincronizar_todo ----------

def test_sincronizar_todo_envia_las_tres_tablas_con_un_solo_cliente(bd, monkeypatch):
    notas(bd, 2)
    asistencias(bd, ["presente"])
    cliente = ClienteFalso()
    creados = []
    monkeypatch.setattr(sync, "_crear_cliente_firestore", lambda: creados.append(1) or cliente)
    assert sync.sincronizar_todo() == {"enviados": 5, "errores": 0}  # 2 estudiantes + 2 notas + 1 asistencia
    assert len(creados) == 1
    assert len(cliente.directos) == 2 and len(cliente.confirmados) == 2


def test_sincronizar_todo_suma_los_errores(bd, monkeypatch):
    notas(bd, 1)
    cliente = ClienteFalso(commits_que_fallan={1})
    monkeypatch.setattr(sync, "_crear_cliente_firestore", lambda: cliente)
    assert sync.sincronizar_todo() == {"enviados": 2, "errores": 1}


def test_sincronizar_todo_sin_base_falla_con_mensaje_claro(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "DB_PATH", tmp_path / "no_existe.db")
    with pytest.raises(FileNotFoundError):
        sync.sincronizar_todo()


# ---------- SyncWorker ----------

def test_espera_normal_cuando_todo_sale_bien():
    worker = sync.SyncWorker(intervalo=30, tarea=lambda: {"enviados": 3, "errores": 0})
    assert worker.ejecutar_ciclo() == 30 and worker.fallos_consecutivos == 0


def test_la_espera_se_duplica_con_cada_fallo_hasta_el_maximo():
    worker = sync.SyncWorker(intervalo=30, espera_maxima=200, tarea=lambda: {"enviados": 0, "errores": 2})
    assert [worker.ejecutar_ciclo() for _ in range(4)] == [60, 120, 200, 200]
    assert worker.fallos_consecutivos == 4


def test_un_exito_despues_de_fallos_restablece_el_intervalo():
    resultados = iter([{"errores": 1}, {"errores": 1}, {"errores": 0}])
    worker = sync.SyncWorker(intervalo=10, tarea=lambda: next(resultados))
    assert [worker.ejecutar_ciclo() for _ in range(3)] == [20, 40, 10]
    assert worker.fallos_consecutivos == 0


def test_una_excepcion_no_mata_al_worker_y_cuenta_como_fallo(capsys):
    def tarea():
        raise OSError("disco ocupado")

    worker = sync.SyncWorker(intervalo=5, tarea=tarea)
    assert worker.ejecutar_ciclo() == 10
    assert "disco ocupado" in capsys.readouterr().out


def test_el_hilo_repite_la_tarea_y_se_detiene():
    llamadas = []
    dos_veces = threading.Event()

    def tarea():
        llamadas.append(1)
        if len(llamadas) >= 2:
            dos_veces.set()
        return {"enviados": 0, "errores": 0}

    worker = sync.SyncWorker(intervalo=0.01, tarea=tarea)
    worker.start()
    assert dos_veces.wait(timeout=5), "el worker no repitió la tarea"
    worker.detener()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert worker.daemon is True


def test_sin_clave_de_seudonimo_los_lotes_no_se_envian(bd, monkeypatch):
    notas(bd, 2)
    monkeypatch.delenv("DATACLASS_SEUDONIMO_CLAVE", raising=False)
    cliente = ClienteFalso()
    assert sync.sincronizar_tabla("calificaciones", cliente) == {"enviados": 0, "errores": 1}
    assert cliente.confirmados == [] and pendientes(bd, "calificaciones") == 2
