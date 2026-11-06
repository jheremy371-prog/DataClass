"""H-02: la bitácora registra el estudiante afectado en altas y cambios, y los valores antes y después."""
import sqlite3

from fastapi.testclient import TestClient

import api.database as database
import api.main as main
from api.limitador import LimitadorIntentos

CLAVE_ADMIN = "Prueba-segura-2026!"


def preparar(tmp_path, monkeypatch):
    ruta = tmp_path / "bitacora.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(main, "DB_PATH", ruta)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", "test-secret-that-is-long-enough-for-tests")
    monkeypatch.setattr(main, "limitador_correo", LimitadorIntentos(max_intentos=50))
    monkeypatch.setattr(main, "limitador_ip", LimitadorIntentos(max_intentos=50))
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)
    return ruta


def filas(ruta, metodo, ruta_http):
    with sqlite3.connect(ruta) as con:
        return con.execute(
            "SELECT id_estudiante, detalle FROM auditoria WHERE metodo = ? AND ruta = ? ORDER BY id_auditoria",
            (metodo, ruta_http),
        ).fetchall()


def test_cada_alta_y_cambio_deja_al_estudiante_en_la_bitacora(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        r = client.post("/api/v1/auth/login", data={"username": "admin@test.edu", "password": CLAVE_ADMIN})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert client.post("/api/v1/estudiantes", headers=h, json={"id_estudiante": "EST-H2", "nombre_completo": "Alumno Prueba", "aula": "A-1"}).status_code == 201
        nota = client.post("/api/v1/calificaciones", headers=h, json={"id_estudiante": "EST-H2", "curso_modulo": "Matemática", "nota_obtenida": 11, "periodo_evaluacion": "B1"})
        assert nota.status_code == 201, nota.text
        asist = client.post("/api/v1/asistencias", headers=h, json={"id_estudiante": "EST-H2", "fecha": "2026-10-01", "estado_asistencia": "falta"})
        assert asist.status_code == 201, asist.text
        alerta = client.post("/api/v1/alertas", headers=h, json={"id_estudiante": "EST-H2", "tipo_alerta": "desercion", "nivel_riesgo": "alto", "descripcion": "Faltas seguidas", "version_modelo": "manual"})
        assert alerta.status_code == 201, alerta.text
        id_alerta = alerta.json()["id_alerta"]
        inter = client.post("/api/v1/intervenciones", headers=h, json={"id_estudiante": "EST-H2", "id_alerta": id_alerta, "tutor": "Tutor Prueba", "tipo_intervencion": "Tutoría individual", "descripcion": "Conversación con el alumno", "fecha_intervencion": "2026-10-02"})
        assert inter.status_code == 201, inter.text
        assert client.patch(f"/api/v1/alertas/{id_alerta}", headers=h, json={"estado": "en_seguimiento"}).status_code == 200
        assert client.patch(f"/api/v1/intervenciones/{inter.json()['id_intervencion']}", headers=h, json={"resultado": "Mejoró la asistencia"}).status_code == 200
        # corrección de nota: 11 -> 14
        assert client.patch(f"/api/v1/calificaciones/{nota.json()['id_calificacion']}", headers=h, json={"nota_obtenida": 14}).status_code == 200
        assert client.get("/api/v1/estudiantes", headers=h).status_code == 200

    for metodo, url in (("POST", "/api/v1/calificaciones"), ("POST", "/api/v1/asistencias"), ("POST", "/api/v1/alertas"), ("POST", "/api/v1/intervenciones")):
        assert [f[0] for f in filas(ruta, metodo, url)] == ["EST-H2"], url
    patch_alerta = filas(ruta, "PATCH", f"/api/v1/alertas/{id_alerta}")
    assert patch_alerta[0][0] == "EST-H2" and "pendiente->en_seguimiento" in patch_alerta[0][1]
    assert filas(ruta, "PATCH", f"/api/v1/intervenciones/{inter.json()['id_intervencion']}")[0][0] == "EST-H2"
    cambio = filas(ruta, "PATCH", f"/api/v1/calificaciones/{nota.json()['id_calificacion']}")
    assert cambio[0][0] == "EST-H2" and "nota_obtenida: 11" in cambio[0][1] and "->14" in cambio[0][1]
    listado = filas(ruta, "GET", "/api/v1/estudiantes")
    assert "EST-H2" in listado[0][1]


def test_los_cambios_de_cuenta_dicen_a_quien_afectaron_y_que_cambio(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        r = client.post("/api/v1/auth/login", data={"username": "admin@test.edu", "password": CLAVE_ADMIN})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        u = client.post("/api/v1/usuarios", headers=h, json={"correo": "profe@test.edu", "nombre_completo": "Profe Uno", "rol": "docente", "password": "Docente-seguro-2026!", "aula": "A-1"})
        id_u = u.json()["id_usuario"]
        assert client.patch(f"/api/v1/usuarios/{id_u}", headers=h, json={"aula": "B-2"}).status_code == 200
        assert client.post(f"/api/v1/usuarios/{id_u}/restablecer-password", headers=h).status_code == 200
    detalle = filas(ruta, "PATCH", f"/api/v1/usuarios/{id_u}")[0][1]
    assert f"usuario={id_u}" in detalle and "aula: A-1->B-2" in detalle
    assert "restablecimiento" in filas(ruta, "POST", f"/api/v1/usuarios/{id_u}/restablecer-password")[0][1]
