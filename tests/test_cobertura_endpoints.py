"""P0 del informe de auditoría: ningún endpoint de /api/ queda sin autenticación y los docentes
no pueden ejecutar acciones reservadas a directivos.

Recorre TODAS las rutas registradas, de modo que un endpoint nuevo sin protección hace fallar la prueba.
"""
import re

import pytest
from fastapi.testclient import TestClient

import api.main as main
from tests.test_acceso_aulas import montar_escenario, preparar

# Únicas rutas que pueden responder sin sesión. /estado es un chequeo de salud público: expone la versión del
# modelo y si es sintético; si prefieres no revelarlo, protégelo y quítalo de esta lista.
PUBLICAS = {("POST", "/api/v1/auth/login"), ("GET", "/api/v1/estado")}

# Rutas que un docente SÍ puede usar (con o sin datos propios). Todo lo demás es solo de directivos.
# Si agregas un endpoint para docentes, añádelo aquí a propósito.
PERMITIDAS_A_DOCENTES = {
    ("GET", "/api/v1/auth/sesion"), ("POST", "/api/v1/auth/cerrar-sesion"), ("POST", "/api/v1/auth/cambiar-password"),
    ("GET", "/api/v1/estado"), ("GET", "/api/v1/aulas"), ("GET", "/api/v1/grados"),
    ("GET", "/api/v1/estudiantes"), ("GET", "/api/v1/estudiantes/{id_estudiante}"),
    ("GET", "/api/v1/estudiantes/{id_estudiante}/calificaciones"), ("GET", "/api/v1/estudiantes/{id_estudiante}/asistencias"),
    ("POST", "/api/v1/calificaciones"), ("POST", "/api/v1/asistencias"),
    ("PATCH", "/api/v1/calificaciones/{id_calificacion}"), ("DELETE", "/api/v1/calificaciones/{id_calificacion}"),
    ("PATCH", "/api/v1/asistencias/{id_asistencia}"), ("DELETE", "/api/v1/asistencias/{id_asistencia}"),
    ("POST", "/api/v1/alertas"), ("GET", "/api/v1/alertas"), ("PATCH", "/api/v1/alertas/{id_alerta}"),
    ("POST", "/api/v1/intervenciones"), ("GET", "/api/v1/intervenciones"), ("PATCH", "/api/v1/intervenciones/{id_intervencion}"),
    ("POST", "/api/v1/estudiantes/{id_estudiante}/evaluar-riesgo"), ("POST", "/api/v1/personas/validar-dni"),
    ("POST", "/api/v1/analitica/predecir"),
    # Los docentes importan notas y asistencias de su aula; el permiso fino se valida dentro del endpoint.
    ("POST", "/api/v1/importaciones/{tipo}"),
}


def rutas_api():
    for ruta in main.app.routes:
        camino = getattr(ruta, "path", "")
        if camino.startswith("/api/"):
            for metodo in sorted(ruta.methods - {"HEAD", "OPTIONS"}):
                yield metodo, camino


def url_de_ejemplo(camino: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "EST-A" if m.group(1) == "id_estudiante" else "1" if m.group(1).startswith("id_") else "x", camino)


def test_hay_rutas_que_recorrer():
    assert len(list(rutas_api())) >= 40


def test_todo_endpoint_exige_sesion(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        for metodo, camino in rutas_api():
            if (metodo, camino) in PUBLICAS:
                continue
            r = client.request(metodo, url_de_ejemplo(camino))
            assert r.status_code == 401, f"{metodo} {camino} respondió {r.status_code} sin sesión"


def test_docente_no_ejecuta_acciones_de_directivo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        esc = montar_escenario(client)
        d = esc["docente_a"]
        for metodo, camino in rutas_api():
            if (metodo, camino) in PUBLICAS or (metodo, camino) in PERMITIDAS_A_DOCENTES:
                continue
            r = client.request(metodo, url_de_ejemplo(camino), headers=d, json={})
            assert r.status_code == 403, f"{metodo} {camino} respondió {r.status_code} a un docente (esperado 403)"


def test_importar_estudiantes_o_aulas_esta_vedado_a_docentes(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        d = montar_escenario(client)["docente_a"]
        for tipo in ("estudiantes", "aulas"):
            r = client.post(f"/api/v1/importaciones/{tipo}", headers=d, files={"archivo": ("x.csv", b"a,b\n1,2\n")})
            assert r.status_code == 403, f"importaciones/{tipo} respondió {r.status_code} a un docente"
