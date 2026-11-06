import sqlite3
import os

def agregar_alumnos_prueba():
    db_path = os.path.join(os.path.dirname(__file__), 'dataclass.db')
    conexion = sqlite3.connect(db_path)
    cursor = conexion.cursor()

    # Lista de alumnos de prueba con diferentes niveles de riesgo
    estudiantes_prueba = [
        ('EST-001', '76543210', 'Carlos Mendoza', 'A-302', '987654321', 'Bajo', 'Bajo', 1),
        ('EST-002', '71234567', 'Ana Torres', 'A-302', '912345678', 'Medio', 'Alto', 0),
        ('EST-003', '79876543', 'Luis Quispe', 'B-101', '998877665', 'Alto', 'Alto', 0),
        ('EST-004', '74561238', 'María Huamán', 'B-101', '944332211', 'Bajo', 'Medio', 1),
        ('EST-005', '73214569', 'Jorge Ramos', 'A-302', '955667788', 'Alto', 'Medio', 0)
    ]

    cursor.executemany('''
    INSERT OR REPLACE INTO estudiantes (id_estudiante, dni, nombre_completo, aula, telefono_apoderado, riesgo_desercion, riesgo_reprobacion, is_synced)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', estudiantes_prueba)

    conexion.commit()
    conexion.close()
    print("✅ ¡Alumnos de prueba agregados exitosamente con diferentes niveles de riesgo!")

if __name__ == '__main__':
    agregar_alumnos_prueba()