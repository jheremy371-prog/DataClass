"""Funciones de acceso a SQLite para la API de DataClass."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "dataclass.db"


def obtener_conexion() -> sqlite3.Connection:
    """Abre una conexión con claves foráneas habilitadas y filas por nombre."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(DB_PATH, timeout=10)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA busy_timeout = 10000")  # espera hasta 10 s a que otro proceso suelte el bloqueo
    conexion.execute("PRAGMA synchronous = NORMAL")  # con WAL es seguro ante cortes de luz y mucho más rápido que FULL
    return conexion


def normalizar_aulas_existentes(conexion) -> int:
    """Lleva las aulas ya guardadas a la forma canónica («a-302 » -> «A-302») y devuelve cuántas filas cambió.

    Es idempotente. Un docente solo ve a los estudiantes cuya aula es idéntica a la suya, así que una aula escrita
    distinta dejaba al alumno invisible. Los estudiantes cambiados se marcan para volver a sincronizarse.
    Las aulas que no se pueden normalizar (por ejemplo, las que empiezan con «=») se dejan como están.
    """
    from api import validaciones

    cambios = 0
    for tabla in ("estudiantes", "usuarios"):
        for (aula,) in conexion.execute(f"SELECT DISTINCT aula FROM {tabla} WHERE aula IS NOT NULL").fetchall():
            try:
                canonica = validaciones.normalizar_aula(aula)
            except ValueError:
                continue
            if canonica == aula:
                continue
            marca = ", is_synced = 0" if tabla == "estudiantes" else ""
            cursor = conexion.execute(f"UPDATE {tabla} SET aula = ?{marca} WHERE aula = ?", (canonica, aula))
            cambios += cursor.rowcount
    return cambios


