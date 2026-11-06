"""Fase 1: DNI oculto a docentes en el listado, exportaciones en la bitácora y modelo cargado en lifespan."""
import sqlite3

from fastapi.testclient import TestClient

import api.database as database
import api.main as main

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"


def preparar(tmp_path, monkeypatch):
    ruta = tmp_path / "fase1.db"
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


def test_el_listado_no_devuelve_dni_a_docentes_pero_si_a_directivos(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        r = client.post("/api/v1/estudiantes", headers=admin, json={
            "id_estudiante": "EST-D1", "nombre_completo": "Alumno Con Dni", "aula": "A-1", "dni": "12345678",
        })
        assert r.status_code == 201, r.text
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "docente.dni@test.edu", "nombre_completo": "Docente Dni", "rol": "docente",
            "password": CLAVE_DOCENTE, "aula": "A-1",
        })
        assert r.status_code == 201, r.text
        docente = login(client, "docente.dni@test.edu", CLAVE_DOCENTE)

        items_docente = client.get("/api/v1/estudiantes", headers=docente).json()["items"]
        assert [e["id_estudiante"] for e in items_docente] == ["EST-D1"]
        assert all("dni" not in e for e in items_docente)

        items_directivo = client.get("/api/v1/estudiantes", headers=admin).json()["items"]
        assert items_directivo[0]["dni"] == "12345678"

    with sqlite3.connect(ruta) as con:
        detalles = [f[0] for f in con.execute(
            "SELECT detalle FROM auditoria WHERE metodo = 'GET' AND ruta = '/api/v1/estudiantes' ORDER BY id_auditoria")]
    assert any("sin DNI" in d for d in detalles) and any("con DNI" in d for d in detalles)


def test_registrar_exportacion_queda_en_la_bitacora_y_es_solo_para_directivos(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "docente.exp@test.edu", "nombre_completo": "Docente Exp", "rol": "docente",
            "password": CLAVE_DOCENTE,
        })
        assert r.status_code == 201, r.text
        docente = login(client, "docente.exp@test.edu", CLAVE_DOCENTE)

        cuerpo = {"recurso": "estudiantes", "filas": 25}
        assert client.post("/api/v1/exportaciones", headers=docente, json=cuerpo).status_code == 403
        assert client.post("/api/v1/exportaciones", json=cuerpo).status_code == 401
        assert client.post("/api/v1/exportaciones", headers=admin, json=cuerpo).status_code == 204
        assert client.post("/api/v1/exportaciones", headers=admin, json={"recurso": "x", "filas": -1}).status_code == 422

    with sqlite3.connect(ruta) as con:
        filas = con.execute(
            "SELECT detalle FROM auditoria WHERE metodo = 'POST' AND ruta = '/api/v1/exportaciones' AND estado_http = 204"
        ).fetchall()
    assert len(filas) == 1 and "25 filas de estudiantes" in filas[0][0]


def test_el_modelo_se_carga_al_arrancar_y_no_al_importar(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    modelo_falso = object()
    llamadas = []
    monkeypatch.setattr(main, "motor_predictivo", main._SIN_CARGAR)
    monkeypatch.setattr(main, "_cargar_modelo", lambda: llamadas.append(1) or modelo_falso)
    assert main.modelo_activo() is None  # antes del arranque no hay modelo
    with TestClient(main.app) as client:
        assert llamadas == [1]
        assert main.modelo_activo() is modelo_falso
        assert client.get("/api/v1/estado").json()["modelo_disponible"] is True


def test_si_el_modelo_no_pasa_la_verificacion_la_api_arranca_sin_modelo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "motor_predictivo", main._SIN_CARGAR)
    monkeypatch.setattr(main, "_cargar_modelo", lambda: None)
    with TestClient(main.app) as client:
        assert main.modelo_activo() is None
        assert client.get("/api/v1/estado").json()["modelo_disponible"] is False


def test_con_la_nube_activada_sin_clave_de_seudonimo_la_api_no_arranca(tmp_path, monkeypatch):
    import pytest

    preparar(tmp_path, monkeypatch)
    monkeypatch.setenv("DATACLASS_SYNC_AUTO", "1")
    monkeypatch.delenv("DATACLASS_SEUDONIMO_CLAVE", raising=False)
    with pytest.raises(RuntimeError, match="DATACLASS_SEUDONIMO_CLAVE"):
        main.validar_configuracion()
