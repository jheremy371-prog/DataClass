"""API del catálogo académico: /aulas, /grados, /grados/materias, aulas inexistentes, ID automático y /auth/sesion."""
from datetime import date

from fastapi.testclient import TestClient

import api.database as database
import api.main as main

SECRETO = "test-secret-that-is-long-enough-for-tests"
CLAVE_ADMIN = "Prueba-segura-2026!"
CLAVE_DOCENTE = "Docente-seguro-2026!"
GRADO = "1° SECUNDARIA"
AULA_A = "1° SECUNDARIA A"
AULA_B = "1° SECUNDARIA B"
ANIO = date.today().year


def preparar(tmp_path, monkeypatch):
    test_db = tmp_path / "catalogo_api.db"
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


def crear_aulas(client, admin, grado="1° Secundaria", secciones=("A", "B")):
    r = client.post("/api/v1/aulas", headers=admin, json={"grado": grado, "secciones": list(secciones)})
    assert r.status_code == 201, r.text
    return r.json()


def crear_docente(client, admin, aula=None, correo="docente.a@test.edu"):
    cuerpo = {"correo": correo, "nombre_completo": "Docente de prueba", "rol": "docente", "password": CLAVE_DOCENTE}
    if aula:
        cuerpo["aula"] = aula
    return client.post("/api/v1/usuarios", headers=admin, json=cuerpo)


