"""Pruebas del endpoint de carga masiva: permisos, simulación por defecto, todo o nada y bitácora."""
from fastapi.testclient import TestClient

import api.database as database
import api.main as main

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"


def preparar(tmp_path, monkeypatch):
    test_db = tmp_path / "importacion_api.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)


def login(client, correo, clave):
    r = client.post("/api/v1/auth/login", data={"username": correo, "password": clave})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def subir(client, headers, tipo, texto, nombre="datos.csv", **params):
    return client.post(
        f"/api/v1/importaciones/{tipo}", headers=headers, params=params,
        files={"archivo": (nombre, texto.encode("utf-8"), "text/csv")},
    )


def montar(client):
    admin = login(client, "admin@test.edu", CLAVE_ADMIN)
    r = subir(client, admin, "estudiantes",
              "id_estudiante,nombre_completo,aula\nA1,Ana Pérez,A-1\nB1,Beto Ruiz,B-1\n", simular="false")
    assert r.status_code == 200 and r.json()["aplicado"], r.text
    r = client.post("/api/v1/usuarios", headers=admin, json={
        "correo": "docente.a@test.edu", "nombre_completo": "Docente A", "rol": "docente",
        "aula": "A-1", "password": CLAVE_DOCENTE})
    assert r.status_code == 201, r.text
    return admin, login(client, "docente.a@test.edu", CLAVE_DOCENTE)


def test_por_defecto_solo_simula(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        r = subir(client, admin, "estudiantes", "id_estudiante,nombre_completo\nE1,Ana\n")
        assert r.status_code == 200
        assert r.json()["simulacion"] is True and r.json()["aplicado"] is False
        assert client.get("/api/v1/estudiantes", headers=admin).json()["items"] == []


def test_requiere_autenticacion(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        r = client.post("/api/v1/importaciones/estudiantes",
                        files={"archivo": ("a.csv", b"id,nombre\nE1,Ana\n", "text/csv")})
        assert r.status_code == 401


def test_docente_no_importa_estudiantes_y_solo_su_aula(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        _, docente = montar(client)
        r = subir(client, docente, "estudiantes", "id_estudiante,nombre_completo\nE1,Ana\n", simular="false")
        assert r.status_code == 403
        r = subir(client, docente, "calificaciones",
                  "id_estudiante,curso,nota,periodo\nA1,Mate,15,B1\nB1,Mate,15,B1\n", simular="false")
        assert r.status_code == 200
        assert r.json()["aplicado"] is False and r.json()["errores"][0]["fila"] == 3
        r = subir(client, docente, "calificaciones", "id_estudiante,curso,nota,periodo\nA1,Mate,15,B1\n", simular="false")
        assert r.json()["aplicado"] is True


def test_reimportar_no_duplica_y_queda_en_bitacora(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, _ = montar(client)
        texto = "id_estudiante,fecha,estado\nA1,2026-10-01,presente\n"
        assert subir(client, admin, "asistencias", texto, simular="false").json()["nuevas"] == 1
        segundo = subir(client, admin, "asistencias", texto, simular="false").json()
        assert (segundo["nuevas"], segundo["ya_existentes"]) == (0, 1)
        items = client.get("/api/v1/auditoria", headers=admin, params={"accion": "escritura"}).json()["items"]
        assert any("importacion tipo=asistencias" in (i.get("detalle") or "") for i in items)


def test_archivo_invalido_responde_422_y_grande_413(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    monkeypatch.setattr(main.importacion, "MAX_BYTES", 50)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        assert subir(client, admin, "estudiantes", "id_estudiante\nE1\n").status_code == 422  # falta nombre_completo
        assert subir(client, admin, "estudiantes", "id_estudiante,nombre_completo\n" + "E1,Ana\n" * 20).status_code == 413
        assert subir(client, admin, "estudiantes", "x", nombre="datos.exe").status_code == 422
