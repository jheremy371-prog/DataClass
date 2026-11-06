import sqlite3
import os

def crear_base_datos():
    db_path = os.path.join(os.path.dirname(__file__), 'dataclass.db')
    conexion = sqlite3.connect(db_path)
    cursor = conexion.cursor()

    # Creación de tabla Estudiantes
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estudiantes (
        id_estudiante TEXT PRIMARY KEY,
        dni TEXT,
        nombre_completo TEXT,
        aula TEXT,
        telefono_apoderado TEXT,
        riesgo_desercion TEXT,
        riesgo_reprobacion TEXT,
        is_synced INTEGER DEFAULT 0
    )
    ''')

    # Creación de tabla Calificaciones
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS calificaciones (
        id_calificacion INTEGER PRIMARY KEY AUTOINCREMENT,
        id_estudiante TEXT,
        curso_modulo TEXT,
        nota_obtenida REAL,
        periodo_evaluacion TEXT,
        is_synced INTEGER DEFAULT 0,
        FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante)
    )
    ''')

    # Creación de tabla Asistencias
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS asistencias (
        id_asistencia INTEGER PRIMARY KEY AUTOINCREMENT,
        id_estudiante TEXT,
        fecha TEXT,
        estado_asistencia TEXT,
        is_synced INTEGER DEFAULT 0,
        FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante)
    )
    ''')

    conexion.commit()
    conexion.close()
    print(f"Base de datos verificada/creada exitosamente en: {db_path}")

def insertar_datos_prueba():
    db_path = os.path.join(os.path.dirname(__file__), 'dataclass.db')
    conexion = sqlite3.connect(db_path)
    cursor = conexion.cursor()

    # Simulación 1: Inserción de un alumno de prueba
    cursor.execute('''
    INSERT OR IGNORE INTO estudiantes (id_estudiante, dni, nombre_completo, aula, telefono_apoderado, riesgo_desercion, riesgo_reprobacion, is_synced)
    VALUES ('EST-001', '76543210', 'Carlos Mendoza', 'A-302', '987654321', 'Pendiente', 'Pendiente', 0)
    ''')

    # Simulación 2: Inserción de una nota offline (is_synced = 0)
    cursor.execute('''
    INSERT INTO calificaciones (id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion, is_synced)
    VALUES ('EST-001', 'Matemáticas Aplicadas', 10.5, 'Primer Bimestre', 0)
    ''')

    conexion.commit()
    conexion.close()
    print("Datos de prueba insertados correctamente (Estado: is_synced = 0)")

if __name__ == '__main__':
    crear_base_datos()
    insertar_datos_prueba()