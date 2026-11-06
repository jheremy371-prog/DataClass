"""Pruebas de aislamiento por aula, cuentas desactivadas y arranque con secreto JWT obligatorio."""
import pytest
from fastapi.testclient import TestClient

import api.database as database
import api.main as main

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"


def preparar(tmp_path, monkeypatch):
    test_db = tmp_path / "acceso_aulas.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)


def login(client, correo, clave):
    respuesta = client.post("/api/v1/auth/login", data={"username": correo, "password": clave})
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def montar_escenario(client):
    """Dos estudiantes (A-1 y B-1) con alerta e intervención, un docente de A-1 y otro sin aula."""
    admin = login(client, "admin@test.edu", CLAVE_ADMIN)
    ids_alerta = {}
    ids_intervencion = {}
    for id_estudiante, aula in (("EST-A", "A-1"), ("EST-B", "B-1")):
        r = client.post("/api/v1/estudiantes", headers=admin, json={
            "id_estudiante": id_estudiante, "nombre_completo": f"Alumno {id_estudiante}", "aula": aula,
        })
        assert r.status_code == 201, r.text
        r = client.post("/api/v1/alertas", headers=admin, json={
            "id_estudiante": id_estudiante, "tipo_alerta": "desercion", "nivel_riesgo": "alto",
            "descripcion": "Alerta de prueba para aislamiento",
        })
        assert r.status_code == 201, r.text
        ids_alerta[id_estudiante] = r.json()["id_alerta"]
        r = client.post("/api/v1/intervenciones", headers=admin, json={
            "id_estudiante": id_estudiante, "tutor": "Tutor de prueba", "tipo_intervencion": "tutoria",
            "descripcion": "Intervención de prueba", "fecha_intervencion": "2026-10-16",
        })
        assert r.status_code == 201, r.text
        ids_intervencion[id_estudiante] = r.json()["id_intervencion"]

    usuarios = {}
    for correo, aula in (("docente.a@test.edu", "A-1"), ("docente.sin.aula@test.edu", None)):
        cuerpo = {"correo": correo, "nombre_completo": "Docente de prueba", "rol": "docente", "password": CLAVE_DOCENTE}
        if aula:
            cuerpo["aula"] = aula
        r = client.post("/api/v1/usuarios", headers=admin, json=cuerpo)
        assert r.status_code == 201, r.text
        usuarios[correo] = r.json()["id_usuario"]
    return {
        "admin": admin,
        "docente_a": login(client, "docente.a@test.edu", CLAVE_DOCENTE),
        "docente_sin_aula": login(client, "docente.sin.aula@test.edu", CLAVE_DOCENTE),
        "alertas": ids_alerta,
        "intervenciones": ids_intervencion,
        "id_docente_a": usuarios["docente.a@test.edu"],
    }


