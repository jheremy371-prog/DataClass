"""Verificación de DNI con RENIEC (Scrall): servicio y endpoint, con la red simulada."""
import requests
from fastapi.testclient import TestClient

import api.database as database
import api.main as main
from api import reniec
from api.limitador import LimitadorIntentos

CLAVE_ADMIN = "Prueba-segura-2026!"


class Resp:
    def __init__(self, status=200, cuerpo=None):
        self.status_code, self._cuerpo = status, cuerpo
        self.ok = 200 <= status < 300

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin json")
        return self._cuerpo


class Sesion:
    def __init__(self, respuesta=None, error=None):
        self.respuesta, self.error, self.llamadas = respuesta, error, []

    def post(self, url, **kw):
        self.llamadas.append((url, kw))
        if self.error:
            raise self.error
        return self.respuesta


ENCONTRADO = {"message": "found data", "result": {
    "D_NUDNI": "46027897", "D_PRENOMBRES": "MARIA", "D_APEPATERNO": "GARCIA",
    "D_APEMATERNO": "LOPEZ", "D_FENACIMIENTO": "1990-05-15"}}


def preparar_servicio(monkeypatch):
    monkeypatch.setenv("SCRALL_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(reniec, "limite_global", reniec.LimiteConsultas(max_consultas=100))


def test_encontrado_devuelve_datos_y_manda_la_clave(monkeypatch):
    preparar_servicio(monkeypatch)
    s = Sesion(Resp(200, ENCONTRADO))
    r = reniec.consultar_dni("46027897", sesion=s)
    assert r.estado == "ok" and r.datos["nombres"] == "MARIA" and r.datos["apellido_paterno"] == "GARCIA"
    assert s.llamadas[0][1]["headers"]["Authorization"] == "Basic clave-de-prueba"
    assert s.llamadas[0][1]["json"] == {"dni": "46027897"}


def test_formato_invalido_no_llama_a_la_red(monkeypatch):
    preparar_servicio(monkeypatch)
    s = Sesion(Resp(200, ENCONTRADO))
    for malo in ("1234567", "123456789", "1234567a", "", None, 12345678):
        assert reniec.consultar_dni(malo, sesion=s).estado == "formato"
    assert s.llamadas == []


def test_conserva_ceros_a_la_izquierda(monkeypatch):
    preparar_servicio(monkeypatch)
    s = Sesion(Resp(200, ENCONTRADO))
    reniec.consultar_dni("04567890", sesion=s)
    assert s.llamadas[0][1]["json"]["dni"] == "04567890"


def test_sin_clave_configurada(monkeypatch):
    monkeypatch.delenv("SCRALL_API_KEY", raising=False)
    assert reniec.consultar_dni("46027897", sesion=Sesion(Resp())).estado == "no_configurado"


def test_estados_http_y_mensajes(monkeypatch):
    preparar_servicio(monkeypatch)
    casos = [
        (Resp(200, {"message": "not found data"}), "no_existe"),
        (Resp(401, {}), "clave_invalida"),
        (Resp(422, {}), "formato"),
        (Resp(500, {}), "error"),
        (Resp(200, {"message": "otra cosa"}), "error"),
        (Resp(200, None), "error"),
    ]
    for respuesta, esperado in casos:
        assert reniec.consultar_dni("46027897", sesion=Sesion(respuesta)).estado == esperado
    r = reniec.consultar_dni("46027897", sesion=Sesion(Resp(429, {"message": "rate limit exceeded, try again in 5 seconds"})))
    assert r.estado == "limite" and r.reintentar_en == 5


def test_timeout_y_error_de_red(monkeypatch):
    preparar_servicio(monkeypatch)
    assert reniec.consultar_dni("46027897", sesion=Sesion(error=requests.Timeout())).estado == "inalcanzable"
    assert reniec.consultar_dni("46027897", sesion=Sesion(error=requests.ConnectionError())).estado == "inalcanzable"


def test_limite_propio_de_2_cada_10_segundos(monkeypatch):
    monkeypatch.setenv("SCRALL_API_KEY", "x")
    t = [0.0]
    monkeypatch.setattr(reniec, "limite_global", reniec.LimiteConsultas(2, 10, reloj=lambda: t[0]))
    s = Sesion(Resp(200, ENCONTRADO))
    assert reniec.consultar_dni("46027897", sesion=s).estado == "ok"
    assert reniec.consultar_dni("46027897", sesion=s).estado == "ok"
    tercero = reniec.consultar_dni("46027897", sesion=s)
    assert tercero.estado == "limite" and tercero.reintentar_en >= 1 and len(s.llamadas) == 2
    t[0] = 10.5
    assert reniec.consultar_dni("46027897", sesion=s).estado == "ok"


# --- Endpoint ----------------------------------------------------------------------------------------
def preparar_api(tmp_path, monkeypatch):
    ruta = tmp_path / "reniec.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(main, "DB_PATH", ruta)
    monkeypatch.setattr(main, "motor_predictivo", None)
    monkeypatch.setattr(main, "SECRET_KEY", "test-secret-that-is-long-enough-for-tests")
    monkeypatch.setattr(main, "limitador_correo", LimitadorIntentos(max_intentos=50))
    monkeypatch.setattr(main, "limitador_ip", LimitadorIntentos(max_intentos=50))
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE_ADMIN)
    preparar_servicio(monkeypatch)
    return ruta


