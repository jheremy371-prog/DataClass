"""Corregir y eliminar notas y asistencias: permisos por aula, recálculo, bitácora y borrado en la nube."""
import sqlite3

from fastapi.testclient import TestClient

import api.database as database
import api.main as main
from api import sync

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"


def preparar(tmp_path, monkeypatch):
    ruta = tmp_path / "correcciones.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(main, "DB_PATH", ruta)
    monkeypatch.setattr(sync, "DB_PATH", ruta)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", SECRETO)
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)
    return ruta


def login(client, correo, clave):
    r = client.post("/api/v1/auth/login", data={"username": correo, "password": clave})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def escenario(client):
    admin = login(client, "admin@test.edu", CLAVE_ADMIN)
    for id_est, aula in (("EST-A", "A-1"), ("EST-B", "B-1")):
        assert client.post("/api/v1/estudiantes", headers=admin, json={
            "id_estudiante": id_est, "nombre_completo": f"Alumno {id_est}", "aula": aula}).status_code == 201
    r = client.post("/api/v1/usuarios", headers=admin, json={
        "correo": "docente.a@test.edu", "nombre_completo": "Docente A", "rol": "docente",
        "password": CLAVE_DOCENTE, "aula": "A-1"})
    assert r.status_code == 201, r.text
    docente = login(client, "docente.a@test.edu", CLAVE_DOCENTE)
    ids = {}
    for id_est in ("EST-A", "EST-B"):
        n = client.post("/api/v1/calificaciones", headers=admin, json={
            "id_estudiante": id_est, "curso_modulo": "Matemática", "nota_obtenida": 8, "periodo_evaluacion": "B1"})
        a = client.post("/api/v1/asistencias", headers=admin, json={
            "id_estudiante": id_est, "fecha": "2026-10-01", "estado_asistencia": "falta"})
        assert n.status_code == 201 and a.status_code == 201
        ids[id_est] = (n.json()["id_calificacion"], a.json()["id_asistencia"])
    return admin, docente, ids