def test_docente_solo_ve_datos_de_su_aula(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        esc = montar_escenario(client)
        docente = esc["docente_a"]

        estudiantes = client.get("/api/v1/estudiantes", headers=docente).json()["items"]
        assert [e["id_estudiante"] for e in estudiantes] == ["EST-A"]
        # un docente no puede ampliar la lista con el filtro de aula
        filtrados = client.get("/api/v1/estudiantes", headers=docente, params={"aula": "B-1"}).json()["items"]
        assert [e["id_estudiante"] for e in filtrados] == ["EST-A"]

        alertas = client.get("/api/v1/alertas", headers=docente).json()
        assert {a["id_estudiante"] for a in alertas} == {"EST-A"}
        intervenciones = client.get("/api/v1/intervenciones", headers=docente).json()
        assert {i["id_estudiante"] for i in intervenciones} == {"EST-A"}
        # pedir explícitamente los datos de otra aula no devuelve nada
        assert client.get("/api/v1/alertas", headers=docente, params={"id_estudiante": "EST-B"}).json() == []


def test_docente_no_accede_a_estudiantes_de_otra_aula(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        esc = montar_escenario(client)
        d = esc["docente_a"]
        base = "/api/v1/estudiantes/EST-B"

        assert client.get(base, headers=d).status_code == 404
        # Modificar estudiantes es solo de directivos (N-03): ni los ajenos ni los propios.
        assert client.patch(base, headers=d, json={"nombre_completo": "Nombre cambiado"}).status_code == 403
        assert client.patch("/api/v1/estudiantes/EST-A", headers=d, json={"aula": "B-1"}).status_code == 403
        assert client.get(f"{base}/calificaciones", headers=d).status_code == 404
        assert client.get(f"{base}/asistencias", headers=d).status_code == 404
        assert client.post(f"{base}/evaluar-riesgo", headers=d).status_code == 404

        nota = {"id_estudiante": "EST-B", "curso_modulo": "Matemática", "nota_obtenida": 10, "periodo_evaluacion": "B1"}
        assert client.post("/api/v1/calificaciones", headers=d, json=nota).status_code == 404
        asistencia = {"id_estudiante": "EST-B", "fecha": "2026-10-16", "estado_asistencia": "presente"}
        assert client.post("/api/v1/asistencias", headers=d, json=asistencia).status_code == 404
        alerta = {"id_estudiante": "EST-B", "tipo_alerta": "desercion", "nivel_riesgo": "bajo", "descripcion": "No debe crearse"}
        assert client.post("/api/v1/alertas", headers=d, json=alerta).status_code == 404
        intervencion = {
            "id_estudiante": "EST-B", "tutor": "Tutor", "tipo_intervencion": "tutoria",
            "descripcion": "No debe crearse", "fecha_intervencion": "2026-10-16",
        }
        assert client.post("/api/v1/intervenciones", headers=d, json=intervencion).status_code == 404
        assert client.patch(f"/api/v1/alertas/{esc['alertas']['EST-B']}", headers=d, json={"estado": "descartada"}).status_code == 404
        assert client.patch(
            f"/api/v1/intervenciones/{esc['intervenciones']['EST-B']}", headers=d, json={"resultado": "No debe cambiar"}
        ).status_code == 404

        # lo de su propia aula sigue funcionando
        assert client.get("/api/v1/estudiantes/EST-A", headers=d).status_code == 200
        assert client.post("/api/v1/calificaciones", headers=d, json={**nota, "id_estudiante": "EST-A"}).status_code == 201
        assert client.patch(f"/api/v1/alertas/{esc['alertas']['EST-A']}", headers=d, json={"estado": "en_seguimiento"}).status_code == 200

        # y la alerta de B no cambió
        alerta_b = client.get("/api/v1/alertas", headers=esc["admin"], params={"id_estudiante": "EST-B"}).json()[0]
        assert alerta_b["estado"] == "pendiente"


def test_docente_sin_aula_no_ve_ningun_estudiante(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        esc = montar_escenario(client)
        d = esc["docente_sin_aula"]
        assert client.get("/api/v1/estudiantes", headers=d).json()["items"] == []
        assert client.get("/api/v1/alertas", headers=d).json() == []
        assert client.get("/api/v1/intervenciones", headers=d).json() == []
        assert client.get("/api/v1/estudiantes/EST-A", headers=d).status_code == 404
        assert client.post("/api/v1/estudiantes/EST-A/evaluar-riesgo", headers=d).status_code == 404


def test_directivo_accede_a_todas_las_aulas(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        esc = montar_escenario(client)
        admin = esc["admin"]
        ids = {e["id_estudiante"] for e in client.get("/api/v1/estudiantes", headers=admin).json()["items"]}
        assert ids == {"EST-A", "EST-B"}
        assert client.get("/api/v1/estudiantes/EST-B", headers=admin).status_code == 200
        assert len(client.get("/api/v1/alertas", headers=admin).json()) == 2


def test_cuenta_desactivada_pierde_acceso_con_token_vigente(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        esc = montar_escenario(client)
        assert client.get("/api/v1/estudiantes", headers=esc["docente_a"]).status_code == 200
        r = client.patch(f"/api/v1/usuarios/{esc['id_docente_a']}", headers=esc["admin"], json={"activo": 0})
        assert r.status_code == 200, r.text
        assert client.get("/api/v1/estudiantes", headers=esc["docente_a"]).status_code == 401
        assert client.get("/api/v1/estudiantes/EST-A", headers=esc["docente_a"]).status_code == 401


@pytest.mark.parametrize("secreto", ["", "corto", "REEMPLAZA_CON_UN_SECRETO_ALEATORIO_DE_AL_MENOS_32_CARACTERES"])
def test_la_configuracion_rechaza_secretos_invalidos(monkeypatch, secreto):
    monkeypatch.setattr(main, "SECRET_KEY", secreto)
    with pytest.raises(RuntimeError, match="DATACLASS_JWT_SECRET"):
        main.validar_configuracion()


def test_la_api_no_arranca_sin_secreto(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass


def test_la_configuracion_acepta_un_secreto_valido(monkeypatch):
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    main.validar_configuracion()
