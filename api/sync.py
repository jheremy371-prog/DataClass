"""Sincronización hacia Firebase Firestore: estudiantes, calificaciones y asistencias.

Solo utiliza credenciales indicadas explícitamente mediante FIREBASE_CREDENTIALS_PATH.
Si no se configura una ruta, funciona en modo simulación y no marca registros como sincronizados.

Minimización (H-03): a la nube NO sale el nombre, el DNI, el teléfono ni el ID real del estudiante. Cada
estudiante viaja con un seudónimo (HMAC-SHA256 del ID con la clave secreta DATACLASS_SEUDONIMO_CLAVE, que
debe guardarse fuera de la nube). Sin esa clave no se envía nada. Solo salen el seudónimo, el aula, los niveles
de riesgo, y de cada nota o asistencia, sus datos académicos.

Estructura en Firestore (<seudonimo> = seudónimo del estudiante):
    <coleccion>/<seudonimo>                             aula y niveles de riesgo
    <coleccion>/<seudonimo>/calificaciones/<id>         una nota
    <coleccion>/<seudonimo>/asistencias/<fecha>         una asistencia (la fecha es única por estudiante)

Calificaciones y asistencias se envían en lotes (WriteBatch, máximo 500 operaciones por lote). Un lote es
atómico: si falla, todo el lote queda pendiente (is_synced = 0) y se reintenta en la siguiente pasada.

SyncWorker repite la sincronización cada cierto tiempo y, si hay fallos (por ejemplo sin internet), espera
cada vez más entre intentos hasta un máximo.
"""
import hashlib
import hmac
import os
import sqlite3
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "dataclass.db"

LOTE_MAX = 500  # límite de Firestore por WriteBatch
_CREAR = object()  # "crea el cliente tú mismo"; None significa modo simulación

TABLAS_HIJAS = {
    "calificaciones": {
        "clave": "id_calificacion",
        "campos": ("id_calificacion", "id_estudiante", "curso_modulo", "nota_obtenida", "periodo_evaluacion"),
        "campos_nube": ("id_calificacion", "curso_modulo", "nota_obtenida", "periodo_evaluacion"),
        "id_documento": lambda fila: str(fila["id_calificacion"]),
    },
    "asistencias": {
        "clave": "id_asistencia",
        "campos": ("id_asistencia", "id_estudiante", "fecha", "estado_asistencia"),
        "campos_nube": ("id_asistencia", "fecha", "estado_asistencia"),
        "id_documento": lambda fila: fila["fecha"],
    },
}


CLAVE_MIN = 32


def _clave_seudonimo(clave=None) -> bytes:
    """La clave secreta del seudónimo. Sin ella (o si es corta) no se envía nada a la nube."""
    clave = clave if clave is not None else os.getenv("DATACLASS_SEUDONIMO_CLAVE", "")
    if len(clave) < CLAVE_MIN or "REEMPLAZA" in clave.upper():
        raise RuntimeError(
            f"DATACLASS_SEUDONIMO_CLAVE falta o tiene menos de {CLAVE_MIN} caracteres. Genera una con: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))" y guárdala fuera de la nube y del repositorio.'
        )
    return clave.encode("utf-8")


