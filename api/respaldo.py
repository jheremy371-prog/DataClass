"""Copia de seguridad CIFRADA de la base de datos, y su restauración.

Uso:
    python -m api.respaldo crear [carpeta_destino]
    python -m api.respaldo restaurar archivo.dcbak [ruta_base_destino]
    python -m api.respaldo verificar archivo.dcbak

La clave sale de DATACLASS_RESPALDO_CLAVE (mínimo 32 caracteres; guárdala FUERA del servidor de la base y del
repositorio: sin ella el respaldo no se puede abrir). Se usa la API de copia de SQLite, que es coherente aunque la
base esté en uso y en modo WAL, y se cifra con Fernet (AES-128-CBC + HMAC) con una clave derivada por PBKDF2.
Una copia de seguridad contiene datos personales: aplica la política de retención de docs/CUMPLIMIENTO_LEY_29733.md.
"""
import base64
from contextlib import closing
import hashlib
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from api.database import DB_PATH

MAGIA = b"DCBAK1"
SAL_BYTES = 16
ITERACIONES = 600_000


def _clave(sal: bytes) -> bytes:
    secreto = os.environ.get("DATACLASS_RESPALDO_CLAVE", "")
    if len(secreto) < 32:
        raise SystemExit("Define DATACLASS_RESPALDO_CLAVE con al menos 32 caracteres (fuera del repositorio).")
    derivada = hashlib.pbkdf2_hmac("sha256", secreto.encode("utf-8"), sal, ITERACIONES, dklen=32)
    return base64.urlsafe_b64encode(derivada)


def crear(destino_dir: Path, origen: Path = DB_PATH) -> Path:
    if not origen.exists():
        raise SystemExit(f"No existe la base de datos: {origen}")
    destino_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "copia.db"
        # closing(): en Windows, `with sqlite3.connect()` NO cierra el archivo y el directorio temporal no se puede borrar.
        with closing(sqlite3.connect(origen)) as fuente, closing(sqlite3.connect(copia)) as espejo:
            fuente.backup(espejo)
        sal = os.urandom(SAL_BYTES)
        cifrado = Fernet(_clave(sal)).encrypt(copia.read_bytes())
    salida = destino_dir / f"dataclass_{datetime.now():%Y%m%d_%H%M%S}.dcbak"
    salida.write_bytes(MAGIA + sal + cifrado)
    try:
        salida.chmod(0o600)
    except OSError:
        pass  # en Windows chmod casi no tiene efecto
    return salida


def _descifrar(archivo: Path) -> bytes:
    datos = archivo.read_bytes()
    if not datos.startswith(MAGIA):
        raise SystemExit("El archivo no es un respaldo de DataClass.")
    sal = datos[len(MAGIA):len(MAGIA) + SAL_BYTES]
    try:
        return Fernet(_clave(sal)).decrypt(datos[len(MAGIA) + SAL_BYTES:])
    except InvalidToken:
        raise SystemExit("Clave incorrecta o respaldo dañado.") from None


def verificar(archivo: Path) -> int:
    """Descifra, abre la copia y ejecuta PRAGMA integrity_check. Devuelve el número de estudiantes."""
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "verificacion.db"
        ruta.write_bytes(_descifrar(archivo))
        with closing(sqlite3.connect(ruta)) as conexion:
            estado = conexion.execute("PRAGMA integrity_check").fetchone()[0]
            if estado != "ok":
                raise SystemExit(f"La copia está dañada: {estado}")
            return conexion.execute("SELECT COUNT(*) FROM estudiantes").fetchone()[0]


def restaurar(archivo: Path, destino: Path = DB_PATH) -> None:
    if destino.exists():
        raise SystemExit(f"{destino} ya existe: muévelo o bórralo antes de restaurar (no se sobrescribe).")
    verificar(archivo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(_descifrar(archivo))


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"crear", "restaurar", "verificar"}:
        print(__doc__)
        return 2
    if argv[1] == "crear":
        print(f"Respaldo creado: {crear(Path(argv[2]) if len(argv) > 2 else Path('respaldos'))}")
    elif argv[1] == "verificar":
        print(f"Respaldo válido. Estudiantes: {verificar(Path(argv[2]))}")
    else:
        restaurar(Path(argv[2]), Path(argv[3]) if len(argv) > 3 else DB_PATH)
        print("Restaurado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