# ------------------------------------------------------------------------------------------------ aulas y grados
def test_crear_aulas_por_grado_y_listarlas(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        assert crear_aulas(client, admin) == {"creadas": [AULA_A, AULA_B], "ya_existentes": []}
        # Repetir no duplica: lo que ya existe se informa aparte.
        assert crear_aulas(client, admin, secciones=("B", "C")) == {"creadas": ["1° SECUNDARIA C"], "ya_existentes": [AULA_B]}

        r = client.post("/api/v1/grados/materias", headers=admin, json={"grado": "1° Secundaria", "materia": "Matemática"})
        assert r.status_code == 201 and r.json() == {"grado": GRADO, "materia": "Matemática", "nueva": True}

        aulas = client.get("/api/v1/aulas", headers=admin).json()
        assert [a["nombre"] for a in aulas] == [AULA_A, AULA_B, "1° SECUNDARIA C"]
        assert all(a["materias"] == ["Matemática"] and a["estudiantes"] == 0 for a in aulas)  # todas las secciones heredan la malla

        grados = client.get("/api/v1/grados", headers=admin).json()
        assert grados == [{"grado": GRADO, "secciones": ["A", "B", "C"], "materias": ["Matemática"]}]


def test_las_materias_se_unifican_y_se_pueden_quitar(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        assert client.post("/api/v1/grados/materias", headers=admin, json={"grado": GRADO, "materia": "Matemática"}).json()["nueva"] is True
        # «matematica» es la misma materia que «Matemática»: no se crea otra.
        r = client.post("/api/v1/grados/materias", headers=admin, json={"grado": GRADO, "materia": "matematica"})
        assert r.status_code == 201 and r.json()["materia"] == "Matemática" and r.json()["nueva"] is False

        params = {"grado": GRADO, "materia": "Matemática"}
        assert client.delete("/api/v1/grados/materias", headers=admin, params=params).status_code == 204
        assert client.delete("/api/v1/grados/materias", headers=admin, params=params).status_code == 404
        assert client.get("/api/v1/grados", headers=admin).json() == []  # sin aulas ni materias, el grado desaparece


def test_datos_invalidos_del_catalogo_se_rechazan(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        assert client.post("/api/v1/aulas", headers=admin, json={"grado": GRADO, "secciones": []}).status_code == 422
        assert client.post("/api/v1/aulas", headers=admin, json={"grado": "=1+1", "secciones": ["A"]}).status_code == 422
        assert client.post("/api/v1/aulas", headers=admin, json={"grado": GRADO, "secciones": ["=A"]}).status_code == 422
        assert client.post("/api/v1/grados/materias", headers=admin, json={"grado": GRADO, "materia": "=HYPERLINK()"}).status_code == 422


def test_eliminar_aula_solo_si_esta_vacia(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        crear_aulas(client, admin)
        r = client.post("/api/v1/estudiantes", headers=admin, json={"nombre_completo": "Ana Pérez", "aula": AULA_A})
        assert r.status_code == 201, r.text

        assert client.delete("/api/v1/aulas", headers=admin, params={"nombre": AULA_A}).status_code == 409  # tiene estudiantes
        assert client.delete("/api/v1/aulas", headers=admin, params={"nombre": AULA_B}).status_code == 204
        assert client.delete("/api/v1/aulas", headers=admin, params={"nombre": AULA_B}).status_code == 404
        assert [a["nombre"] for a in client.get("/api/v1/aulas", headers=admin).json()] == [AULA_A]


def test_permisos_del_catalogo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        crear_aulas(client, admin)
        assert crear_docente(client, admin, aula=AULA_A).status_code == 201
        docente = login(client, "docente.a@test.edu", CLAVE_DOCENTE)

        # El docente ve solo su aula; todo lo demás del catálogo es de directivos.
        assert [a["nombre"] for a in client.get("/api/v1/aulas", headers=docente).json()] == [AULA_A]
        assert client.get("/api/v1/grados", headers=docente).status_code == 403
        assert client.post("/api/v1/aulas", headers=docente, json={"grado": GRADO, "secciones": ["Z"]}).status_code == 403
        assert client.delete("/api/v1/aulas", headers=docente, params={"nombre": AULA_B}).status_code == 403
        assert client.post("/api/v1/grados/materias", headers=docente, json={"grado": GRADO, "materia": "Arte"}).status_code == 403
        assert client.delete("/api/v1/grados/materias", headers=docente, params={"grado": GRADO, "materia": "Arte"}).status_code == 403
        # Sin sesión no se ve nada.
        assert client.get("/api/v1/aulas").status_code == 401
        assert client.get("/api/v1/grados").status_code == 401


def test_un_docente_sin_aula_no_ve_aulas(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        crear_aulas(client, admin)
        assert crear_docente(client, admin).status_code == 201
        assert client.get("/api/v1/aulas", headers=login(client, "docente.a@test.edu", CLAVE_DOCENTE)).json() == []


# ------------------------------------------------------------------------------------------------ aulas inexistentes
def test_un_estudiante_solo_puede_ir_a_un_aula_del_catalogo(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        # Sin catálogo, el aula sigue siendo texto libre (instituciones que aún no cargan sus aulas).
        assert client.post("/api/v1/estudiantes", headers=admin, json={"nombre_completo": "Libre Uno", "aula": "Aula libre"}).status_code == 201

        crear_aulas(client, admin)
        r = client.post("/api/v1/estudiantes", headers=admin, json={"nombre_completo": "Beto Ruiz", "aula": "9° INEXISTENTE A"})
        assert r.status_code == 422 and "no existe" in r.json()["detail"]
        ok = client.post("/api/v1/estudiantes", headers=admin, json={"nombre_completo": "Carla Soto", "aula": AULA_A})
        assert ok.status_code == 201, ok.text

        # Lo mismo al mover a un estudiante existente (PATCH).
        id_estudiante = ok.json()["id_estudiante"]
        r = client.patch(f"/api/v1/estudiantes/{id_estudiante}", headers=admin, json={"aula": "9° INEXISTENTE A"})
        assert r.status_code == 422
        assert client.get(f"/api/v1/estudiantes/{id_estudiante}", headers=admin).json()["aula"] == AULA_A  # no se movió
        r = client.patch(f"/api/v1/estudiantes/{id_estudiante}", headers=admin, json={"aula": AULA_B})
        assert r.status_code == 200 and r.json()["aula"] == AULA_B


def test_el_aula_del_docente_se_valida_contra_el_catalogo(tmp_path, monkeypatch):
    """N-04: un aula mal escrita dejaba al docente con cero estudiantes y sin aviso."""
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        # Sin catálogo se admite texto libre, como antes.
        assert crear_docente(client, admin, aula="A-302", correo="libre@test.edu").status_code == 201

        crear_aulas(client, admin)
        r = crear_docente(client, admin, aula="1° SECUNDARIA Z")
        assert r.status_code == 422 and "no existe" in r.json()["detail"]
        ok = crear_docente(client, admin, aula=AULA_A, correo="ok@test.edu")
        assert ok.status_code == 201, ok.text

        id_u = ok.json()["id_usuario"]
        assert client.patch(f"/api/v1/usuarios/{id_u}", headers=admin, json={"aula": "1° SECUNDARIA Z"}).status_code == 422
        r = client.patch(f"/api/v1/usuarios/{id_u}", headers=admin, json={"aula": AULA_B})
        assert r.status_code == 200 and r.json()["aula"] == AULA_B
        # Quitarle el aula sigue permitido.
        r = client.patch(f"/api/v1/usuarios/{id_u}", headers=admin, json={"aula": None})
        assert r.status_code == 200 and r.json()["aula"] is None


# ------------------------------------------------------------------------------------------------ ID automático
def test_id_automatico_por_api_y_sin_reutilizar_ids_borrados(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)

        def nuevo(nombre):
            r = client.post("/api/v1/estudiantes", headers=admin, json={"nombre_completo": nombre})
            assert r.status_code == 201, r.text
            return r.json()["id_estudiante"]

        assert nuevo("Ana Pérez") == f"{ANIO}-0001"
        assert nuevo("Beto Ruiz") == f"{ANIO}-0002"
        # N-05: borrar el último no libera su número para otra persona.
        assert client.delete(f"/api/v1/estudiantes/{ANIO}-0002", headers=admin).status_code == 204
        assert nuevo("Carla Soto") == f"{ANIO}-0003"
        # Un ID dado a mano se respeta y también adelanta el contador.
        r = client.post("/api/v1/estudiantes", headers=admin, json={"id_estudiante": f"{ANIO}-0010", "nombre_completo": "Dario Paz"})
        assert r.status_code == 201 and r.json()["id_estudiante"] == f"{ANIO}-0010"
        assert nuevo("Elena Cruz") == f"{ANIO}-0011"


def test_solo_directivos_crean_estudiantes(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        assert crear_docente(client, admin).status_code == 201
        docente = login(client, "docente.a@test.edu", CLAVE_DOCENTE)
        assert client.post("/api/v1/estudiantes", headers=docente, json={"nombre_completo": "Ana Pérez"}).status_code == 403


# ------------------------------------------------------------------------------------------------ /auth/sesion
def test_auth_sesion_devuelve_rol_y_rechaza_tokens_invalidos(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        r = client.get("/api/v1/auth/sesion", headers=admin)
        assert r.status_code == 200
        assert r.json()["rol"] == "directivo" and r.json()["debe_cambiar"] is False and r.json()["nombre_completo"]

        assert client.get("/api/v1/auth/sesion").status_code == 401
        assert client.get("/api/v1/auth/sesion", headers={"Authorization": "Bearer no.es.un.token"}).status_code == 401


def test_auth_sesion_avisa_si_la_cuenta_debe_cambiar_la_clave(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        admin = login(client, "admin@test.edu", CLAVE_ADMIN)
        r = client.post("/api/v1/usuarios", headers=admin, json={
            "correo": "temporal@test.edu", "nombre_completo": "Docente Temporal", "rol": "docente",
            "password": CLAVE_DOCENTE, "debe_cambiar": True})
        assert r.status_code == 201, r.text
        temporal = login(client, "temporal@test.edu", CLAVE_DOCENTE)
        assert client.get("/api/v1/auth/sesion", headers=temporal).json()["debe_cambiar"] is True
        # Con la clave pendiente solo puede cambiarla o cerrar sesión: el resto está bloqueado.
        assert client.get("/api/v1/aulas", headers=temporal).status_code == 403
        assert client.post("/api/v1/auth/cerrar-sesion", headers=temporal).status_code == 204