def seudonimo(id_estudiante, clave=None) -> str:
    """Código que identifica al estudiante en la nube sin revelar su ID real (24 caracteres hexadecimales)."""
    return hmac.new(_clave_seudonimo(clave), str(id_estudiante).encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _verificar_clave():
    """Devuelve True si hay clave válida; si no, lo informa y devuelve False (no se envía nada)."""
    try:
        _clave_seudonimo()
        return True
    except RuntimeError as exc:
        print(f"Sincronización detenida: {exc}")
        return False


def _crear_cliente_firestore():
    # Las credenciales deben configurarse fuera del repositorio mediante variable de entorno.
    credenciales = os.getenv("FIREBASE_CREDENTIALS_PATH")

    if not credenciales:
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as exc:
        raise RuntimeError("Instala firebase-admin ejecutando: pip install firebase-admin") from exc

    if not Path(credenciales).is_file():
        raise RuntimeError(f"El archivo de credenciales no existe en la ruta: {credenciales}")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        app = firebase_admin.initialize_app(credentials.Certificate(credenciales))

    return firestore.client(app=app)


def _abrir_base():
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos local: {DB_PATH}")
    conexion = sqlite3.connect(DB_PATH, timeout=10)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def _obtener_cliente(cliente):
    """Devuelve (cliente, error). error es True si no se pudo crear el cliente."""
    if cliente is not _CREAR:
        return cliente, False
    try:
        return _crear_cliente_firestore(), False
    except Exception as e:
        print(f"Error al inicializar Firebase: {e}")
        return None, True


def sincronizar_estudiantes(cliente=_CREAR):
    """Envía los estudiantes con is_synced = 0. Devuelve {"enviados": n, "errores": n}."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos local: {DB_PATH}")

    coleccion = os.getenv("FIREBASE_COLLECTION", "estudiantes")

    cliente, fallo_cliente = _obtener_cliente(cliente)
    if fallo_cliente:
        return {"enviados": 0, "errores": 1}

    modo_real = cliente is not None

    with sqlite3.connect(DB_PATH, timeout=10) as conexion:
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")

        # Consultar registros pendientes de sincronización (is_synced = 0)
        pendientes = conexion.execute(
            "SELECT id_estudiante, aula, riesgo_desercion, "
            "riesgo_reprobacion FROM estudiantes WHERE is_synced = 0"
        ).fetchall()

        if not pendientes:
            print("🟢 Todo al día: No hay estudiantes pendientes de sincronización.")
            return {"enviados": 0, "errores": 0}

        if not modo_real:
            print(f"⚠️ MODO SIMULACIÓN: Se encontraron {len(pendientes)} estudiante(s) pendientes.")
            print(f"💡 Para conectar con la nube real, configura FIREBASE_CREDENTIALS_PATH con la ruta segura del archivo de credenciales fuera del repositorio.")
            for alumno in pendientes:
                print(f"   - Pendiente local: {alumno['id_estudiante']}")
            return {"enviados": 0, "errores": 0}

        if not _verificar_clave():
            return {"enviados": 0, "errores": 1}

        print(f"🚀 Conexión establecida con Firestore. Sincronizando {len(pendientes)} registro(s)...")
        exitosos = 0
        errores = []

        for alumno in pendientes:
            id_estudiante = alumno["id_estudiante"]
            id_nube = seudonimo(id_estudiante)
            documento = {
                "id_anonimo": id_nube,
                "aula": alumno["aula"],
                "riesgo_desercion": alumno["riesgo_desercion"],
                "riesgo_reprobacion": alumno["riesgo_reprobacion"],
            }
            try:
                # Envío real a Firebase Firestore
                cliente.collection(coleccion).document(id_nube).set(documento, merge=True)

                # Actualizar bandera local a 1 solo si Firebase confirmó el éxito
                conexion.execute(
                    "UPDATE estudiantes SET is_synced = 1 WHERE id_estudiante = ?",
                    (id_estudiante,),
                )
                conexion.commit()
                exitosos += 1
                print(f"   ✔ Sincronizado exitosamente: {id_estudiante}")

            except Exception as exc:
                conexion.rollback()
                errores.append(id_estudiante)
                print(f"   ❌ Falló la sincronización de {id_estudiante}: {type(exc).__name__} - {exc}")

        print(f"\n📊 Sincronización finalizada. Exitosos en la nube: {exitosos}; Pendientes por error: {len(errores)}.")
        return {"enviados": exitosos, "errores": len(errores)}


def sincronizar_tabla(tabla, cliente=_CREAR, tamano_lote=LOTE_MAX):
    """Envía en lotes las filas de `tabla` (calificaciones o asistencias) con is_synced = 0.

    Devuelve {"enviados": n, "errores": n}. Cada lote se confirma en Firestore antes de marcarse en SQLite,
    así que un fallo nunca marca como sincronizado algo que no llegó.
    """
    if tabla not in TABLAS_HIJAS:
        raise ValueError(f"Tabla no sincronizable: {tabla}")
    if not 1 <= tamano_lote <= LOTE_MAX:
        raise ValueError(f"El tamaño de lote debe estar entre 1 y {LOTE_MAX}.")
    config = TABLAS_HIJAS[tabla]
    clave = config["clave"]

    coleccion = os.getenv("FIREBASE_COLLECTION", "estudiantes")
    cliente, fallo_cliente = _obtener_cliente(cliente)
    if fallo_cliente:
        return {"enviados": 0, "errores": 1}

    with _abrir_base() as conexion:
        pendientes = conexion.execute(
            f"SELECT {', '.join(config['campos'])} FROM {tabla} WHERE is_synced = 0 ORDER BY {clave}"
        ).fetchall()

        if not pendientes:
            print(f"🟢 Todo al día: No hay {tabla} pendientes de sincronización.")
            return {"enviados": 0, "errores": 0}

        if cliente is None:
            print(f"⚠️ MODO SIMULACIÓN: {len(pendientes)} {tabla} pendiente(s). Configura FIREBASE_CREDENTIALS_PATH para enviarlas.")
            return {"enviados": 0, "errores": 0}

        if not _verificar_clave():
            return {"enviados": 0, "errores": 1}

        print(f"🚀 Sincronizando {len(pendientes)} {tabla} en lotes de hasta {tamano_lote}...")
        enviados = errores = 0
        for inicio in range(0, len(pendientes), tamano_lote):
            grupo = pendientes[inicio:inicio + tamano_lote]
            try:
                lote = cliente.batch()
                for fila in grupo:
                    id_nube = seudonimo(fila["id_estudiante"])
                    referencia = (
                        cliente.collection(coleccion).document(id_nube)
                        .collection(tabla).document(config["id_documento"](fila))
                    )
                    documento = {"id_anonimo": id_nube, **{campo: fila[campo] for campo in config["campos_nube"]}}
                    lote.set(referencia, documento, merge=True)
                lote.commit()
                marcas = ",".join("?" * len(grupo))
                conexion.execute(f"UPDATE {tabla} SET is_synced = 1 WHERE {clave} IN ({marcas})", [fila[clave] for fila in grupo])
                conexion.commit()
                enviados += len(grupo)
            except Exception as exc:
                conexion.rollback()
                errores += len(grupo)
                print(f"   ❌ Falló un lote de {len(grupo)} {tabla}: {type(exc).__name__} - {exc}")

        print(f"📊 {tabla}: enviados {enviados}; pendientes por error {errores}.")
        return {"enviados": enviados, "errores": errores}


def _borrar_subcoleccion(cliente, referencia_estudiante, nombre, tamano_lote=LOTE_MAX):
    """Firestore NO borra las subcolecciones al borrar un documento: hay que vaciarlas por lotes."""
    total = 0
    while True:
        documentos = list(referencia_estudiante.collection(nombre).limit(tamano_lote).stream())
        if not documentos:
            return total
        lote = cliente.batch()
        for documento in documentos:
            lote.delete(documento.reference)
        lote.commit()
        total += len(documentos)


def sincronizar_eliminaciones(cliente=_CREAR):
    """Borra de Firestore a los estudiantes eliminados localmente (derecho de supresión).

    Cada id queda en la tabla `eliminaciones_nube` hasta que Firestore confirme el borrado, de modo que
    si no hay red se reintenta en la siguiente pasada. Sin credenciales (modo simulación) no borra nada
    y deja las solicitudes pendientes. Devuelve {"enviados": n, "errores": n}.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos local: {DB_PATH}")
    coleccion = os.getenv("FIREBASE_COLLECTION", "estudiantes")
    cliente, fallo_cliente = _obtener_cliente(cliente)
    if fallo_cliente:
        return {"enviados": 0, "errores": 1}

    with _abrir_base() as conexion:
        try:
            pendientes = [f[0] for f in conexion.execute(
                "SELECT id_estudiante FROM eliminaciones_nube ORDER BY fecha_solicitud, id_estudiante"
            ).fetchall()]
        except sqlite3.OperationalError:  # base anterior a esta versión: aún no existe la tabla
            return {"enviados": 0, "errores": 0}
        if not pendientes:
            return {"enviados": 0, "errores": 0}
        if cliente is None:
            print(f"⚠️ MODO SIMULACIÓN: {len(pendientes)} eliminación(es) pendiente(s) en la nube. Configura FIREBASE_CREDENTIALS_PATH.")
            return {"enviados": 0, "errores": 0}
        if not _verificar_clave():
            return {"enviados": 0, "errores": 1}

        enviados = errores = 0
        for id_estudiante in pendientes:
            try:
                referencia = cliente.collection(coleccion).document(seudonimo(id_estudiante))
                for tabla in TABLAS_HIJAS:
                    _borrar_subcoleccion(cliente, referencia, tabla)
                referencia.delete()
                conexion.execute("DELETE FROM eliminaciones_nube WHERE id_estudiante = ?", (id_estudiante,))
                conexion.commit()
                enviados += 1
            except Exception as exc:
                conexion.rollback()
                errores += 1
                print(f"   ❌ No se pudo eliminar {id_estudiante} de la nube: {type(exc).__name__} - {exc}")
        print(f"🗑️ Eliminaciones en la nube: {enviados} confirmadas; {errores} pendientes por error.")
        return {"enviados": enviados, "errores": errores}


def sincronizar_eliminaciones_hijas(cliente=_CREAR):
    """Borra de Firestore las notas y asistencias eliminadas (o con la fecha cambiada) localmente.

    Cada documento queda en `eliminaciones_nube_hijas` hasta que Firestore confirme el borrado; sin red o sin
    credenciales se reintenta en la siguiente pasada. Borrar un documento que ya no existe no da error.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos local: {DB_PATH}")
    coleccion = os.getenv("FIREBASE_COLLECTION", "estudiantes")
    cliente, fallo_cliente = _obtener_cliente(cliente)
    if fallo_cliente:
        return {"enviados": 0, "errores": 1}

    with _abrir_base() as conexion:
        try:
            pendientes = conexion.execute(
                "SELECT tabla, id_estudiante, id_documento FROM eliminaciones_nube_hijas ORDER BY fecha_solicitud"
            ).fetchall()
        except sqlite3.OperationalError:  # base anterior a esta versión: aún no existe la tabla
            return {"enviados": 0, "errores": 0}
        if not pendientes:
            return {"enviados": 0, "errores": 0}
        if cliente is None:
            print(f"⚠️ MODO SIMULACIÓN: {len(pendientes)} borrado(s) de notas/asistencias pendiente(s) en la nube.")
            return {"enviados": 0, "errores": 0}
        if not _verificar_clave():
            return {"enviados": 0, "errores": 1}

        enviados = errores = 0
        for tabla, id_estudiante, id_documento in pendientes:
            try:
                cliente.collection(coleccion).document(seudonimo(id_estudiante)).collection(tabla).document(id_documento).delete()
                conexion.execute(
                    "DELETE FROM eliminaciones_nube_hijas WHERE tabla = ? AND id_estudiante = ? AND id_documento = ?",
                    (tabla, id_estudiante, id_documento),
                )
                conexion.commit()
                enviados += 1
            except Exception as exc:
                conexion.rollback()
                errores += 1
                print(f"   ❌ No se pudo borrar {tabla}/{id_documento} de {id_estudiante} en la nube: {type(exc).__name__} - {exc}")
        print(f"🗑️ Borrados de notas/asistencias en la nube: {enviados} confirmados; {errores} pendientes por error.")
        return {"enviados": enviados, "errores": errores}


def sincronizar_todo():
    """Estudiantes primero, luego calificaciones y asistencias, con un solo cliente de Firestore."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos local: {DB_PATH}")
    cliente, fallo_cliente = _obtener_cliente(_CREAR)
    if fallo_cliente:
        return {"enviados": 0, "errores": 1}
    total = {"enviados": 0, "errores": 0}
    # Las eliminaciones van primero: si un id se borró y se volvió a crear, el alta posterior lo restaura.
    for resultado in (
        sincronizar_eliminaciones(cliente),
        sincronizar_eliminaciones_hijas(cliente),
        sincronizar_estudiantes(cliente),
        sincronizar_tabla("calificaciones", cliente),
        sincronizar_tabla("asistencias", cliente),
    ):
        total["enviados"] += resultado["enviados"]
        total["errores"] += resultado["errores"]
    return total


