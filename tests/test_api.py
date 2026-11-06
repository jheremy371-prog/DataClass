from fastapi.testclient import TestClient

import api.database as database
import api.main as main


def autenticar_como_directivo(client, monkeypatch):
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", "admin@test.edu")
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", "Prueba-segura-2026!")
    response = client.post("/api/v1/auth/login", data={
        "username": "admin@test.edu",
        "password": "Prueba-segura-2026!",
    })
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})


def test_flujo_academico_basico(tmp_path, monkeypatch):
    test_db = tmp_path / "dataclass_test.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setenv("DATACLASS_JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    main.SECRET_KEY = "test-secret-that-is-long-enough-for-tests"

    with TestClient(main.app) as client:
        assert client.get("/api/v1/estudiantes").status_code == 401
        autenticar_como_directivo(client, monkeypatch)
        estudiante = {
            "id_estudiante": "TEST-001",
            "nombre_completo": "Estudiante de Prueba",
            "aula": "A-1",
        }
        respuesta = client.post("/api/v1/estudiantes", json=estudiante)
        assert respuesta.status_code == 201
        assert respuesta.json()["id_estudiante"] == "TEST-001"

        nota = {
            "id_estudiante": "TEST-001",
            "curso_modulo": "Matemática",
            "nota_obtenida": 16,
            "periodo_evaluacion": "Bimestre 1",
        }
        assert client.post("/api/v1/calificaciones", json=nota).status_code == 201
        assert len(client.get("/api/v1/estudiantes/TEST-001/calificaciones").json()) == 1

        asistencia = {
            "id_estudiante": "TEST-001",
            "fecha": "2026-10-16",
            "estado_asistencia": "presente",
        }
        assert client.post("/api/v1/asistencias", json=asistencia).status_code == 201
        assert client.post("/api/v1/asistencias", json=asistencia).status_code == 409

        nota_invalida = {**nota, "nota_obtenida": 25}
        assert client.post("/api/v1/calificaciones", json=nota_invalida).status_code == 422
        assert client.delete("/api/v1/estudiantes/TEST-001").status_code == 204
        assert client.get("/api/v1/estudiantes/TEST-001").status_code == 404


def test_alertas_e_intervenciones(tmp_path, monkeypatch):
    test_db = tmp_path / "dataclass_alertas_test.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setenv("DATACLASS_JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    main.SECRET_KEY = "test-secret-that-is-long-enough-for-tests"

    with TestClient(main.app) as client:
        autenticar_como_directivo(client, monkeypatch)
        creado = client.post("/api/v1/estudiantes", json={
            "id_estudiante": "TEST-ALERTA-01",
            "nombre_completo": "Estudiante con Seguimiento",
            "aula": "A-2",
        })
        assert creado.status_code == 201

        alerta = client.post("/api/v1/alertas", json={
            "id_estudiante": "TEST-ALERTA-01",
            "tipo_alerta": "bajo_rendimiento",
            "nivel_riesgo": "medio",
            "descripcion": "Descenso de notas en Matemática.",
            "version_modelo": "experimental-0.1",
            "probabilidad": 0.62,
        })
        assert alerta.status_code == 201
        id_alerta = alerta.json()["id_alerta"]

        intervencion = client.post("/api/v1/intervenciones", json={
            "id_estudiante": "TEST-ALERTA-01",
            "id_alerta": id_alerta,
            "tutor": "Tutor de prueba",
            "tipo_intervencion": "tutoria",
            "descripcion": "Revisar ejercicios y establecer un plan de estudio.",
            "fecha_intervencion": "2026-10-16",
            "proxima_revision": "2026-10-23",
        })
        assert intervencion.status_code == 201
        id_intervencion = intervencion.json()["id_intervencion"]

        actualizada = client.patch(f"/api/v1/alertas/{id_alerta}", json={"estado": "en_seguimiento"})
        assert actualizada.status_code == 200
        assert actualizada.json()["estado"] == "en_seguimiento"

        resultado = client.patch(f"/api/v1/intervenciones/{id_intervencion}", json={
            "resultado": "El estudiante completó los ejercicios asignados.",
            "proxima_revision": "2026-10-30",
        })
        assert resultado.status_code == 200
        assert resultado.json()["resultado"].startswith("El estudiante completó")

        assert len(client.get("/api/v1/alertas", params={"id_estudiante": "TEST-ALERTA-01"}).json()) == 1
        assert len(client.get("/api/v1/intervenciones", params={"id_alerta": id_alerta}).json()) == 1

        alerta_otro = client.post("/api/v1/alertas", json={
            "id_estudiante": "TEST-ALERTA-01",
            "tipo_alerta": "desercion",
            "nivel_riesgo": "alto",
            "descripcion": "Riesgo de abandono para prueba de validación.",
        })
        assert alerta_otro.status_code == 201
        respuesta_invalida = client.post("/api/v1/intervenciones", json={
            "id_estudiante": "TEST-ALERTA-01",
            "id_alerta": alerta_otro.json()["id_alerta"] + 999,
            "tutor": "Tutor de prueba",
            "tipo_intervencion": "llamada",
            "descripcion": "Intento con una alerta inexistente.",
            "fecha_intervencion": "2026-10-16",
        })
        assert respuesta_invalida.status_code == 404


def test_autenticacion_y_permisos_por_rol(tmp_path, monkeypatch):
    test_db = tmp_path / "dataclass_roles_test.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setenv("DATACLASS_JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    main.SECRET_KEY = "test-secret-that-is-long-enough-for-tests"

    with TestClient(main.app) as client:
        assert client.get("/api/v1/alertas").status_code == 401
        autenticar_como_directivo(client, monkeypatch)

        creado = client.post("/api/v1/usuarios", json={
            "correo": "profesor@test.edu",
            "nombre_completo": "Docente de prueba",
            "rol": "docente",
            "password": "Docente-seguro-2026!",
        })
        assert creado.status_code == 201, creado.text
        assert "password_hash" not in creado.json()

        login_docente = client.post("/api/v1/auth/login", data={
            "username": "profesor@test.edu",
            "password": "Docente-seguro-2026!",
        })
        assert login_docente.status_code == 200
        client.headers.update({"Authorization": f"Bearer {login_docente.json()['access_token']}"})
        assert client.get("/api/v1/estudiantes").status_code == 200
        no_autorizado = client.post("/api/v1/estudiantes", json={
            "id_estudiante": "NO-PERMITIDO",
            "nombre_completo": "No debe crearse",
        })
        assert no_autorizado.status_code == 403
        assert client.get("/api/v1/usuarios").status_code == 403