def _agregar_columnas_usuarios(conexion) -> None:
    """Bases creadas antes de la v1.8.1: añade token_version y debe_cambiar a usuarios (idempotente)."""
    columnas = {fila[1] for fila in conexion.execute("PRAGMA table_info(usuarios)").fetchall()}
    if "token_version" not in columnas:
        conexion.execute("ALTER TABLE usuarios ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
    if "debe_cambiar" not in columnas:
        conexion.execute(
            "ALTER TABLE usuarios ADD COLUMN debe_cambiar INTEGER NOT NULL DEFAULT 0 CHECK (debe_cambiar IN (0, 1))"
        )


# Versión del esquema, guardada en PRAGMA user_version. Súbela y añade una función a MIGRACIONES cada vez que
# cambie una tabla: las bases existentes se actualizan solas al arrancar y una base de una versión MÁS NUEVA
# que el código se rechaza (evita que un programa viejo estropee datos de uno nuevo).
ESQUEMA_VERSION = 2


def _usar_wal(conexion) -> None:
    """Modo WAL: lectores y un escritor a la vez sin bloquearse. Se guarda en el archivo; no falla si no es posible."""
    if os.getenv("DATACLASS_SQLITE_WAL", "1") == "0":
        return
    try:
        conexion.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass


def _recalcular_secuencias(conexion) -> None:
    """Lleva el contador de IDs «AAAA-0001» al mayor número ya usado (idempotente; nunca lo baja)."""
    conexion.execute(
        """INSERT INTO secuencias (nombre, valor)
        SELECT substr(id_estudiante, 1, 4), MAX(CAST(substr(id_estudiante, 6) AS INTEGER)) FROM estudiantes
        WHERE id_estudiante GLOB '[0-9][0-9][0-9][0-9]-[0-9]*' AND substr(id_estudiante, 6) NOT GLOB '*[^0-9]*'
        GROUP BY 1
        ON CONFLICT(nombre) DO UPDATE SET valor = max(valor, excluded.valor)"""
    )


def _migracion_2(conexion) -> None:
    """v2: tokens_revocados (cierre de sesión real) y secuencias (IDs que no se reutilizan)."""
    _recalcular_secuencias(conexion)


MIGRACIONES = {2: _migracion_2}


def _migrar(conexion) -> None:
    actual = conexion.execute("PRAGMA user_version").fetchone()[0]
    if actual > ESQUEMA_VERSION:
        raise RuntimeError(
            f"La base de datos tiene la versión de esquema {actual} y este programa solo conoce hasta la {ESQUEMA_VERSION}. "
            "Actualiza DataClass antes de abrirla."
        )
    for version in sorted(MIGRACIONES):
        if version > actual:
            MIGRACIONES[version](conexion)
    if actual < ESQUEMA_VERSION:
        conexion.execute(f"PRAGMA user_version = {int(ESQUEMA_VERSION)}")


def inicializar_esquema() -> None:
    """Crea las tablas si aún no existen, sin borrar datos existentes."""
    with closing(obtener_conexion()) as conexion:  # closing: en Windows una conexión abierta bloquea el archivo
        conexion.executescript(
            """
            CREATE TABLE IF NOT EXISTS estudiantes (
                id_estudiante TEXT PRIMARY KEY,
                dni TEXT UNIQUE,
                nombre_completo TEXT NOT NULL,
                aula TEXT,
                telefono_apoderado TEXT,
                riesgo_desercion TEXT DEFAULT 'Pendiente',
                riesgo_reprobacion TEXT DEFAULT 'Pendiente',
                is_synced INTEGER NOT NULL DEFAULT 0 CHECK (is_synced IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS calificaciones (
                id_calificacion INTEGER PRIMARY KEY AUTOINCREMENT,
                id_estudiante TEXT NOT NULL,
                curso_modulo TEXT NOT NULL,
                nota_obtenida REAL NOT NULL CHECK (nota_obtenida >= 0 AND nota_obtenida <= 20),
                periodo_evaluacion TEXT NOT NULL,
                is_synced INTEGER NOT NULL DEFAULT 0 CHECK (is_synced IN (0, 1)),
                FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS asistencias (
                id_asistencia INTEGER PRIMARY KEY AUTOINCREMENT,
                id_estudiante TEXT NOT NULL,
                fecha TEXT NOT NULL,
                estado_asistencia TEXT NOT NULL CHECK (estado_asistencia IN ('presente', 'tardanza', 'falta', 'justificada')),
                is_synced INTEGER NOT NULL DEFAULT 0 CHECK (is_synced IN (0, 1)),
                UNIQUE (id_estudiante, fecha),
                FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS usuarios (
                id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
                correo TEXT NOT NULL UNIQUE,
                nombre_completo TEXT NOT NULL,
                rol TEXT NOT NULL CHECK (rol IN ('docente', 'directivo')),
                aula TEXT,
                password_hash TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
                token_version INTEGER NOT NULL DEFAULT 0,
                debe_cambiar INTEGER NOT NULL DEFAULT 0 CHECK (debe_cambiar IN (0, 1))
            );
            -- Catálogo académico: aulas (grado + sección) y malla curricular (materias de cada grado).
            CREATE TABLE IF NOT EXISTS aulas (
                nombre TEXT PRIMARY KEY,
                grado TEXT NOT NULL,
                seccion TEXT NOT NULL,
                UNIQUE (grado, seccion)
            );
            CREATE TABLE IF NOT EXISTS malla_grado (
                grado TEXT NOT NULL,
                materia TEXT NOT NULL,
                PRIMARY KEY (grado, materia)
            );
            -- Tokens de sesión cerrados antes de vencer (cierre de sesión real). Se limpian solos cuando vencen.
            CREATE TABLE IF NOT EXISTS tokens_revocados (
                jti TEXT PRIMARY KEY,
                id_usuario INTEGER,
                expira_utc TEXT NOT NULL
            );
            -- Mayor número usado de los IDs «AAAA-0001». Solo sube: un ID borrado no se vuelve a entregar.
            CREATE TABLE IF NOT EXISTS secuencias (
                nombre TEXT PRIMARY KEY,
                valor INTEGER NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS estudiantes_secuencia AFTER INSERT ON estudiantes
            WHEN NEW.id_estudiante GLOB '[0-9][0-9][0-9][0-9]-[0-9]*' AND substr(NEW.id_estudiante, 6) NOT GLOB '*[^0-9]*'
            BEGIN
                INSERT INTO secuencias (nombre, valor)
                VALUES (substr(NEW.id_estudiante, 1, 4), CAST(substr(NEW.id_estudiante, 6) AS INTEGER))
                ON CONFLICT(nombre) DO UPDATE SET valor = max(valor, excluded.valor);
            END;
            CREATE INDEX IF NOT EXISTS idx_calificaciones_estudiante ON calificaciones(id_estudiante);
            CREATE INDEX IF NOT EXISTS idx_asistencias_estudiante_fecha ON asistencias(id_estudiante, fecha);
            CREATE TABLE IF NOT EXISTS alertas (
                id_alerta INTEGER PRIMARY KEY AUTOINCREMENT,
                id_estudiante TEXT NOT NULL,
                tipo_alerta TEXT NOT NULL CHECK (tipo_alerta IN ('desercion', 'bajo_rendimiento')),
                nivel_riesgo TEXT NOT NULL CHECK (nivel_riesgo IN ('bajo', 'medio', 'alto')),
                descripcion TEXT NOT NULL,
                fecha_creacion TEXT NOT NULL DEFAULT (datetime('now')),
                estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'en_seguimiento', 'resuelta', 'descartada')),
                version_modelo TEXT,
                probabilidad REAL CHECK (probabilidad IS NULL OR (probabilidad >= 0 AND probabilidad <= 1)),
                FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS intervenciones (
                id_intervencion INTEGER PRIMARY KEY AUTOINCREMENT,
                id_estudiante TEXT NOT NULL,
                id_alerta INTEGER,
                tutor TEXT NOT NULL,
                tipo_intervencion TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                fecha_intervencion TEXT NOT NULL DEFAULT (date('now')),
                resultado TEXT,
                proxima_revision TEXT,
                FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante) ON DELETE CASCADE,
                FOREIGN KEY (id_alerta) REFERENCES alertas(id_alerta) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alertas_estudiante_fecha ON alertas(id_estudiante, fecha_creacion);
            CREATE INDEX IF NOT EXISTS idx_alertas_estado ON alertas(estado, nivel_riesgo);
            CREATE INDEX IF NOT EXISTS idx_intervenciones_estudiante_fecha ON intervenciones(id_estudiante, fecha_intervencion);
            CREATE TABLE IF NOT EXISTS auditoria (
                id_auditoria INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                id_usuario INTEGER,
                rol TEXT,
                ip TEXT,
                accion TEXT NOT NULL,
                metodo TEXT,
                ruta TEXT,
                id_estudiante TEXT,
                estado_http INTEGER,
                detalle TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha_utc);
            CREATE INDEX IF NOT EXISTS idx_auditoria_estudiante ON auditoria(id_estudiante, fecha_utc);
            CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria(id_usuario, fecha_utc);
            CREATE TRIGGER IF NOT EXISTS auditoria_sin_update BEFORE UPDATE ON auditoria
            BEGIN SELECT RAISE(ABORT, 'La bitácora de auditoría es de solo anexado.'); END;
            CREATE TRIGGER IF NOT EXISTS auditoria_sin_delete BEFORE DELETE ON auditoria
            BEGIN SELECT RAISE(ABORT, 'La bitácora de auditoría es de solo anexado.'); END;
            -- Estudiantes borrados localmente cuyos datos aún deben eliminarse de Firestore (se reintenta sin red).
            CREATE TABLE IF NOT EXISTS eliminaciones_nube (
                id_estudiante TEXT PRIMARY KEY,
                fecha_solicitud TEXT NOT NULL DEFAULT (datetime('now'))
            );
            -- Notas y asistencias borradas o cambiadas de fecha localmente cuyo documento aún debe borrarse en Firestore.
            CREATE TABLE IF NOT EXISTS eliminaciones_nube_hijas (
                tabla TEXT NOT NULL CHECK (tabla IN ('calificaciones', 'asistencias')),
                id_estudiante TEXT NOT NULL,
                id_documento TEXT NOT NULL,
                fecha_solicitud TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (tabla, id_estudiante, id_documento)
            );
            """
        )
        _agregar_columnas_usuarios(conexion)
        normalizar_aulas_existentes(conexion)
        _migrar(conexion)
        conexion.commit()
        _usar_wal(conexion)
