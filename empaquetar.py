"""Crea un ZIP del proyecto SIN datos personales ni secretos, para compartirlo o entregarlo.

Uso:  python empaquetar.py [salida.zip]

Excluye: bases de datos (*.db, *.sqlite*), .env, claves de Firebase, entornos virtuales (env/, .venv/),
logs, cachés y .git. Si encuentra un archivo que parece una clave privada dentro del proyecto, avisa y lo omite.
Después de crear el ZIP, lista su contenido para que verifiques qué se envía.
"""
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CARPETAS_EXCLUIDAS = {"env", ".venv", "venv", "__pycache__", ".pytest_cache", ".git", "logs", "node_modules"}
# -wal y -shm: archivos temporales del modo WAL de SQLite; contienen datos personales igual que la base.
SUFIJOS_EXCLUIDOS = {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm",
                     ".log", ".pyc", ".zip", ".pem", ".key"}
NOMBRES_EXCLUIDOS = {".env"}
PATRONES_SECRETOS = ("serviceaccountkey", "service-account", "credentials", "firebase-adminsdk")


def debe_omitirse(ruta: Path) -> str | None:
    relativa = ruta.relative_to(RAIZ)
    nombre = ruta.name.lower()
    if any(parte in CARPETAS_EXCLUIDAS for parte in relativa.parts[:-1]):
        return "carpeta excluida"
    if nombre in NOMBRES_EXCLUIDOS or (nombre.startswith(".env.") and nombre != ".env.example"):
        return "variables de entorno"
    if ruta.suffix.lower() in SUFIJOS_EXCLUIDOS:
        return "datos/archivo excluido"
    if nombre.endswith(".json") and any(p in nombre for p in PATRONES_SECRETOS):
        return "posible clave privada"
    return None


def main() -> int:
    salida = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "dataclass_limpio.zip"
    incluidos, omitidos = [], []
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zf:
        for ruta in sorted(RAIZ.rglob("*")):
            if not ruta.is_file() or ruta.resolve() == salida.resolve():
                continue
            motivo = debe_omitirse(ruta)
            if motivo:
                omitidos.append((ruta.relative_to(RAIZ), motivo))
                continue
            zf.write(ruta, ruta.relative_to(RAIZ))
            incluidos.append(ruta.relative_to(RAIZ))
    print(f"ZIP creado: {salida}  ({len(incluidos)} archivos)")
    print("Omitidos:")
    for ruta, motivo in omitidos:
        if any(parte in CARPETAS_EXCLUIDAS for parte in ruta.parts[:-1]):
            continue  # no listar miles de archivos de env/ ni cachés
        print(f"  - {ruta}  [{motivo}]")
    print("Revisa que no falte ni sobre nada antes de compartirlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
