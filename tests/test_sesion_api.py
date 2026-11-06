"""Cierre de sesión con revocación real (N-01), login sin texto escrito en la bitácora (M-02), /auth/sesion fuera de la
bitácora (N-02), PATCH de estudiantes solo para directivos (N-03), alertas manuales y tutor fijados por el servidor (M-01)."""
import sqlite3

from fastapi.testclient import TestClient

import api.database as database
import api.main as main
from api.limitador import LimitadorIntentos

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"


def preparar(tmp_path, monkeypatch):
    test_db = tmp_path / "sesion_api.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)
    monkeypatch.setattr(main, "limitador_correo", LimitadorIntentos(max_intentos=5))  # sin fallos arrastrados entre pruebas
    monkeypatch.setattr(main, "limitador_ip", LimitadorIntentos(max_intentos=30))
    return test_db


def login(client, correo, clave):
    r = client.post("/api/v1/auth/login", data={"username": correo, "password": clave})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def filas(db, consulta, parametros=()):
    con = sqlite3.connect(db)
    try:
        return con.execute(consulta, parametros).fetchall()
    finally:
        con.close()


def montar(client):
    """Admin, un estudiante en A-1 y un docente de A-1."""
    admin = login(client, "admin@test.edu", CLAVE_ADMIN)
    r = client.post("/api/v1/estudiantes", headers=admin, json={"id_estudiante": "EST-A", "nombre_completo": "Alumno A", "aula": "A-1"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/usuarios", headers=admin, json={
        "correo": "docente.a@test.edu", "nombre_completo": "Docente Ana", "rol": "docente", "aula": "A-1", "password": CLAVE_DOCENTE})
    assert r.status_code == 201, r.text
    return admin, login(client, "docente.a@test.edu", CLAVE_DOCENTE)