class SyncWorker(threading.Thread):
    """Hilo en segundo plano que sincroniza cada `intervalo` segundos.

    Con fallos (red caída, Firestore no disponible) duplica la espera en cada intento seguido, hasta
    `espera_maxima`; al primer éxito vuelve al intervalo normal. Nunca muere por una excepción.
    """

    def __init__(self, intervalo=30.0, espera_maxima=600.0, tarea=None):
        super().__init__(daemon=True, name="SyncWorker")
        self.intervalo = float(intervalo)
        self.espera_maxima = float(espera_maxima)
        self.tarea = tarea or sincronizar_todo
        self.fallos_consecutivos = 0
        self._detener = threading.Event()

    def ejecutar_ciclo(self) -> float:
        """Hace una pasada y devuelve cuántos segundos esperar antes de la siguiente."""
        try:
            resultado = self.tarea() or {}
            fallo = bool(resultado.get("errores"))
        except Exception as exc:
            print(f"SyncWorker: {type(exc).__name__} - {exc}")
            fallo = True
        if fallo:
            self.fallos_consecutivos += 1
            return min(self.intervalo * (2 ** self.fallos_consecutivos), self.espera_maxima)
        self.fallos_consecutivos = 0
        return self.intervalo

    def run(self):
        while not self._detener.is_set():
            self._detener.wait(self.ejecutar_ciclo())

    def detener(self):
        self._detener.set()


if __name__ == "__main__":
    # Al ejecutar `python -m api.sync` nadie más ha cargado el .env (la API sí lo hace en main.py).
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
    sincronizar_todo()