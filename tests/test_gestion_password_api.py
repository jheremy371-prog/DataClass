"""H-04 en la API: cambio y restablecimiento de contraseña, token_version, último directivo y rehash al iniciar sesión."""
import hashlib
import sqlite3

from fastapi.testclient import TestClient

import api.database as database
import api.main as main
from api import seguridad
from api.limitador import LimitadorIntentos

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"
CLAVE_NUEVA = "Clave-nueva-larga-2027!"


def preparar(tmp_path, monkeypatch):
    ruta = tmp_path / "password.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(main, "DB_PATH", ruta)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    monkeypatch.setattr(main, "limitador_correo", LimitadorIntentos(max_intentos=50))
    monkeypatch.setattr(main, "limitador_ip", LimitadorIntentos(max_intentos=50))
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)
    return ruta


def login(client, correo, clave):
    return client.post("/api/v1/auth/login", data={"username": correo, "password": clave})


def cab(respuesta):
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def crear_docente(client, admin, correo="doc@test.edu", **extra):
    r = client.post("/api/v1/usuarios", headers=admin, json={
        "correo": correo, "nombre_completo": "Docente Prueba", "rol": "docente", "password": CLAVE_DOCENTE, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id_usuario"]


def test_cambiar_password_invalida_tokens_anteriores_y_devuelve_uno_nuevo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        r = client.post("/api/v1/auth/cambiar-password", headers=admin,
                        json={"password_actual": CLAVE_ADMIN, "password_nueva": CLAVE_NUEVA})
        assert r.status_code == 200, r.text
        nuevo = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert client.get("/api/v1/usuarios", headers=nuevo).status_code == 200
        assert client.get("/api/v1/usuarios", headers=admin).status_code == 401  # token anterior
        assert login(client, "admin@test.edu", CLAVE_ADMIN).status_code == 401
        assert login(client, "admin@test.edu", CLAVE_NUEVA).status_code == 200


def test_cambiar_password_valida_clave_actual_y_politica(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        url = "/api/v1/auth/cambiar-password"
        assert client.post(url, headers=admin, json={"password_actual": "incorrecta-2026!", "password_nueva": CLAVE_NUEVA}).status_code == 400
        assert client.post(url, headers=admin, json={"password_actual": CLAVE_ADMIN, "password_nueva": "corta"}).status_code == 422
        assert client.post(url, headers=admin, json={"password_actual": CLAVE_ADMIN, "password_nueva": CLAVE_ADMIN}).status_code == 422
        assert client.post(url, json={"password_actual": CLAVE_ADMIN, "password_nueva": CLAVE_NUEVA}).status_code == 401


def test_restablecer_da_clave_temporal_obliga_a_cambiarla_y_cierra_sesiones(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        id_doc = crear_docente(client, admin)
        sesion_vieja = cab(login(client, "doc@test.edu", CLAVE_DOCENTE))
        r = client.post(f"/api/v1/usuarios/{id_doc}/restablecer-password", headers=admin)
        assert r.status_code == 200, r.text
        temporal = r.json()["password_temporal"]
        assert client.get("/api/v1/estudiantes", headers=sesion_vieja).status_code == 401
        assert login(client, "doc@test.edu", CLAVE_DOCENTE).status_code == 401
        entrada = login(client, "doc@test.edu", temporal)
        assert entrada.status_code == 200 and entrada.json()["debe_cambiar"] is True
        sesion = {"Authorization": f"Bearer {entrada.json()['access_token']}"}
        assert client.get("/api/v1/estudiantes", headers=sesion).status_code == 403  # primero debe cambiar la clave
        cambio = client.post("/api/v1/auth/cambiar-password", headers=sesion,
                             json={"password_actual": temporal, "password_nueva": CLAVE_NUEVA})
        assert cambio.status_code == 200 and cambio.json()["debe_cambiar"] is False
        listo = {"Authorization": f"Bearer {cambio.json()['access_token']}"}
        assert client.get("/api/v1/estudiantes", headers=listo).status_code == 200


def test_un_directivo_no_restablece_su_propia_clave_ni_un_docente_restablece(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        id_admin = client.get("/api/v1/usuarios", headers=admin).json()[0]["id_usuario"]
        assert client.post(f"/api/v1/usuarios/{id_admin}/restablecer-password", headers=admin).status_code == 400
        id_doc = crear_docente(client, admin)
        doc = cab(login(client, "doc@test.edu", CLAVE_DOCENTE))
        assert client.post(f"/api/v1/usuarios/{id_doc}/restablecer-password", headers=doc).status_code == 403
        assert client.post("/api/v1/usuarios/9999/restablecer-password", headers=admin).status_code == 404


def test_no_se_puede_quitar_ni_desactivar_al_ultimo_directivo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        id_admin = client.get("/api/v1/usuarios", headers=admin).json()[0]["id_usuario"]
        assert client.patch(f"/api/v1/usuarios/{id_admin}", headers=admin, json={"activo": 0}).status_code == 409
        assert client.patch(f"/api/v1/usuarios/{id_admin}", headers=admin, json={"rol": "docente"}).status_code == 409
        assert client.patch(f"/api/v1/usuarios/{id_admin}", headers=admin, json={"nombre_completo": "Nuevo Nombre"}).status_code == 200
        # con un segundo directivo activo ya se permite
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "dir2@test.edu", "nombre_completo": "Directivo Dos", "rol": "directivo", "password": CLAVE_DOCENTE})
        assert r.status_code == 201
        assert client.patch(f"/api/v1/usuarios/{id_admin}", headers=admin, json={"rol": "docente"}).status_code == 200


def test_desactivar_o_cambiar_el_rol_corta_las_sesiones_abiertas(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        id_doc = crear_docente(client, admin)
        doc = cab(login(client, "doc@test.edu", CLAVE_DOCENTE))
        assert client.get("/api/v1/estudiantes", headers=doc).status_code == 200
        assert client.patch(f"/api/v1/usuarios/{id_doc}", headers=admin, json={"activo": 0}).status_code == 200
        assert client.get("/api/v1/estudiantes", headers=doc).status_code == 401
        assert client.patch(f"/api/v1/usuarios/{id_doc}", headers=admin, json={"activo": 1}).status_code == 200
        assert client.get("/api/v1/estudiantes", headers=doc).status_code == 401  # el token viejo no revive
        assert login(client, "doc@test.edu", CLAVE_DOCENTE).status_code == 200


def test_crear_usuario_aplica_la_politica_de_contrasenas(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "x@test.edu", "nombre_completo": "Docente X", "rol": "docente", "password": "aaaaaaaaaaaaaaaa"})
        assert r.status_code == 422
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "y@test.edu", "nombre_completo": "Docente Y", "rol": "docente", "password": CLAVE_DOCENTE, "debe_cambiar": True})
        assert r.status_code == 201
        entrada = login(client, "y@test.edu", CLAVE_DOCENTE)
        assert entrada.json()["debe_cambiar"] is True


def test_el_hash_antiguo_se_actualiza_al_iniciar_sesion(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        crear_docente(client, admin)
        sal = b"0123456789abcdef"
        antiguo = f"{sal.hex()}:{hashlib.pbkdf2_hmac('sha256', CLAVE_DOCENTE.encode(), sal, 310_000).hex()}"
        con = sqlite3.connect(ruta)
        con.execute("UPDATE usuarios SET password_hash = ? WHERE correo = 'doc@test.edu'", (antiguo,))
        con.commit()
        con.close()
        assert login(client, "doc@test.edu", CLAVE_DOCENTE).status_code == 200
        con = sqlite3.connect(ruta)
        nuevo = con.execute("SELECT password_hash FROM usuarios WHERE correo = 'doc@test.edu'").fetchone()[0]
        con.close()
        assert nuevo.startswith("pbkdf2_sha256$") and seguridad.verificar_password(CLAVE_DOCENTE, nuevo)


def test_la_clave_de_env_solo_crea_al_primer_directivo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = cab(login(client, "admin@test.edu", CLAVE_ADMIN))
        monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "otro@test.edu")
        assert login(client, "otro@test.edu", CLAVE_ADMIN).status_code == 401
        assert client.get("/api/v1/usuarios", headers=admin).status_code == 200
