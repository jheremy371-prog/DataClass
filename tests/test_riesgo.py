"""Pruebas del semáforo de riesgo (sin depender de FastAPI ni del modelo real)."""
import pytest

import api.database as database
from api import riesgo


class ModeloFalso:
    """Imita el modelo de scikit-learn: devuelve una probabilidad fija para la clase 1."""

    classes_ = [0, 1]

    def __init__(self, probabilidad):
        self.probabilidad = probabilidad

    def predict_proba(self, entrada):
        return [[1 - self.probabilidad, self.probabilidad]]


def preparar_bd(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "riesgo_test.db")
    database.inicializar_esquema()
    return database.obtener_conexion()


def crear_estudiante(conexion, id_estudiante, notas=(), asistencias=()):
    conexion.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo) VALUES (?, ?)", (id_estudiante, f"Alumno {id_estudiante}"))
    for i, nota in enumerate(notas):
        conexion.execute(
            "INSERT INTO calificaciones (id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion) VALUES (?, ?, ?, 'B1')",
            (id_estudiante, f"Curso {i}", nota),
        )
    for i, estado in enumerate(asistencias):
        conexion.execute(
            "INSERT INTO asistencias (id_estudiante, fecha, estado_asistencia) VALUES (?, ?, ?)",
            (id_estudiante, f"2026-10-{i + 1:02d}", estado),
        )
    conexion.commit()


def alertas_de(conexion, id_estudiante):
    return conexion.execute(
        "SELECT nivel_riesgo, probabilidad, tipo_alerta, estado FROM alertas WHERE id_estudiante = ? ORDER BY id_alerta",
        (id_estudiante,),
    ).fetchall()


def test_umbrales_del_semaforo():
    casos = {0.0: "Bajo", 0.2999: "Bajo", 0.30: "Medio", 0.6999: "Medio", 0.70: "Alto", 1.0: "Alto"}
    for probabilidad, esperado in casos.items():
        assert riesgo.clasificar_probabilidad(probabilidad) == esperado, probabilidad
    for invalida in (-0.01, 1.01, None):
        with pytest.raises(ValueError):
            riesgo.clasificar_probabilidad(invalida)


