"""Casos límite del módulo de riesgo que test_riesgo.py no cubre: indicadores, predicción y estado de alertas."""
import pytest

import api.database as database
from api import riesgo


class ModeloFalso:
    def __init__(self, probabilidad, classes=(0, 1)):
        self.probabilidad = probabilidad
        self.classes_ = list(classes)
        self.entradas = []

    def predict_proba(self, entrada):
        self.entradas.append(entrada)
        por_clase = {0: 1 - self.probabilidad, 1: self.probabilidad}
        return [[por_clase[c] for c in self.classes_]]


@pytest.fixture
def conexion(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "bordes.db")
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


# ---------- calcular_indicadores ----------

def test_indicadores_de_estudiante_sin_registros(conexion):
    crear_estudiante(conexion, "E1")
    assert riesgo.calcular_indicadores(conexion, "E1") == {
        "notas_promedio": None, "porcentaje_asistencia": 100, "n_notas": 0, "n_asistencias": 0,
    }


def test_todas_las_ausencias_justificadas_dan_100_por_ciento(conexion):
    crear_estudiante(conexion, "E1", notas=(12,), asistencias=["justificada"] * 5)
    indicadores = riesgo.calcular_indicadores(conexion, "E1")
    assert indicadores["porcentaje_asistencia"] == 100
    assert indicadores["n_asistencias"] == 5


def test_solo_faltas_da_0_por_ciento(conexion):
    crear_estudiante(conexion, "E1", asistencias=["falta"] * 5)
    assert riesgo.calcular_indicadores(conexion, "E1")["porcentaje_asistencia"] == 0


def test_tardanza_cuenta_como_asistencia_y_el_porcentaje_se_redondea(conexion):
    # 2 de 3 días penalizables = 66.67 % -> 67
    crear_estudiante(conexion, "E1", asistencias=["presente", "tardanza", "falta"])
    assert riesgo.calcular_indicadores(conexion, "E1")["porcentaje_asistencia"] == 67


def test_promedio_con_decimales_y_notas_extremas(conexion):
    crear_estudiante(conexion, "E1", notas=(0, 20, 7))
    assert riesgo.calcular_indicadores(conexion, "E1")["notas_promedio"] == 9.0
    crear_estudiante(conexion, "E2", notas=(10, 11, 11))
    assert riesgo.calcular_indicadores(conexion, "E2")["notas_promedio"] == 10.67


def test_indicadores_no_mezclan_estudiantes(conexion):
    crear_estudiante(conexion, "E1", notas=(20,), asistencias=["presente"] * 5)
    crear_estudiante(conexion, "E2", notas=(0,), asistencias=["falta"] * 5)
    assert riesgo.calcular_indicadores(conexion, "E1")["notas_promedio"] == 20.0
    assert riesgo.calcular_indicadores(conexion, "E2")["porcentaje_asistencia"] == 0


# ---------- predecir_probabilidad ----------

def test_sin_modelo_lanza_modelo_no_disponible():
    with pytest.raises(riesgo.ModeloNoDisponible):
        riesgo.predecir_probabilidad(None, 12.0, 90)


def test_la_entrada_del_modelo_usa_las_columnas_del_entrenamiento():
    modelo = ModeloFalso(0.4)
    riesgo.predecir_probabilidad(modelo, 13.5, 85)
    entrada = modelo.entradas[0]
    assert list(entrada.columns) == ["Notas_Detalladas", "Registro_Asistencia"]
    assert entrada["Notas_Detalladas"].iloc[0] == 13.5
    assert entrada["Registro_Asistencia"].iloc[0] == 85


def test_toma_la_probabilidad_de_la_clase_1_aunque_el_orden_de_clases_cambie():
    assert riesgo.predecir_probabilidad(ModeloFalso(0.8, classes=(0, 1)), 10, 50) == pytest.approx(0.8)
    assert riesgo.predecir_probabilidad(ModeloFalso(0.8, classes=(1, 0)), 10, 50) == pytest.approx(0.8)


def test_modelo_sin_clase_de_riesgo_lanza_error_de_prediccion():
    class SoloClaseCero:
        classes_ = [0]

        def predict_proba(self, entrada):
            return [[1.0]]

    with pytest.raises(riesgo.ErrorPrediccion, match="clase de riesgo"):
        riesgo.predecir_probabilidad(SoloClaseCero(), 10, 50)


def test_modelo_sin_predict_proba_lanza_error_de_prediccion():
    class SoloPredict:
        classes_ = [0, 1]

        def predict(self, entrada):
            return [1]

    with pytest.raises(riesgo.ErrorPrediccion, match="probabilidades"):
        riesgo.predecir_probabilidad(SoloPredict(), 10, 50)


def test_fallos_internos_del_modelo_se_envuelven_en_error_de_prediccion():
    class Roto:
        classes_ = [0, 1]

        def predict_proba(self, entrada):
            raise ValueError("forma de entrada inesperada")

    with pytest.raises(riesgo.ErrorPrediccion) as info:
        riesgo.predecir_probabilidad(Roto(), 10, 50)
    assert isinstance(info.value.__cause__, ValueError)


def test_los_errores_del_modulo_comparten_clase_base():
    for error in (riesgo.EstudianteNoEncontrado, riesgo.DatosInsuficientes, riesgo.ModeloNoDisponible, riesgo.ErrorPrediccion):
        assert issubclass(error, riesgo.RiesgoError)


# ---------- evaluar_estudiante: estado de las alertas ----------

DATOS_SUFICIENTES = dict(notas=(10,), asistencias=["presente"] * 5)