# ------------------------------------------------------------------------------------------------ N-01
def test_cerrar_sesion_invalida_el_token_en_el_servidor(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        assert client.get("/api/v1/auth/sesion", headers=docente).status_code == 200
        assert client.get("/api/v1/estudiantes", headers=docente).status_code == 200

        assert client.post("/api/v1/auth/cerrar-sesion", headers=docente).status_code == 204

        # El mismo token, copiado antes de cerrar sesión, ya no sirve para nada.
        assert client.get("/api/v1/auth/sesion", headers=docente).status_code == 401
        assert client.get("/api/v1/estudiantes", headers=docente).status_code == 401
        # Cerrar dos veces no abre nada: el segundo intento ya es un token inválido.
        assert client.post("/api/v1/auth/cerrar-sesion", headers=docente).status_code == 401


def test_cerrar_sesion_solo_afecta_a_esa_sesion(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        otro_dispositivo = login(client, "docente.a@test.edu", CLAVE_DOCENTE)
        assert otro_dispositivo != docente  # cada inicio de sesión emite un token distinto (jti)

        assert client.post("/api/v1/auth/cerrar-sesion", headers=docente).status_code == 204
        assert client.get("/api/v1/estudiantes", headers=docente).status_code == 401
        assert client.get("/api/v1/estudiantes", headers=otro_dispositivo).status_code == 200
        assert client.get("/api/v1/estudiantes", headers=admin).status_code == 200


def test_cerrar_sesion_requiere_token_y_queda_en_la_bitacora(tmp_path, monkeypatch):
    db = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        assert client.post("/api/v1/auth/cerrar-sesion").status_code == 401
        assert client.post("/api/v1/auth/cerrar-sesion", headers=docente).status_code == 204
    registro = filas(db, "SELECT accion, estado_http, detalle FROM auditoria WHERE ruta = '/api/v1/auth/cerrar-sesion' AND estado_http = 204")
    assert registro == [("escritura", 204, "cierre de sesión")]
    assert len(filas(db, "SELECT jti FROM tokens_revocados")) == 1


def test_los_tokens_revocados_vencidos_se_limpian(tmp_path, monkeypatch):
    db = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        con = sqlite3.connect(db)
        con.execute("INSERT INTO tokens_revocados (jti, id_usuario, expira_utc) VALUES ('viejo', 1, '2000-01-01 00:00:00')")
        con.commit()
        con.close()
        assert client.post("/api/v1/auth/cerrar-sesion", headers=docente).status_code == 204
    jtis = [f[0] for f in filas(db, "SELECT jti FROM tokens_revocados")]
    assert "viejo" not in jtis and len(jtis) == 1


# ------------------------------------------------------------------------------------------------ M-02 y N-02
def test_login_fallido_no_guarda_el_texto_escrito(tmp_path, monkeypatch):
    db = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        montar(client)
        # Alguien teclea su contraseña en el campo de usuario.
        r = client.post("/api/v1/auth/login", data={"username": "Mi-Clave-Secreta-2026!", "password": "x"})
        assert r.status_code == 401
        r = client.post("/api/v1/auth/login", data={"username": "docente.a@test.edu", "password": "incorrecta"})
        assert r.status_code == 401
    fallidos = filas(db, "SELECT detalle FROM auditoria WHERE accion = 'login_fallido'")
    assert len(fallidos) == 2
    assert all(detalle is None for (detalle,) in fallidos)
    assert filas(db, "SELECT 1 FROM auditoria WHERE detalle LIKE '%Secreta%'") == []


def test_la_bloqueada_tampoco_guarda_el_texto_escrito(tmp_path, monkeypatch):
    db = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        montar(client)
        for _ in range(5):
            client.post("/api/v1/auth/login", data={"username": "docente.a@test.edu", "password": "incorrecta"})
        r = client.post("/api/v1/auth/login", data={"username": "docente.a@test.edu", "password": "incorrecta"})
        assert r.status_code == 429
    assert filas(db, "SELECT detalle FROM auditoria WHERE accion = 'login_bloqueado'") == [(None,)]


def test_auth_sesion_no_llena_la_bitacora(tmp_path, monkeypatch):
    db = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        for _ in range(3):
            assert client.get("/api/v1/auth/sesion", headers=docente).status_code == 200
    assert filas(db, "SELECT 1 FROM auditoria WHERE ruta = '/api/v1/auth/sesion'") == []


# ------------------------------------------------------------------------------------------------ N-03
def test_solo_directivos_modifican_estudiantes(tmp_path, monkeypatch):
    db = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        # Un docente no puede ni cambiar el aula de su propio estudiante ni el nombre.
        assert client.patch("/api/v1/estudiantes/EST-A", headers=docente, json={"aula": "B-1"}).status_code == 403
        assert client.patch("/api/v1/estudiantes/EST-A", headers=docente, json={"nombre_completo": "Otro Nombre"}).status_code == 403
        assert filas(db, "SELECT aula, nombre_completo FROM estudiantes WHERE id_estudiante = 'EST-A'") == [("A-1", "Alumno A")]

        r = client.patch("/api/v1/estudiantes/EST-A", headers=admin, json={"aula": "B-1"})
        assert r.status_code == 200 and r.json()["aula"] == "B-1"
        # Y el cambio de aula queda en la bitácora con el antes y el después.
    detalle = filas(db, "SELECT detalle FROM auditoria WHERE metodo = 'PATCH' AND ruta = '/api/v1/estudiantes/EST-A' AND estado_http = 200")[0][0]
    assert "aula: A-1->B-1" in detalle


def test_cambiar_solo_el_telefono_se_audita_sin_el_numero(tmp_path, monkeypatch):
    db = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, _ = montar(client)
        r = client.patch("/api/v1/estudiantes/EST-A", headers=admin, json={"telefono_apoderado": "987654321"})
        assert r.status_code == 200, r.text
    detalle = filas(db, "SELECT detalle FROM auditoria WHERE metodo = 'PATCH' AND ruta = '/api/v1/estudiantes/EST-A'")[0][0]
    assert detalle == "telefono_apoderado actualizado"
    assert "987654321" not in detalle


# ------------------------------------------------------------------------------------------------ M-01
def test_alerta_manual_no_puede_hacerse_pasar_por_alerta_del_modelo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        r = client.post("/api/v1/alertas", headers=docente, json={
            "id_estudiante": "EST-A", "tipo_alerta": "desercion", "nivel_riesgo": "alto",
            "descripcion": "Faltas seguidas esta semana", "version_modelo": "rf-20261023", "probabilidad": 0.99,
        })
        assert r.status_code == 201, r.text
        assert r.json()["version_modelo"] == "manual"
        assert r.json()["probabilidad"] is None


def test_el_tutor_es_la_cuenta_que_registra_la_intervencion(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente = montar(client)
        base = {"id_estudiante": "EST-A", "tipo_intervencion": "Tutoría", "descripcion": "Conversación con el alumno", "fecha_intervencion": "2026-10-02"}
        r = client.post("/api/v1/intervenciones", headers=docente, json={**base, "tutor": "Director General"})  # intento de suplantar
        assert r.status_code == 201, r.text
        assert r.json()["tutor"] == "Docente Ana"
        r = client.post("/api/v1/intervenciones", headers=docente, json=base)  # el campo ya no es necesario
        assert r.status_code == 201 and r.json()["tutor"] == "Docente Ana"
