"""H-04: hash versionado, política de contraseñas, migración de esquema y comando crear_admin (sin FastAPI)."""
import hashlib
import sqlite3

import pytest

import api.database as database
from api import crear_admin, seguridad


def hash_antiguo(password, salt=b"0123456789abcdef"):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}:{digest.hex()}"


def test_el_hash_nuevo_es_versionado_y_se_verifica():
    almacenado = seguridad.hash_password("Una-clave-larga-2026")
    assert almacenado.startswith(f"pbkdf2_sha256${seguridad.ITERACIONES}$")
    assert seguridad.verificar_password("Una-clave-larga-2026", almacenado)
    assert not seguridad.verificar_password("otra-clave-larga-2026", almacenado)
    assert not seguridad.necesita_rehash(almacenado)


def test_dos_hashes_de_la_misma_clave_difieren_por_la_sal():
    assert seguridad.hash_password("Una-clave-larga-2026") != seguridad.hash_password("Una-clave-larga-2026")


def test_el_formato_antiguo_sigue_verificando_y_pide_rehash():
    almacenado = hash_antiguo("Clave-antigua-2026")
    assert seguridad.verificar_password("Clave-antigua-2026", almacenado)
    assert not seguridad.verificar_password("Clave-antigua-2027", almacenado)
    assert seguridad.necesita_rehash(almacenado)


@pytest.mark.parametrize("basura", ["", "x", "a:b", "pbkdf2_sha256$abc$00$00", "pbkdf2_sha256$600000$zz$00", None])
def test_hashes_danados_nunca_verifican_ni_lanzan(basura):
    assert seguridad.verificar_password("cualquier-clave-2026", basura) is False


def test_el_hash_ficticio_existe_y_no_acepta_claves_comunes():
    assert not seguridad.verificar_password("Prueba-segura-2026!", seguridad.HASH_FICTICIO)


@pytest.mark.parametrize("clave", ["corta-1A", "1234567890123", "aaaaaaaaaaaaaaaa", " espacios-al-borde-1 ", "x" * 129])
def test_politica_rechaza_claves_debiles(clave):
    with pytest.raises(ValueError):
        seguridad.validar_politica(clave)


def test_politica_rechaza_el_usuario_del_correo():
    with pytest.raises(ValueError):
        seguridad.validar_politica("maria.lopez-2026!", "maria.lopez@colegio.edu")
    assert seguridad.validar_politica("Otra-clave-larga-2026", "maria.lopez@colegio.edu")


def test_la_clave_temporal_cumple_la_politica_y_no_se_repite():
    claves = {seguridad.contrasena_temporal() for _ in range(20)}
    assert len(claves) == 20
    for clave in claves:
        assert seguridad.validar_politica(clave)


def test_migracion_agrega_columnas_a_una_base_antigua(tmp_path, monkeypatch):
    ruta = tmp_path / "vieja.db"
    monkeypatch.setattr(database, "DB_PATH", ruta)
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE usuarios (id_usuario INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT NOT NULL UNIQUE,
            nombre_completo TEXT NOT NULL, rol TEXT NOT NULL, aula TEXT, password_hash TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1);
        INSERT INTO usuarios (correo, nombre_completo, rol, password_hash) VALUES ('a@x.edu', 'A', 'directivo', 'h');
    """)
    con.commit()
    con.close()
    database.inicializar_esquema()
    database.inicializar_esquema()  # idempotente
    con = sqlite3.connect(ruta)
    fila = con.execute("SELECT token_version, debe_cambiar FROM usuarios WHERE correo = 'a@x.edu'").fetchone()
    con.close()
    assert fila == (0, 0)


def _leer(correo):
    con = database.obtener_conexion()
    try:
        return con.execute("SELECT rol, activo, password_hash, token_version FROM usuarios WHERE correo = ?", (correo,)).fetchone()
    finally:
        con.close()


def test_crear_admin_crea_y_luego_restablece(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "admin.db")
    assert crear_admin.crear_o_restablecer("Dir@Colegio.edu", "Dir", "Clave-directiva-2026") == "creado"
    fila = _leer("dir@colegio.edu")
    assert fila["rol"] == "directivo" and seguridad.verificar_password("Clave-directiva-2026", fila["password_hash"])
    assert crear_admin.crear_o_restablecer("dir@colegio.edu", "Dir", "Otra-clave-directiva-2026") == "restablecido"
    fila2 = _leer("dir@colegio.edu")
    assert seguridad.verificar_password("Otra-clave-directiva-2026", fila2["password_hash"])
    assert fila2["token_version"] == fila["token_version"] + 1


def test_crear_admin_rechaza_clave_debil_y_no_convierte_docentes(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "admin2.db")
    with pytest.raises(ValueError):
        crear_admin.crear_o_restablecer("dir@colegio.edu", "Dir", "corta")
    database.inicializar_esquema()
    con = database.obtener_conexion()
    con.execute("INSERT INTO usuarios (correo, nombre_completo, rol, password_hash) VALUES ('doc@colegio.edu', 'Doc', 'docente', 'h')")
    con.commit()
    con.close()
    with pytest.raises(ValueError):
        crear_admin.crear_o_restablecer("doc@colegio.edu", "Doc", "Clave-directiva-2026")
