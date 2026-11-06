"""Pruebas de los endpoints del semáforo de riesgo (modelo simulado, base temporal)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

import api.database as database
import api.main as main


class ModeloFalso:
    classes_ = [0, 1]

    def __init__(self, probabilidad):
        self.probabilidad = probabilidad

    def predict_proba(self, entrada):
        return [[1 - self.probabilidad, self.probabilidad]]


def preparar(tmp_path, monkeypatch, modelo):
    test_db = tmp_path / "dataclass_riesgo_api.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setattr(main, "motor_predictivo", modelo)
    monkeypatch.setenv("DATACLASS_JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    main.SECRET_KEY = "test-secret-that-is-long-enough-for-tests"


def autenticar_como_directivo(client, monkeypatch):
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", "Prueba-segura-2026!")
    respuesta = client.post("/api/v1/auth/login", data={"username": "admin@test.edu", "password": "Prueba-segura-2026!"})
    assert respuesta.status_code == 200, respuesta.text
    client.headers.update({"Authorization": f"Bearer {respuesta.json()['access_token']}"})


def crear_estudiante(client, id_estudiante):
    respuesta = client.post("/api/v1/estudiantes", json={"id_estudiante": id_estudiante, "nombre_completo": "Alumno de Prueba", "aula": "A-1"})
    assert respuesta.status_code == 201, respuesta.text


def registrar_nota(client, id_estudiante, nota):
    respuesta = client.post("/api/v1/calificaciones", json={"id_estudiante": id_estudiante, "curso_modulo": "Matemática", "nota_obtenida": nota, "periodo_evaluacion": "Bimestre 1"})
    assert respuesta.status_code == 201, respuesta.text


def registrar_asistencia(client, id_estudiante, dia, estado="falta"):
    fecha = (date(2026, 10, 1) + timedelta(days=dia)).isoformat()
    respuesta = client.post("/api/v1/asistencias", json={"id_estudiante": id_estudiante, "fecha": fecha, "estado_asistencia": estado})
    assert respuesta.status_code == 201, respuesta.text


def test_registrar_datos_actualiza_el_semaforo_y_crea_la_alerta(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, ModeloFalso(0.85))
    with TestClient(main.app) as client:
        autenticar_como_directivo(client, monkeypatch)
        crear_estudiante(client, "SEM-001")
        registrar_nota(client, "SEM-001", 8)
        for dia in range(4):
            registrar_asistencia(client, "SEM-001", dia)
        # Con 4 asistencias todavía no hay datos suficientes: no se evalúa ni se alerta.
        assert client.get("/api/v1/estudiantes/SEM-001").json()["riesgo_desercion"] == "Pendiente"
        assert client.get("/api/v1/alertas", params={"id_estudiante": "SEM-001"}).json() == []

        registrar_asistencia(client, "SEM-001", 4)  # la 5.ª dispara la evaluación automática
        assert client.get("/api/v1/estudiantes/SEM-001").json()["riesgo_desercion"] == "Alto"
        alertas = client.get("/api/v1/alertas", params={"id_estudiante": "SEM-001"}).json()
        assert len(alertas) == 1
        assert alertas[0]["tipo_alerta"] == "desercion" and alertas[0]["nivel_riesgo"] == "alto"
        assert alertas[0]["probabilidad"] == 0.85

        repetida = client.post("/api/v1/estudiantes/SEM-001/evaluar-riesgo")
        assert repetida.status_code == 200, repetida.text
        assert repetida.json()["nivel_riesgo"] == "Alto" and repetida.json()["alerta_creada"] is None
        assert len(client.get("/api/v1/alertas", params={"id_estudiante": "SEM-001"}).json()) == 1


def test_errores_de_evaluacion(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, None)
    with TestClient(main.app) as client:
        assert client.post("/api/v1/estudiantes/SEM-X/evaluar-riesgo").status_code == 401
        autenticar_como_directivo(client, monkeypatch)
        assert client.post("/api/v1/estudiantes/NO-EXISTE/evaluar-riesgo").status_code == 404

        crear_estudiante(client, "SEM-002")
        assert client.post("/api/v1/estudiantes/SEM-002/evaluar-riesgo").status_code == 422  # sin datos

        registrar_nota(client, "SEM-002", 12)
        for dia in range(5):
            registrar_asistencia(client, "SEM-002", dia, "presente")
        # Sin modelo cargado el registro funciona (arriba) pero la evaluación informa 503.
        assert client.post("/api/v1/estudiantes/SEM-002/evaluar-riesgo").status_code == 503
        assert client.get("/api/v1/estudiantes/SEM-002").json()["riesgo_desercion"] == "Pendiente"


def test_evaluar_todos_solo_para_directivos(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, ModeloFalso(0.2))
    with TestClient(main.app) as client:
        autenticar_como_directivo(client, monkeypatch)
        crear_estudiante(client, "SEM-003")
        registrar_nota(client, "SEM-003", 17)
        for dia in range(5):
            registrar_asistencia(client, "SEM-003", dia, "presente")
        crear_estudiante(client, "SEM-004")  # sin datos suficientes

        resumen = client.post("/api/v1/analitica/evaluar-todos")
        assert resumen.status_code == 200, resumen.text
        assert resumen.json()["total_estudiantes"] == 2
        assert resumen.json()["sin_datos_suficientes"] == 1
        assert resumen.json()["por_nivel"]["Bajo"] == 1

        assert client.post("/api/v1/usuarios", json={
            "correo": "profesor@test.edu", "nombre_completo": "Docente de prueba",
            "rol": "docente", "aula": "A-1", "password": "Docente-seguro-2026!",
        }).status_code == 201
        login = client.post("/api/v1/auth/login", data={"username": "profesor@test.edu", "password": "Docente-seguro-2026!"})
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        assert client.post("/api/v1/analitica/evaluar-todos").status_code == 403
        assert client.post("/api/v1/estudiantes/SEM-003/evaluar-riesgo").status_code == 200  # un docente sí puede evaluar un caso de su aula