def test_endpoint_exige_sesion_y_rol_directivo(tmp_path, monkeypatch):
    preparar_api(tmp_path, monkeypatch)
    with TestClient(main.app) as c:
        assert c.post("/api/v1/personas/validar-dni", json={"dni": "46027897"}).status_code == 401
        h = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", data={"username": "admin@test.edu", "password": CLAVE_ADMIN}).json()["access_token"]}
        creado = c.post("/api/v1/usuarios", headers=h, json={"correo": "doc@test.edu", "nombre_completo": "Docente Uno", "rol": "docente", "aula": "A-1", "password": "Otra-clave-segura-2026!"})
        assert creado.status_code == 201, creado.text
        r = c.post("/api/v1/auth/login", data={"username": "doc@test.edu", "password": "Otra-clave-segura-2026!"})
        hd = {"Authorization": "Bearer " + r.json()["access_token"]}
        assert c.post("/api/v1/personas/validar-dni", headers=hd, json={"dni": "46027897"}).status_code == 403


def test_endpoint_ok_y_bitacora_sin_el_numero(tmp_path, monkeypatch):
    import sqlite3
    ruta = preparar_api(tmp_path, monkeypatch)
    monkeypatch.setattr(reniec.requests, "post", lambda *a, **k: Resp(200, ENCONTRADO))
    with TestClient(main.app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", data={"username": "admin@test.edu", "password": CLAVE_ADMIN}).json()["access_token"]}
        r = c.post("/api/v1/personas/validar-dni", headers=h, json={"dni": "46027897"})
        assert r.status_code == 200 and r.json()["datos"]["nombres"] == "MARIA"
        malo = c.post("/api/v1/personas/validar-dni", headers=h, json={"dni": "12ab"})
        assert malo.status_code == 422
    with sqlite3.connect(ruta) as con:
        textos = " ".join(str(f) for f in con.execute("SELECT detalle, ruta FROM auditoria"))
    assert "validar-dni" in textos and "46027897" not in textos


def test_endpoint_traduce_errores(tmp_path, monkeypatch):
    preparar_api(tmp_path, monkeypatch)
    with TestClient(main.app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", data={"username": "admin@test.edu", "password": CLAVE_ADMIN}).json()["access_token"]}
        for respuesta, codigo in ((Resp(200, {"message": "not found data"}), 404), (Resp(401, {}), 502), (Resp(500, {}), 502)):
            monkeypatch.setattr(reniec.requests, "post", lambda *a, r=respuesta, **k: r)
            assert c.post("/api/v1/personas/validar-dni", headers=h, json={"dni": "46027897"}).status_code == codigo
        monkeypatch.setattr(reniec.requests, "post", lambda *a, **k: Resp(429, {"message": "try again in 7 seconds"}))
        r = c.post("/api/v1/personas/validar-dni", headers=h, json={"dni": "46027897"})
        assert r.status_code == 429 and r.headers["retry-after"] == "7"
        monkeypatch.delenv("SCRALL_API_KEY")
        assert c.post("/api/v1/personas/validar-dni", headers=h, json={"dni": "46027897"}).status_code == 503
