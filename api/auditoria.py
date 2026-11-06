"""Bitácora de auditoría: quién hizo qué sobre los datos de los estudiantes, desde dónde y cuándo.

Qué registra: fecha (UTC), usuario y rol, IP, acción (lectura / escritura / eliminación / inicio de sesión),
método y ruta HTTP, estudiante afectado y código de respuesta. Registra también los intentos rechazados
(401/403/404), que son justo los que importan ante un acceso indebido.

Qué NO registra: cuerpos de las peticiones. Solo se guardan identificadores, salvo en las correcciones y
eliminaciones de notas y asistencias y en los cambios de cuentas y alertas, donde el campo «detalle» guarda
«campo: antes->después» para poder reconstruir qué cambió (H-02). Los listados anotan los ids entregados.

La tabla es de solo anexado: unos triggers impiden UPDATE y DELETE. La única forma prevista de borrar
registros viejos es `depurar()`, según el plazo de retención definido por la institución.
Un administrador con acceso directo al archivo SQLite todavía podría alterarla: para una garantía fuerte,
exporta la bitácora periódicamente a un almacenamiento externo de solo escritura.
"""
import logging
import os
import re
import sqlite3
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

logger = logging.getLogger("dataclass.auditoria")

# Rutas que no se auditan: no tocan datos personales y generarían ruido.
# /auth/sesion se llama en cada recarga de página y solo valida el token: no aporta nada a la bitácora.
RUTAS_OMITIDAS = ("/api/v1/auth/login", "/api/v1/auth/sesion", "/api/v1/estado", "/docs", "/redoc", "/openapi.json")
_RUTA_ESTUDIANTE = re.compile(r"^/api/v1/estudiantes/([^/]+)")
_MAX_RUTA = 300
_MAX_DETALLE = 300
RETENCION_DIAS_DEFECTO = 730  # 2 años. Es una decisión de la institución: confírmala con su asesor legal.

TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS auditoria_sin_update BEFORE UPDATE ON auditoria "
    "BEGIN SELECT RAISE(ABORT, 'La bitácora de auditoría es de solo anexado.'); END",
    "CREATE TRIGGER IF NOT EXISTS auditoria_sin_delete BEFORE DELETE ON auditoria "
    "BEGIN SELECT RAISE(ABORT, 'La bitácora de auditoría es de solo anexado.'); END",
)


def omitir_ruta(ruta: str) -> bool:
    return ruta.startswith(RUTAS_OMITIDAS) or not ruta.startswith("/api/")


def clasificar_metodo(metodo: str) -> str:
    metodo = (metodo or "").upper()
    if metodo in ("GET", "HEAD", "OPTIONS"):
        return "lectura"
    if metodo == "DELETE":
        return "eliminacion"
    return "escritura"


def estudiante_de_ruta(ruta: str, parametros: Optional[dict] = None) -> Optional[str]:
    """Extrae el id del estudiante de /estudiantes/{id}/... o del parámetro ?id_estudiante=."""
    coincidencia = _RUTA_ESTUDIANTE.match(ruta or "")
    if coincidencia:
        return coincidencia.group(1)[:50]
    valor = (parametros or {}).get("id_estudiante")
    return valor[:50] if valor else None


def registrar(
    conexion: sqlite3.Connection,
    accion: str,
    *,
    id_usuario: Optional[int] = None,
    rol: Optional[str] = None,
    ip: Optional[str] = None,
    metodo: Optional[str] = None,
    ruta: Optional[str] = None,
    id_estudiante: Optional[str] = None,
    estado_http: Optional[int] = None,
    detalle: Optional[str] = None,
) -> None:
    """Anexa un registro y hace commit. Nunca lanza: auditar no debe tumbar la operación del usuario."""
    try:
        conexion.execute(
            "INSERT INTO auditoria (id_usuario, rol, ip, accion, metodo, ruta, id_estudiante, estado_http, detalle) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id_usuario, rol, ip, accion, metodo,
                (ruta or "")[:_MAX_RUTA] or None, id_estudiante, estado_http,
                (detalle or "")[:_MAX_DETALLE] or None,
            ),
        )
        conexion.commit()
    except sqlite3.Error:
        logger.exception("No se pudo escribir en la bitácora de auditoría (accion=%s)", accion)
        return
    logger.info(
        "audit accion=%s usuario=%s rol=%s ip=%s %s %s estudiante=%s estado=%s",
        accion, id_usuario, rol, ip, metodo, ruta, id_estudiante, estado_http,
    )


def consultar(
    conexion: sqlite3.Connection,
    *,
    id_estudiante: Optional[str] = None,
    id_usuario: Optional[int] = None,
    accion: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    limite: int = 100,
    desplazamiento: int = 0,
) -> list[dict]:
    filtros, parametros = [], []
    if id_estudiante:
        filtros.append("id_estudiante = ?")
        parametros.append(id_estudiante)
    if id_usuario is not None:
        filtros.append("id_usuario = ?")
        parametros.append(id_usuario)
    if accion:
        filtros.append("accion = ?")
        parametros.append(accion)
    if desde:
        filtros.append("fecha_utc >= ?")
        parametros.append(desde)
    if hasta:
        filtros.append("fecha_utc < date(?, '+1 day')")  # 'hasta' incluye todo ese día
        parametros.append(hasta)
    consulta = "SELECT * FROM auditoria"
    if filtros:
        consulta += " WHERE " + " AND ".join(filtros)
    consulta += " ORDER BY id_auditoria DESC LIMIT ? OFFSET ?"
    parametros += [limite, desplazamiento]
    cursor = conexion.execute(consulta, parametros)
    columnas = [c[0] for c in cursor.description]
    return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


def depurar(conexion: sqlite3.Connection, dias: Optional[int] = None) -> int:
    """Borra registros más viejos que `dias` (por defecto DATACLASS_AUDITORIA_RETENCION_DIAS o 730).

    Quita el trigger de borrado, elimina y lo recrea dentro de una sola transacción. Devuelve cuántos borró.
    """
    if dias is None:
        dias = int(os.getenv("DATACLASS_AUDITORIA_RETENCION_DIAS", RETENCION_DIAS_DEFECTO))
    if dias < 30:
        raise ValueError("La retención mínima de la bitácora es de 30 días.")
    try:
        conexion.execute("BEGIN IMMEDIATE")
        conexion.execute("DROP TRIGGER IF EXISTS auditoria_sin_delete")
        cursor = conexion.execute("DELETE FROM auditoria WHERE fecha_utc < datetime('now', ?)", (f"-{int(dias)} days",))
        borrados = cursor.rowcount
        conexion.execute(TRIGGERS[1])
        conexion.commit()
        return borrados
    except sqlite3.Error:
        conexion.rollback()
        raise


def configurar_logging() -> None:
    """Logging a consola y, si DATACLASS_LOG_DIR está definido, a un archivo rotativo (5 x 5 MB)."""
    raiz = logging.getLogger("dataclass")
    if raiz.handlers:
        return
    raiz.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    consola = logging.StreamHandler()
    consola.setFormatter(formato)
    raiz.addHandler(consola)
    carpeta = os.getenv("DATACLASS_LOG_DIR")
    if carpeta:
        Path(carpeta).mkdir(parents=True, exist_ok=True)
        archivo = RotatingFileHandler(Path(carpeta) / "dataclass.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        archivo.setFormatter(formato)
        raiz.addHandler(archivo)
