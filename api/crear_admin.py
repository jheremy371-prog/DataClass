"""Crea (o repara) la cuenta de un directivo sin dejar la clave en .env.

    python -m api.crear_admin --correo directivo@institucion.edu --nombre "Nombre Apellido"

La clave se pide por teclado (no se muestra ni queda en el historial del terminal). Si el correo ya existe
como directivo, se restablece su clave y se cierran sus sesiones. Después de usarlo, borra
DATACLASS_ADMIN_PASSWORD de .env.
"""
import argparse
import getpass
import sys
from contextlib import closing

from api import database, seguridad, validaciones


def crear_o_restablecer(correo: str, nombre: str, password: str) -> str:
    """Devuelve 'creado' o 'restablecido'. Lanza ValueError si la clave no cumple la política."""
    correo = validaciones.normalizar_correo(correo)
    seguridad.validar_politica(password, correo)
    database.inicializar_esquema()
    with closing(database.obtener_conexion()) as conexion:
        with conexion:
            existente = conexion.execute("SELECT id_usuario, rol FROM usuarios WHERE correo = ?", (correo,)).fetchone()
            if existente is None:
                conexion.execute(
                    "INSERT INTO usuarios (correo, nombre_completo, rol, password_hash, activo) VALUES (?, ?, 'directivo', ?, 1)",
                    (correo, nombre.strip(), seguridad.hash_password(password)),
                )
                return "creado"
            if existente["rol"] != "directivo":
                raise ValueError("Ese correo pertenece a un docente; no se convierte en directivo desde aquí.")
            conexion.execute(
                "UPDATE usuarios SET password_hash = ?, activo = 1, debe_cambiar = 0, token_version = token_version + 1 "
                "WHERE id_usuario = ?",
                (seguridad.hash_password(password), existente["id_usuario"]),
            )
            return "restablecido"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crear o restablecer un directivo de DataClass.")
    parser.add_argument("--correo", required=True)
    parser.add_argument("--nombre", default="Administrador DataClass")
    args = parser.parse_args(argv)
    clave = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
    if clave != getpass.getpass("Repite la contraseña: "):
        print("Las contraseñas no coinciden.", file=sys.stderr)
        return 1
    try:
        resultado = crear_o_restablecer(args.correo, args.nombre, clave)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Directivo {resultado}. Ahora puedes borrar DATACLASS_ADMIN_PASSWORD de .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
