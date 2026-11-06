"""Hallazgos 6, 7 y 8: la API normaliza y valida igual que la importación (aula, curso, periodo, fecha)."""
import sqlite3

from fastapi.testclient import TestClient

import api.database as database
import api.main as main

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"


def preparar(tmp_path, monkeypatch):
    ruta = tmp_path / "normalizacion.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(main, "DB_PATH", ruta)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)
    return ruta


def login(client, correo, clave):
    r = client.post("/api/v1/auth/login", data={"username": correo, "password": clave})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def crear_estudiante(client, admin, id_est, aula):
    return client.post("/api/v1/estudiantes", headers=admin, json={
        "id_estudiante": id_est, "nombre_completo": "Alumno Prueba", "aula": aula})


def test_el_aula_se_normaliza_y_el_docente_ve_al_alumno(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        r = crear_estudiante(client, admin, "EST-1", "a-302 ")
        assert r.status_code == 201 and r.json()["aula"] == "A-302"
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "doc@test.edu", "nombre_completo": "Docente", "rol": "docente",
            "password": CLAVE_DOCENTE, "aula": " A-302"})
        assert r.status_code == 201 and r.json()["aula"] == "A-302"
        docente = login(client, "doc@test.edu", CLAVE_DOCENTE)
        items = client.get("/api/v1/estudiantes", headers=docente).json()["items"]
        assert [e["id_estudiante"] for e in items] == ["EST-1"]
        # el directivo puede filtrar escribiendo el aula de cualquier forma
        filtrados = client.get("/api/v1/estudiantes", headers=admin, params={"aula": "a-302"}).json()["items"]
        assert [e["id_estudiante"] for e in filtrados] == ["EST-1"]
        # y al editar el aula también se normaliza
        r = client.patch("/api/v1/estudiantes/EST-1", headers=admin, json={"aula": "b-1"})
        assert r.status_code == 200 and r.json()["aula"] == "B-1"


def test_aula_con_formula_se_rechaza(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        assert crear_estudiante(client, admin, "EST-1", "=1+1").status_code == 422
        crear_estudiante(client, admin, "EST-2", "A-1")
        assert client.patch("/api/v1/estudiantes/EST-2", headers=admin, json={"aula": "@SUM(A1)"}).status_code == 422
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "doc@test.edu", "nombre_completo": "Docente", "rol": "docente",
            "password": CLAVE_DOCENTE, "aula": "=cmd"})
        assert r.status_code == 422


def test_la_api_valida_notas_como_la_importacion(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        crear_estudiante(client, admin, "EST-1", "A-1")
        base = {"id_estudiante": "EST-1", "curso_modulo": "Matemática", "nota_obtenida": 14, "periodo_evaluacion": "2026-II"}
        assert client.post("/api/v1/calificaciones", headers=admin, json={**base, "curso_modulo": "=1+1"}).status_code == 422
        assert client.post("/api/v1/calificaciones", headers=admin, json={**base, "periodo_evaluacion": "@x"}).status_code == 422
        assert client.post("/api/v1/calificaciones", headers=admin, json={**base, "nota_obtenida": 21}).status_code == 422
        r = client.post("/api/v1/calificaciones", headers=admin, json={**base, "curso_modulo": "  Matemática   II "})
        assert r.status_code == 201 and r.json()["curso_modulo"] == "Matemática II"  # espacios colapsados


def test_el_curso_se_unifica_con_la_grafia_ya_guardada(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        crear_estudiante(client, admin, "EST-1", "A-1")
        base = {"id_estudiante": "EST-1", "nota_obtenida": 14, "periodo_evaluacion": "B1"}
        assert client.post("/api/v1/calificaciones", headers=admin, json={**base, "curso_modulo": "Matemática"}).status_code == 201
        r = client.post("/api/v1/calificaciones", headers=admin, json={**base, "curso_modulo": "matematica", "periodo_evaluacion": "B2"})
        assert r.status_code == 201 and r.json()["curso_modulo"] == "Matemática"
        # al corregir una nota también se unifica
        r = client.patch(f"/api/v1/calificaciones/{r.json()['id_calificacion']}", headers=admin, json={"curso_modulo": "MATEMATICA"})
        assert r.status_code == 200 and r.json()["curso_modulo"] == "Matemática"
        # un curso distinto no se toca
        r = client.post("/api/v1/calificaciones", headers=admin, json={**base, "curso_modulo": "Comunicación"})
        assert r.json()["curso_modulo"] == "Comunicación"


def test_asistencia_con_fecha_futura_se_rechaza(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        crear_estudiante(client, admin, "EST-1", "A-1")
        futura = {"id_estudiante": "EST-1", "fecha": "2999-01-01", "estado_asistencia": "presente"}
        assert client.post("/api/v1/asistencias", headers=admin, json=futura).status_code == 422
        antigua = {**futura, "fecha": "1999-12-31"}
        assert client.post("/api/v1/asistencias", headers=admin, json=antigua).status_code == 422
        ok = {**futura, "fecha": "2026-10-01"}
        assert client.post("/api/v1/asistencias", headers=admin, json=ok).status_code == 201


def test_al_iniciar_se_normalizan_las_aulas_ya_guardadas(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    database.inicializar_esquema()
    with sqlite3.connect(ruta) as con:
        con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo, aula, is_synced) VALUES ('E1', 'Ana', 'a-302 ', 1)")
        con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo, aula, is_synced) VALUES ('E2', 'Luis', '=1+1', 1)")
        con.execute("INSERT INTO usuarios (correo, nombre_completo, rol, aula, password_hash) VALUES ('d@test.edu', 'D', 'docente', ' a-302', 'x')")
    database.inicializar_esquema()
    with sqlite3.connect(ruta) as con:
        assert con.execute("SELECT aula, is_synced FROM estudiantes WHERE id_estudiante = 'E1'").fetchone() == ("A-302", 0)
        assert con.execute("SELECT aula, is_synced FROM estudiantes WHERE id_estudiante = 'E2'").fetchone() == ("=1+1", 1)  # no normalizable: intacta
        assert con.execute("SELECT aula FROM usuarios").fetchone() == ("A-302",)
    assert database.inicializar_esquema() is None  # idempotente: una segunda pasada no falla ni cambia nada
