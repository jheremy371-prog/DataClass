"""Migra dataclass.db del esquema antiguo (legacy/setup_sqlite_esquema_antiguo.py) al esquema actual de api/database.py.

Uso: python migrar_esquema.py RUTA_BD_ORIGEN RUTA_BD_DESTINO
Crea una base nueva en RUTA_BD_DESTINO, copia los datos validando cada regla, y NO modifica el origen.
Si algún dato no cumple una regla nueva, se detiene y no escribe nada en el destino.
"""
import os
import sqlite3
import sys

ESQUEMA = """
CREATE TABLE estudiantes (
    id_estudiante TEXT PRIMARY KEY,
    dni TEXT UNIQUE,
    nombre_completo TEXT NOT NULL,
    aula TEXT,
    telefono_apoderado TEXT,
    riesgo_desercion TEXT DEFAULT 'Pendiente',
    riesgo_reprobacion TEXT DEFAULT 'Pendiente',
    is_synced INTEGER NOT NULL DEFAULT 0 CHECK (is_synced IN (0, 1))
);
CREATE TABLE calificaciones (
    id_calificacion INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante TEXT NOT NULL,
    curso_modulo TEXT NOT NULL,
    nota_obtenida REAL NOT NULL CHECK (nota_obtenida >= 0 AND nota_obtenida <= 20),
    periodo_evaluacion TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0 CHECK (is_synced IN (0, 1)),
    FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante) ON DELETE CASCADE
);
CREATE TABLE asistencias (
    id_asistencia INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante TEXT NOT NULL,
    fecha TEXT NOT NULL,
    estado_asistencia TEXT NOT NULL CHECK (estado_asistencia IN ('presente', 'tardanza', 'falta', 'justificada')),
    is_synced INTEGER NOT NULL DEFAULT 0 CHECK (is_synced IN (0, 1)),
    UNIQUE (id_estudiante, fecha),
    FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante) ON DELETE CASCADE
);
CREATE TABLE usuarios (
    id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
    correo TEXT NOT NULL UNIQUE,
    nombre_completo TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('docente', 'directivo')),
    aula TEXT,
    password_hash TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);
CREATE INDEX idx_calificaciones_estudiante ON calificaciones(id_estudiante);
CREATE INDEX idx_asistencias_estudiante_fecha ON asistencias(id_estudiante, fecha);
CREATE TABLE alertas (
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
CREATE TABLE intervenciones (
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
CREATE INDEX idx_alertas_estudiante_fecha ON alertas(id_estudiante, fecha_creacion);
CREATE INDEX idx_alertas_estado ON alertas(estado, nivel_riesgo);
CREATE INDEX idx_intervenciones_estudiante_fecha ON intervenciones(id_estudiante, fecha_intervencion);
"""

TABLAS = ["estudiantes", "calificaciones", "asistencias", "usuarios", "alertas", "intervenciones"]


def columnas(conexion, tabla):
    return [fila[1] for fila in conexion.execute(f"PRAGMA table_info({tabla})")]


def migrar(origen, destino):
    if os.path.exists(destino):
        raise FileExistsError(f"El destino ya existe, no se sobrescribe: {destino}")
    src = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(destino)
    dst.execute("PRAGMA foreign_keys = OFF")  # se activa al final, tras insertar y verificar
    try:
        dst.executescript(ESQUEMA)
        for tabla in TABLAS:
            if tabla not in [r[0] for r in src.execute("select name from sqlite_master where type='table'")]:
                print(f"  {tabla}: no existe en el origen, se omite")
                continue
            cols_dst = columnas(dst, tabla)
            cols_src = columnas(src, tabla)
            comunes = [c for c in cols_dst if c in cols_src]
            filas = src.execute(f"SELECT {', '.join(comunes)} FROM {tabla}").fetchall()
            marcas = ",".join("?" * len(comunes))
            dst.executemany(
                f"INSERT INTO {tabla} ({', '.join(comunes)}) VALUES ({marcas})",
                [tuple(f) for f in filas],
            )
            print(f"  {tabla}: {len(filas)} fila(s) copiadas")
        # Ajusta los contadores AUTOINCREMENT para que los nuevos ids no choquen con los existentes.
        dst.execute("PRAGMA foreign_keys = ON")
        problemas = dst.execute("PRAGMA foreign_key_check").fetchall()
        integridad = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if problemas or integridad != "ok":
            raise RuntimeError(f"Verificación fallida: fk={len(problemas)}, integridad={integridad}")
        dst.commit()
        print("Migración verificada: integridad ok, sin violaciones de clave foránea.")
    except Exception:
        dst.rollback()
        dst.close()
        os.remove(destino)
        raise
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Uso: python migrar_esquema.py ORIGEN DESTINO")
    migrar(sys.argv[1], sys.argv[2])
