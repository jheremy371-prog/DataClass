"""Crea una base de datos de DEMOSTRACIÓN con personas inventadas (nunca datos reales).

Uso (desde la raíz del proyecto):
    python database/datos_demo.py                       # escribe database/dataclass.db si no existe
    python database/datos_demo.py --destino demo.db     # otra ruta
    python database/datos_demo.py --forzar              # sobrescribe el destino (¡borra lo que haya!)

Los DNI empiezan con 00000 y los teléfonos con +51 9000, patrones que no corresponden a personas reales, para que
cualquiera que vea la base sepa de inmediato que es de prueba.
"""
import argparse
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PERFILES = [  # (nombre, aula, nota base, probabilidad de falta)
    ("Estudiante Demo Uno", "DEMO-A", 16.5, 0.03),
    ("Estudiante Demo Dos", "DEMO-A", 11.0, 0.25),
    ("Estudiante Demo Tres", "DEMO-A", 7.0, 0.55),
    ("Estudiante Demo Cuatro", "DEMO-B", 14.0, 0.10),
    ("Estudiante Demo Cinco", "DEMO-B", 8.5, 0.45),
]


def crear_demo(destino: Path, semilla: int = 2026) -> Path:
    import api.database as bd

    bd.DB_PATH = Path(destino)
    bd.inicializar_esquema()
    azar = random.Random(semilla)
    inicio = date(2026, 9, 1)
    with sqlite3.connect(bd.DB_PATH) as con:
        con.execute("PRAGMA foreign_keys = ON")
        for i, (nombre, aula, base, p_falta) in enumerate(PERFILES, start=1):
            id_est = f"DEMO-{i:03d}"
            con.execute(
                "INSERT OR IGNORE INTO estudiantes (id_estudiante, dni, nombre_completo, aula, telefono_apoderado) VALUES (?, ?, ?, ?, ?)",
                (id_est, f"{i:08d}", nombre, aula, f"+51900000{i:03d}"),
            )
            for curso in ("Matemática", "Comunicación"):
                nota = max(0, min(20, round(azar.gauss(base, 1.5), 1)))
                con.execute(
                    "INSERT INTO calificaciones (id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion) "
                    "SELECT ?, ?, ?, 'Bimestre 1' WHERE NOT EXISTS (SELECT 1 FROM calificaciones WHERE id_estudiante = ? AND curso_modulo = ?)",
                    (id_est, curso, nota, id_est, curso),
                )
            for dia in range(10):
                estado = "falta" if azar.random() < p_falta else "presente"
                con.execute(
                    "INSERT OR IGNORE INTO asistencias (id_estudiante, fecha, estado_asistencia) VALUES (?, ?, ?)",
                    (id_est, (inicio + timedelta(days=dia)).isoformat(), estado),
                )
    return bd.DB_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea una base de datos de demostración con datos inventados.")
    parser.add_argument("--destino", default=str(RAIZ / "database" / "dataclass.db"))
    parser.add_argument("--forzar", action="store_true", help="Sobrescribe el destino si ya existe.")
    args = parser.parse_args()
    destino = Path(args.destino)
    if destino.exists():
        if not args.forzar:
            print(f"{destino} ya existe. Usa --forzar para sobrescribirlo o --destino para otra ruta.")
            return 1
        destino.unlink()
    print(f"Base de demostración creada en {crear_demo(destino)} (personas inventadas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
