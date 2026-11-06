"""El endpoint de login bloquea tras demasiados intentos fallidos (429) sin romper el inicio de sesión normal."""
from fastapi.testclient import TestClient

import api.database as database
import api.main as main
from api.limitador import LimitadorIntentos

CORREO = "admin@test.edu"
CLAVE = "Prueba-segura-2026!"


def preparar(tmp_path, monkeypatch, max_correo=3, max_ip=30):
    ruta = tmp_path / "login_limite.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    monkeypatch.setattr(main, "DB_PATH", ruta)
    monkeypatch.setenv("DATACLASS_JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    monkeypatch.setenv("DATACLASS_ADMIN_EMAIL", CORREO)
    monkeypatch.setenv("DATACLASS_ADMIN_PASSWORD", CLAVE)
    main.SECRET_KEY = "test-secret-that-is-long-enough-for-tests"
    # Limitadores nuevos por prueba: así no se arrastra estado entre pruebas.
    monkeypatch.setattr(main, "limitador_correo", LimitadorIntentos(max_intentos=max_correo))
    monkeypatch.setattr(main, "limitador_ip", LimitadorIntentos(max_intentos=max_ip))


def login(client, correo=CORREO, clave=CLAVE):
    return client.post("/api/v1/auth/login", data={"username": correo, "password": clave})


def test_tras_los_intentos_permitidos_responde_429_con_retry_after(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=3)
    with TestClient(main.app) as client:
        for _ in range(3):
            assert login(client, clave="incorrecta-1234").status_code == 401
        bloqueado = login(client, clave="incorrecta-1234")
        assert bloqueado.status_code == 429
        assert int(bloqueado.headers["Retry-After"]) > 0
        assert "Demasiados intentos" in bloqueado.json()["detail"]


def test_con_la_cuenta_bloqueada_ni_la_clave_correcta_entra(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=2)
    with TestClient(main.app) as client:
        for _ in range(2):
            login(client, clave="incorrecta-1234")
        assert login(client).status_code == 429


def test_un_login_correcto_reinicia_la_cuenta(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=3)
    with TestClient(main.app) as client:
        for _ in range(2):
            assert login(client, clave="incorrecta-1234").status_code == 401
        assert login(client).status_code == 200
        for _ in range(2):  # empieza de cero: dos fallos más no bloquean
            assert login(client, clave="incorrecta-1234").status_code == 401
        assert login(client).status_code == 200


def test_otro_correo_no_se_ve_afectado(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=2)
    with TestClient(main.app) as client:
        assert login(client).status_code == 200  # crea al directivo
        for _ in range(2):
            login(client, correo="otro@test.edu", clave="incorrecta-1234")
        assert login(client, correo="otro@test.edu", clave="incorrecta-1234").status_code == 429
        assert login(client).status_code == 200


def test_un_correo_inexistente_tambien_se_bloquea_igual(tmp_path, monkeypatch):
    # Mismo comportamiento exista o no la cuenta: no se revela qué correos están registrados.
    preparar(tmp_path, monkeypatch, max_correo=2)
    with TestClient(main.app) as client:
        for _ in range(2):
            assert login(client, correo="fantasma@test.edu", clave="incorrecta-1234").status_code == 401
        assert login(client, correo="fantasma@test.edu", clave="incorrecta-1234").status_code == 429


def test_el_correo_se_normaliza_antes_de_contar(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=2)
    with TestClient(main.app) as client:
        login(client, correo="Admin@Test.edu", clave="incorrecta-1234")
        login(client, correo="  admin@test.edu ", clave="incorrecta-1234")
        assert login(client, correo="ADMIN@TEST.EDU", clave="incorrecta-1234").status_code == 429


def test_el_limite_por_ip_corta_aunque_cambien_los_correos(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=100, max_ip=3)
    # TestClient reporta el host "testclient", que no es una IP atribuible; se simula una IP pública real.
    with TestClient(main.app, client=("203.0.113.7", 50000)) as client:
        for i in range(3):
            assert login(client, correo=f"u{i}@test.edu", clave="incorrecta-1234").status_code == 401
        assert login(client, correo="u99@test.edu", clave="incorrecta-1234").status_code == 429


def test_sin_ip_real_el_limite_por_ip_no_bloquea_a_toda_la_institucion(tmp_path, monkeypatch):
    # Streamlit llama desde el mismo servidor: la API ve 127.0.0.1 para todos. Esa IP no debe bloquearse.
    preparar(tmp_path, monkeypatch, max_correo=100, max_ip=3)
    with TestClient(main.app, client=("127.0.0.1", 50000)) as client:
        for i in range(10):
            assert login(client, correo=f"u{i}@test.edu", clave="incorrecta-1234").status_code == 401
        assert login(client).status_code == 200  # otro usuario legítimo sigue entrando


def test_el_limite_por_correo_sigue_activo_desde_loopback(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=2, max_ip=3)
    with TestClient(main.app, client=("127.0.0.1", 50000)) as client:
        for _ in range(2):
            login(client, clave="incorrecta-1234")
        assert login(client).status_code == 429


def test_una_ip_real_bloqueada_no_afecta_a_otra_ip(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, max_correo=100, max_ip=3)
    with TestClient(main.app, client=("203.0.113.5", 50000)) as atacante:
        for i in range(3):
            assert login(atacante, correo=f"u{i}@test.edu", clave="incorrecta-1234").status_code == 401
        assert login(atacante).status_code == 429
    with TestClient(main.app, client=("198.51.100.7", 50000)) as legitimo:
        assert login(legitimo).status_code == 200


def test_ip_limitable():
    assert main._ip_limitable("203.0.113.5")
    assert main._ip_limitable("2001:db8::1")
    assert not main._ip_limitable("127.0.0.1")
    assert not main._ip_limitable("::1")
    assert not main._ip_limitable("desconocida")