def test_corregir_una_nota_la_reemplaza_y_no_se_suma(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente, ids = escenario(client)
        id_nota = ids["EST-A"][0]
        r = client.patch(f"/api/v1/calificaciones/{id_nota}", headers=docente, json={"nota_obtenida": 14.5})
        assert r.status_code == 200, r.text
        assert r.json()["nota_obtenida"] == 14.5 and r.json()["is_synced"] == 0
        notas = client.get("/api/v1/estudiantes/EST-A/calificaciones", headers=docente).json()
        assert [n["nota_obtenida"] for n in notas] == [14.5]  # una sola nota, no dos


def test_corregir_asistencia_y_cambiar_fecha(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente, ids = escenario(client)
        id_asist = ids["EST-A"][1]
        r = client.patch(f"/api/v1/asistencias/{id_asist}", headers=docente, json={"estado_asistencia": "justificada"})
        assert r.status_code == 200 and r.json()["estado_asistencia"] == "justificada"
        # otra asistencia en otra fecha; mover la primera a esa fecha da 409
        assert client.post("/api/v1/asistencias", headers=docente, json={
            "id_estudiante": "EST-A", "fecha": "2026-10-02", "estado_asistencia": "presente"}).status_code == 201
        assert client.patch(f"/api/v1/asistencias/{id_asist}", headers=docente, json={"fecha": "2026-10-02"}).status_code == 409
        assert client.patch(f"/api/v1/asistencias/{id_asist}", headers=docente, json={"fecha": "2026-10-03"}).status_code == 200


def test_validaciones_de_las_correcciones(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente, ids = escenario(client)
        n, a = ids["EST-A"]
        assert client.patch(f"/api/v1/calificaciones/{n}", headers=docente, json={}).status_code == 400
        assert client.patch(f"/api/v1/calificaciones/{n}", headers=docente, json={"nota_obtenida": None}).status_code == 400
        assert client.patch(f"/api/v1/calificaciones/{n}", headers=docente, json={"nota_obtenida": 25}).status_code == 422
        assert client.patch(f"/api/v1/calificaciones/{n}", headers=docente, json={"curso_modulo": "=1+1"}).status_code == 422
        assert client.patch(f"/api/v1/asistencias/{a}", headers=docente, json={"fecha": "2999-01-01"}).status_code == 422
        assert client.patch(f"/api/v1/asistencias/{a}", headers=docente, json={"estado_asistencia": "x"}).status_code == 422


def test_docente_no_toca_registros_de_otra_aula_y_el_404_es_igual_al_inexistente(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente, ids = escenario(client)
        n_b, a_b = ids["EST-B"]
        ajeno = client.patch(f"/api/v1/calificaciones/{n_b}", headers=docente, json={"nota_obtenida": 20})
        inexistente = client.patch("/api/v1/calificaciones/999999", headers=docente, json={"nota_obtenida": 20})
        assert ajeno.status_code == inexistente.status_code == 404
        assert ajeno.json() == inexistente.json()
        assert client.delete(f"/api/v1/calificaciones/{n_b}", headers=docente).status_code == 404
        assert client.patch(f"/api/v1/asistencias/{a_b}", headers=docente, json={"estado_asistencia": "presente"}).status_code == 404
        assert client.delete(f"/api/v1/asistencias/{a_b}", headers=docente).status_code == 404
        # nada cambió
        notas = client.get("/api/v1/estudiantes/EST-B/calificaciones", headers=admin).json()
        assert [x["nota_obtenida"] for x in notas] == [8]
        # sin token no se puede
        assert client.delete(f"/api/v1/calificaciones/{n_b}").status_code == 401


def test_eliminar_registra_en_bitacora_y_pide_borrado_en_la_nube(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente, ids = escenario(client)
        n, a = ids["EST-A"]
        assert client.patch(f"/api/v1/calificaciones/{n}", headers=docente, json={"nota_obtenida": 12}).status_code == 200
        assert client.delete(f"/api/v1/calificaciones/{n}", headers=docente).status_code == 204
        assert client.delete(f"/api/v1/asistencias/{a}", headers=docente).status_code == 204
        assert client.get("/api/v1/estudiantes/EST-A/calificaciones", headers=docente).json() == []
        assert client.get("/api/v1/estudiantes/EST-A/asistencias", headers=docente).json() == []
        # se puede volver a registrar la asistencia del mismo día (antes daba 409 sin salida)
        assert client.post("/api/v1/asistencias", headers=docente, json={
            "id_estudiante": "EST-A", "fecha": "2026-10-01", "estado_asistencia": "presente"}).status_code == 201

    with sqlite3.connect(ruta) as con:
        acciones = {f[0]: f for f in con.execute(
            "SELECT accion, id_estudiante, detalle FROM auditoria WHERE accion LIKE 'correccion_%' OR accion LIKE 'eliminacion_%'")}
        assert acciones["correccion_nota"][1] == "EST-A" and "nota_obtenida" in acciones["correccion_nota"][2]
        assert acciones["eliminacion_nota"][1] == "EST-A"
        assert acciones["eliminacion_asistencia"][1] == "EST-A"
        pendientes = set(con.execute("SELECT tabla, id_estudiante, id_documento FROM eliminaciones_nube_hijas"))
        assert pendientes == {("calificaciones", "EST-A", str(n)), ("asistencias", "EST-A", "2026-10-01")}


def test_cambiar_la_fecha_pide_borrar_el_documento_de_la_fecha_anterior(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin, docente, ids = escenario(client)
        a = ids["EST-A"][1]
        assert client.patch(f"/api/v1/asistencias/{a}", headers=docente, json={"fecha": "2026-10-05"}).status_code == 200
    with sqlite3.connect(ruta) as con:
        assert set(con.execute("SELECT tabla, id_documento FROM eliminaciones_nube_hijas")) == {("asistencias", "2026-10-01")}


class _Doc:
    def __init__(self, cliente, ruta):
        self.cliente, self.ruta = cliente, ruta

    def collection(self, nombre):
        return _Col(self.cliente, self.ruta + (nombre,))

    def delete(self):
        if self.cliente.sin_red:
            raise ConnectionError("sin red")
        self.cliente.almacen.discard(self.ruta)


class _Col:
    def __init__(self, cliente, ruta):
        self.cliente, self.ruta = cliente, ruta

    def document(self, id_documento):
        return _Doc(self.cliente, self.ruta + (id_documento,))


class _Cliente:
    def __init__(self, sin_red=False):
        self.almacen, self.sin_red = set(), sin_red

    def collection(self, nombre):
        return _Col(self, (nombre,))


def test_la_sincronizacion_borra_los_documentos_hijos_y_reintenta_sin_red(tmp_path, monkeypatch):
    ruta = preparar(tmp_path, monkeypatch)
    monkeypatch.delenv("FIREBASE_COLLECTION", raising=False)
    database.inicializar_esquema()
    with sqlite3.connect(ruta) as con:
        con.execute("INSERT INTO eliminaciones_nube_hijas (tabla, id_estudiante, id_documento) VALUES ('calificaciones', 'E1', '7')")
        con.execute("INSERT INTO eliminaciones_nube_hijas (tabla, id_estudiante, id_documento) VALUES ('asistencias', 'E1', '2026-10-01')")
    cliente = _Cliente(sin_red=True)
    p = sync.seudonimo("E1")  # en la nube los documentos llevan el seudónimo, no el ID real
    cliente.almacen |= {("estudiantes", p, "calificaciones", "7"), ("estudiantes", p, "asistencias", "2026-10-01"),
                        ("estudiantes", p, "calificaciones", "8")}
    assert sync.sincronizar_eliminaciones_hijas(cliente) == {"enviados": 0, "errores": 2}  # queda pendiente
    cliente.sin_red = False
    assert sync.sincronizar_eliminaciones_hijas(cliente) == {"enviados": 2, "errores": 0}
    assert cliente.almacen == {("estudiantes", p, "calificaciones", "8")}  # no toca otras notas
    assert sync.sincronizar_eliminaciones_hijas(cliente) == {"enviados": 0, "errores": 0}
    assert sync.sincronizar_eliminaciones_hijas(None) == {"enviados": 0, "errores": 0}