def test_indicadores_excluyen_faltas_justificadas(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    crear_estudiante(
        conexion, "E1", notas=(10, 14),
        asistencias=["presente"] * 3 + ["tardanza", "falta", "justificada", "justificada"],
    )
    indicadores = riesgo.calcular_indicadores(conexion, "E1")
    assert indicadores["notas_promedio"] == 12.0
    assert indicadores["porcentaje_asistencia"] == 80  # 4 de 5 días penalizables
    assert indicadores["n_asistencias"] == 7


def test_datos_insuficientes_y_estudiante_inexistente(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    crear_estudiante(conexion, "E2", notas=(15,), asistencias=["presente"] * 4)
    with pytest.raises(riesgo.DatosInsuficientes):
        riesgo.evaluar_estudiante(conexion, "E2", ModeloFalso(0.9))
    with pytest.raises(riesgo.EstudianteNoEncontrado):
        riesgo.evaluar_estudiante(conexion, "NO-EXISTE", ModeloFalso(0.9))
    assert alertas_de(conexion, "E2") == []


def test_sin_modelo_no_inventa_resultados(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    crear_estudiante(conexion, "E3", notas=(9,), asistencias=["falta"] * 5)
    with pytest.raises(riesgo.ModeloNoDisponible):
        riesgo.evaluar_estudiante(conexion, "E3", None)
    estado = conexion.execute("SELECT riesgo_desercion FROM estudiantes WHERE id_estudiante = 'E3'").fetchone()[0]
    assert estado == "Pendiente"


def test_evaluacion_actualiza_semaforo_y_crea_alertas_sin_duplicar(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    crear_estudiante(conexion, "E4", notas=(8, 9), asistencias=["presente", "falta", "falta", "falta", "presente"])

    alto = riesgo.evaluar_estudiante(conexion, "E4", ModeloFalso(0.85))
    assert alto["nivel_riesgo"] == "Alto" and alto["cambio"] is True and alto["alerta_creada"]
    assert conexion.execute("SELECT riesgo_desercion, is_synced FROM estudiantes WHERE id_estudiante = 'E4'").fetchone()[:] == ("Alto", 0)
    assert [tuple(a)[:3] for a in alertas_de(conexion, "E4")] == [("alto", 0.85, "desercion")]

    repetido = riesgo.evaluar_estudiante(conexion, "E4", ModeloFalso(0.85))
    assert repetido["alerta_creada"] is None and repetido["cambio"] is False
    assert len(alertas_de(conexion, "E4")) == 1

    medio = riesgo.evaluar_estudiante(conexion, "E4", ModeloFalso(0.50))
    assert medio["nivel_riesgo"] == "Medio" and medio["alerta_creada"]
    assert len(alertas_de(conexion, "E4")) == 2

    bajo = riesgo.evaluar_estudiante(conexion, "E4", ModeloFalso(0.10))
    assert bajo["nivel_riesgo"] == "Bajo" and bajo["alerta_creada"] is None
    assert len(alertas_de(conexion, "E4")) == 2
    assert conexion.execute("SELECT riesgo_desercion FROM estudiantes WHERE id_estudiante = 'E4'").fetchone()[0] == "Bajo"


def test_evaluar_todos_resume_y_omite_los_que_no_tienen_datos(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    crear_estudiante(conexion, "A1", notas=(18,), asistencias=["presente"] * 6)
    crear_estudiante(conexion, "A2", notas=(7,), asistencias=["falta"] * 6)
    crear_estudiante(conexion, "A3")  # sin datos
    resumen = riesgo.evaluar_todos(conexion, ModeloFalso(0.9))
    assert resumen["total_estudiantes"] == 3
    assert resumen["evaluados"] == 2 and resumen["sin_datos_suficientes"] == 1
    assert resumen["alertas_creadas"] == 2 and resumen["por_nivel"]["Alto"] == 2


# --- H-01: un modelo sintético no publica semáforo ni crea alertas ---------------------------

def _estudiante_con_datos(conexion):
    crear_estudiante(conexion, "EST-S1", notas=(5,), asistencias=("falta",) * 6)
    conexion.commit()


def test_modelo_sintetico_no_crea_alertas_ni_cambia_semaforo(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    _estudiante_con_datos(conexion)
    monkeypatch.setattr(riesgo, "MODELO_SINTETICO", True)
    with pytest.raises(riesgo.ModeloSintetico):
        riesgo.evaluar_estudiante(conexion, "EST-S1", ModeloFalso(0.95))
    assert conexion.execute("SELECT COUNT(*) FROM alertas").fetchone()[0] == 0
    assert conexion.execute("SELECT riesgo_desercion FROM estudiantes WHERE id_estudiante='EST-S1'").fetchone()[0] != "Alto"
    conexion.close()


def test_modelo_sintetico_es_un_modelo_no_disponible_para_la_api(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    _estudiante_con_datos(conexion)
    monkeypatch.setattr(riesgo, "MODELO_SINTETICO", True)
    with pytest.raises(riesgo.ModeloNoDisponible):
        riesgo.evaluar_todos(conexion, ModeloFalso(0.95))
    conexion.close()


def test_modo_demostracion_permite_alertas_con_modelo_sintetico(tmp_path, monkeypatch):
    conexion = preparar_bd(tmp_path, monkeypatch)
    _estudiante_con_datos(conexion)
    monkeypatch.setattr(riesgo, "MODELO_SINTETICO", True)
    monkeypatch.setenv("DATACLASS_MODO_DEMO", "1")
    resultado = riesgo.evaluar_estudiante(conexion, "EST-S1", ModeloFalso(0.95))
    assert resultado["nivel_riesgo"] == "Alto" and resultado["alerta_creada"]
    conexion.close()


def test_metadatos_sinteticos_o_sin_marca_bloquean_y_false_explicito_permite(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(riesgo, "VERSION_MODELO", riesgo.VERSION_MODELO)
    for contenido, esperado in (
        ({"version_modelo": "v", "sintetico": True}, True),
        ({"version_modelo": "v"}, True),
        ({"version_modelo": "v", "sintetico": False}, False),
    ):
        ruta = tmp_path / "m.json"
        ruta.write_text(json.dumps(contenido), encoding="utf-8")
        monkeypatch.setattr(riesgo, "MODELO_SINTETICO", not esperado)
        riesgo.aplicar_metadatos_modelo(ruta, None)
        assert riesgo.MODELO_SINTETICO is esperado
        assert riesgo.estado_modelo()["evaluacion_automatica_activa"] is (not esperado)