def test_exactamente_el_minimo_de_datos_ya_evalua(conexion):
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    resultado = riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.2))
    assert resultado["nivel_riesgo"] == "Bajo"
    assert resultado["registros"] == {"calificaciones": 1, "asistencias": 5}


def test_sin_notas_pero_con_asistencias_suficientes_es_datos_insuficientes(conexion):
    crear_estudiante(conexion, "E1", asistencias=["presente"] * 10)
    with pytest.raises(riesgo.DatosInsuficientes, match="0 y 10"):
        riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.9))


@pytest.mark.parametrize("estado_alerta", ["pendiente", "en_seguimiento"])
def test_alerta_abierta_del_mismo_nivel_evita_duplicados(conexion, estado_alerta):
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    primera = riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.9))
    conexion.execute("UPDATE alertas SET estado = ? WHERE id_alerta = ?", (estado_alerta, primera["alerta_creada"]))
    segunda = riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.9))
    assert segunda["alerta_creada"] is None
    assert conexion.execute("SELECT COUNT(*) FROM alertas").fetchone()[0] == 1


@pytest.mark.parametrize("estado_alerta", ["resuelta", "descartada"])
def test_alerta_cerrada_permite_crear_una_nueva(conexion, estado_alerta):
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    primera = riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.9))
    conexion.execute("UPDATE alertas SET estado = ? WHERE id_alerta = ?", (estado_alerta, primera["alerta_creada"]))
    segunda = riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.9))
    assert segunda["alerta_creada"] is not None
    assert conexion.execute("SELECT COUNT(*) FROM alertas").fetchone()[0] == 2


def test_alerta_abierta_de_otro_estudiante_no_bloquea(conexion):
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    crear_estudiante(conexion, "E2", **DATOS_SUFICIENTES)
    riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.9))
    assert riesgo.evaluar_estudiante(conexion, "E2", ModeloFalso(0.9))["alerta_creada"] is not None


def test_alerta_de_bajo_rendimiento_no_bloquea_la_de_desercion(conexion):
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    conexion.execute(
        "INSERT INTO alertas (id_estudiante, tipo_alerta, nivel_riesgo, descripcion) VALUES ('E1', 'bajo_rendimiento', 'alto', 'manual')"
    )
    assert riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.9))["alerta_creada"] is not None


def test_la_alerta_guarda_modelo_probabilidad_y_accion_sugerida(conexion):
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    resultado = riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.73456))
    alerta = conexion.execute("SELECT * FROM alertas WHERE id_alerta = ?", (resultado["alerta_creada"],)).fetchone()
    assert alerta["version_modelo"] == riesgo.VERSION_MODELO
    assert alerta["probabilidad"] == 0.7346  # redondeada a 4 decimales
    assert alerta["tipo_alerta"] == "desercion" and alerta["nivel_riesgo"] == "alto"
    assert riesgo.ACCIONES["Alto"] in alerta["descripcion"]


def test_la_probabilidad_se_redondea_antes_de_clasificar(conexion):
    # 0.69996 redondea a 0.7 -> "Alto"; el semáforo usa el valor ya redondeado que se guarda en la alerta
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    assert riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.69996))["nivel_riesgo"] == "Alto"


def test_cambio_de_nivel_marca_el_registro_para_resincronizar(conexion):
    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    conexion.execute("UPDATE estudiantes SET is_synced = 1 WHERE id_estudiante = 'E1'")
    riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.1))  # Pendiente -> Bajo
    assert conexion.execute("SELECT is_synced FROM estudiantes").fetchone()[0] == 0
    conexion.execute("UPDATE estudiantes SET is_synced = 1")
    sin_cambio = riesgo.evaluar_estudiante(conexion, "E1", ModeloFalso(0.1))
    assert sin_cambio["cambio"] is False
    assert conexion.execute("SELECT is_synced FROM estudiantes").fetchone()[0] == 1  # no se re-marca sin cambio


def test_error_de_prediccion_no_deja_cambios_a_medias(conexion):
    class Roto:
        classes_ = [0, 1]

        def predict_proba(self, entrada):
            raise ValueError("boom")

    crear_estudiante(conexion, "E1", **DATOS_SUFICIENTES)
    with pytest.raises(riesgo.ErrorPrediccion):
        riesgo.evaluar_estudiante(conexion, "E1", Roto())
    assert conexion.execute("SELECT riesgo_desercion FROM estudiantes").fetchone()[0] == "Pendiente"
    assert conexion.execute("SELECT COUNT(*) FROM alertas").fetchone()[0] == 0


def test_evaluar_todos_sin_estudiantes(conexion):
    assert riesgo.evaluar_todos(conexion, ModeloFalso(0.5)) == {
        "evaluados": 0, "sin_datos_suficientes": 0, "alertas_creadas": 0,
        "por_nivel": {"Bajo": 0, "Medio": 0, "Alto": 0}, "total_estudiantes": 0,
    }


def test_evaluar_todos_no_cuenta_alertas_ya_existentes(conexion):
    crear_estudiante(conexion, "A1", **DATOS_SUFICIENTES)
    riesgo.evaluar_todos(conexion, ModeloFalso(0.9))
    segunda = riesgo.evaluar_todos(conexion, ModeloFalso(0.9))
    assert segunda["evaluados"] == 1 and segunda["alertas_creadas"] == 0


def test_evaluar_todos_propaga_modelo_no_disponible(conexion):
    crear_estudiante(conexion, "A1", **DATOS_SUFICIENTES)
    with pytest.raises(riesgo.ModeloNoDisponible):
        riesgo.evaluar_todos(conexion, None)
