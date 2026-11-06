"""Bitácora de auditoría: módulo (SQLite) y su integración con la API."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.database as database
import api.main as main
from api import auditoria

SECRETO = "test-secret-that-is-long-enough-for-tests"


@pytest.fixture
def bd(tmp_path, monkeypatch):
    ruta = tmp_path / "auditoria.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(main, "DB_PATH", ruta)
    monkeypatch.setenv("DATACLASS_JWT_SECRET", SECRETO)
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    database.inicializar_esquema()
    return ruta


def filas(ruta, where="1=1", params=()):
    with sqlite3.connect(ruta) as con:
        con.row_factory = sqlite3.Row
        return [dict(f) for f in con.execute(f"SELECT * FROM auditoria WHERE {where} ORDER BY id_auditoria", params)]


# ---------- módulo ----------
def test_registrar_y_consultar(bd):
    with sqlite3.connect(bd) as con:
        auditoria.registrar(con, "lectura", id_usuario=3, rol="docente", ip="10.0.0.1", metodo="GET",
                            ruta="/api/v1/estudiantes/E1", id_estudiante="E1", estado_http=200)
        auditoria.registrar(con, "escritura", id_usuario=4, id_estudiante="E2", estado_http=201)
        assert [f["id_estudiante"] for f in auditoria.consultar(con, id_estudiante="E1")] == ["E1"]
        assert len(auditoria.consultar(con, id_usuario=4)) == 1
        assert len(auditoria.consultar(con)) == 2


def test_la_bitacora_es_de_solo_anexado(bd):
    with sqlite3.connect(bd) as con:
        auditoria.registrar(con, "lectura")
        with pytest.raises(sqlite3.DatabaseError, match="solo anexado"):
            con.execute("UPDATE auditoria SET ip = 'x'")
        with pytest.raises(sqlite3.DatabaseError, match="solo anexado"):
            con.execute("DELETE FROM auditoria")


def test_depurar_borra_solo_lo_antiguo_y_restaura_el_trigger(bd):
    con = sqlite3.connect(bd)
    con.execute("INSERT INTO auditoria (fecha_utc, accion) VALUES ('2020-01-01 00:00:00.000', 'lectura')")
    auditoria.registrar(con, "lectura")
    assert auditoria.depurar(con, 365) == 1
    assert len(auditoria.consultar(con)) == 1
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM auditoria")
    with pytest.raises(ValueError):
        auditoria.depurar(con, 5)
    con.close()


def test_registrar_no_lanza_si_falla(tmp_path):
    con = sqlite3.connect(tmp_path / "sin_tabla.db")  # no existe la tabla auditoria
    auditoria.registrar(con, "lectura")  # no debe propagar la excepción
    con.close()


def test_helpers():
    assert auditoria.clasificar_metodo("get") == "lectura"
    assert auditoria.clasificar_metodo("PATCH") == "escritura"
    assert auditoria.clasificar_metodo("DELETE") == "eliminacion"
    assert auditoria.estudiante_de_ruta("/api/v1/estudiantes/E1/asistencias") == "E1"
    assert auditoria.estudiante_de_ruta("/api/v1/alertas", {"id_estudiante": "E2"}) == "E2"
    assert auditoria.estudiante_de_ruta("/api/v1/alertas") is None
    assert auditoria.omitir_ruta("/api/v1/auth/login") and auditoria.omitir_ruta("/docs")
    assert not auditoria.omitir_ruta("/api/v1/estudiantes")


# ---------- integración con la API ----------
def login(client, correo, password):
    return client.post("/api/v1/auth/login", data={"username": correo, "password": password})


def test_api_registra_accesos_login_y_rechazos(bd, monkeypatch):
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@aud.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", "Prueba-segura-2026!")
    with TestClient(main.app) as client:
        assert client.get("/api/v1/estudiantes").status_code == 401           # sin token
        assert login(client, "admin@aud.edu", "clave-incorrecta-123").status_code == 401
        r = login(client, "admin@aud.edu", "Prueba-segura-2026!")
        assert r.status_code == 200
        client.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
        est = {"id_estudiante": "AUD-1", "nombre_completo": "Estudiante Auditoria", "aula": "A-1"}
        assert client.post("/api/v1/estudiantes", json=est).status_code == 201
        assert client.get("/api/v1/estudiantes/AUD-1").status_code == 200
        assert client.delete("/api/v1/estudiantes/AUD-1").status_code == 204

    acciones = [f["accion"] for f in filas(bd)]
    assert {"login_fallido", "login_ok", "lectura", "escritura", "eliminacion"} <= set(acciones)
    rechazo = filas(bd, "estado_http = 401 AND accion = 'lectura'")
    assert rechazo and rechazo[0]["id_usuario"] is None                         # intento sin token queda registrado
    lectura = filas(bd, "id_estudiante = 'AUD-1' AND accion = 'lectura'")
    assert lectura and lectura[0]["id_usuario"] is not None and lectura[0]["rol"] == "directivo"
    # No se guardan cuerpos ni datos personales: el nombre del estudiante no aparece en ninguna columna.
    assert all("Estudiante Auditoria" not in str(f.values()) for f in filas(bd))
    # La baja local deja pendiente la eliminación en la nube.
    with sqlite3.connect(bd) as con:
        assert con.execute("SELECT id_estudiante FROM eliminaciones_nube").fetchall() == [("AUD-1",)]


def test_endpoint_auditoria_solo_directivos(bd, monkeypatch):
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@aud2.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", "Prueba-segura-2026!")
    with TestClient(main.app) as client:
        assert client.get("/api/v1/auditoria").status_code == 401
        token = login(client, "admin@aud2.edu", "Prueba-segura-2026!").json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
        docente = {"correo": "doc@aud2.edu", "nombre_completo": "Docente Uno", "rol": "docente",
                   "aula": "A-1", "password": "Otra-clave-larga-2026"}
        assert client.post("/api/v1/usuarios", json=docente).status_code == 201
        cuerpo = client.get("/api/v1/auditoria", params={"accion": "login_ok"})
        assert cuerpo.status_code == 200 and cuerpo.json()["items"]
        assert client.get("/api/v1/auditoria", params={"desde": "2026-12-01", "hasta": "2026-01-01"}).status_code == 422

        token_doc = login(client, "doc@aud2.edu", "Otra-clave-larga-2026").json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token_doc}"})
        assert client.get("/api/v1/auditoria").status_code == 403


def test_cabeceras_de_seguridad(bd, monkeypatch):
    monkeypatch.setenv("DATACLASS_FORZAR_HTTPS", "1")
    with TestClient(main.app) as client:
        r = client.get("/api/v1/estudiantes")
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert "max-age" in r.headers["Strict-Transport-Security"]
