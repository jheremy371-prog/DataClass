"""Carga masiva de estudiantes, calificaciones y asistencias desde CSV o Excel (.xlsx).

Reglas de diseño:
    * Todo o nada: si una sola fila tiene errores no se escribe NADA, y el informe lista cada error con su fila.
    * Idempotente: volver a subir el mismo archivo no duplica datos; las filas que ya existen idénticas se omiten.
    * Nunca sobrescribe: si una fila choca con un dato existente que es distinto, se reporta como error
      (para corregir un dato existente se usa la edición individual, que queda en la bitácora).
    * Mismas reglas que la API individual (api/validaciones.py) y mismos permisos por aula.
    * Este módulo no depende de FastAPI: recibe bytes y una conexión SQLite, así que se prueba de forma aislada.
"""
import csv
import io
import os
import unicodedata
import zipfile
from datetime import date, datetime
from typing import Any, Optional

from api import catalogo
from api import validaciones as v

MAX_BYTES = int(os.getenv("DATACLASS_IMPORT_MAX_MB", "5")) * 1024 * 1024
MAX_FILAS = int(os.getenv("DATACLASS_IMPORT_MAX_FILAS", "5000"))
MAX_ERRORES_INFORME = 200
MAX_ADVERTENCIAS_INFORME = 50
_MAX_DESCOMPRIMIDO = 100 * 1024 * 1024  # defensa contra "bombas zip" dentro de un .xlsx
_LOTE_SQL = 400  # SQLite limita las variables por consulta; se consulta por trozos

HOJA_DATOS = "Datos"  # hoja que se lee de las plantillas de Excel; si no existe, se lee la primera
TIPOS = ("estudiantes", "calificaciones", "asistencias", "aulas")
TIPOS_SOLO_DIRECTIVO = ("estudiantes", "aulas")

COLUMNAS = {
    # id_estudiante es opcional: si va vacío se genera solo (AAAA-0001...).
    "estudiantes": {"obligatorias": ("nombre_completo",), "opcionales": ("id_estudiante", "dni", "aula", "telefono_apoderado")},
    "calificaciones": {"obligatorias": ("id_estudiante", "curso_modulo", "nota_obtenida", "periodo_evaluacion"), "opcionales": ()},
    "asistencias": {"obligatorias": ("id_estudiante", "fecha", "estado_asistencia"), "opcionales": ()},
    # Una fila por grado (año): sus secciones y las materias de su malla, separadas por «;».
    "aulas": {"obligatorias": ("grado", "secciones"), "opcionales": ("materias",)},
}

_ALIAS = {
    "id": "id_estudiante", "codigo": "id_estudiante", "id_estudiante": "id_estudiante",
    "nombre": "nombre_completo", "nombres": "nombre_completo", "nombre_completo": "nombre_completo", "estudiante": "nombre_completo",
    "dni": "dni", "documento": "dni",
    "aula": "aula", "salon": "aula", "grupo": "aula",
    "telefono": "telefono_apoderado", "celular": "telefono_apoderado", "telefono_apoderado": "telefono_apoderado",
    "curso": "curso_modulo", "modulo": "curso_modulo", "curso_modulo": "curso_modulo", "asignatura": "curso_modulo",
    "nota": "nota_obtenida", "calificacion": "nota_obtenida", "nota_obtenida": "nota_obtenida",
    "periodo": "periodo_evaluacion", "bimestre": "periodo_evaluacion", "periodo_evaluacion": "periodo_evaluacion",
    "fecha": "fecha",
    "grado": "grado", "anio": "grado", "ano": "grado", "year": "grado",
    "secciones": "secciones", "seccion": "secciones", "salones": "secciones",
    "materias": "materias", "materia": "materias", "cursos": "materias", "asignaturas": "materias",
    "estado": "estado_asistencia", "asistencia": "estado_asistencia", "estado_asistencia": "estado_asistencia",
}


class ErrorArchivo(Exception):
    """El archivo no se puede leer o no tiene la estructura esperada (no hay informe por fila)."""


# --------------------------------------------------------------------------------------- lectura de archivos
def _clave_columna(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", str(texto)) if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "_" for c in sin_tildes.lower()).strip("_")


def _celda_a_texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else repr(valor)
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).strip()


def _filas_csv(contenido: bytes) -> list[list[str]]:
    if b"\x00" in contenido:
        raise ErrorArchivo("El archivo CSV contiene caracteres nulos; no parece un CSV válido.")
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            texto = contenido.decode("cp1252")  # CSV exportado por Excel en Windows
        except UnicodeDecodeError as exc:
            raise ErrorArchivo("No se pudo leer la codificación del CSV. Guárdalo como 'CSV UTF-8'.") from exc
    primera = texto.split("\n", 1)[0]
    delimitador = max((",", ";", "\t"), key=primera.count)
    try:
        return [[c.strip() for c in fila] for fila in csv.reader(io.StringIO(texto), delimiter=delimitador)]
    except csv.Error as exc:
        raise ErrorArchivo(f"El CSV está mal formado: {exc}") from exc


def _filas_xlsx(contenido: bytes) -> list[list[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            nombres = [i.filename.lower() for i in z.infolist()]
            if sum(i.file_size for i in z.infolist()) > _MAX_DESCOMPRIMIDO:
                raise ErrorArchivo("El archivo Excel descomprimido es demasiado grande.")
    except zipfile.BadZipFile as exc:
        raise ErrorArchivo("El archivo no es un Excel .xlsx válido.") from exc
    if any(n.endswith("vbaproject.bin") for n in nombres):
        raise ErrorArchivo("No se admiten libros con macros. Guarda el archivo como .xlsx sin macros.")
    try:
        from openpyxl import load_workbook

        libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except ImportError as exc:
        raise ErrorArchivo("Falta instalar openpyxl en el servidor para leer archivos Excel.") from exc
    except Exception as exc:  # openpyxl lanza tipos variados con archivos dañados
        raise ErrorArchivo("No se pudo abrir el archivo Excel; puede estar dañado.") from exc
    try:
        hoja = libro[HOJA_DATOS] if HOJA_DATOS in libro.sheetnames else libro.worksheets[0]
        filas = []
        for fila in hoja.iter_rows(values_only=True):
            textos = [_celda_a_texto(c) for c in fila]
            if not any(t.strip() for t in textos):
                continue  # las plantillas traen miles de filas con formato pero vacías
            filas.append(textos)
            if len(filas) > MAX_FILAS + 1:
                break  # se detecta abajo; no hace falta leer el resto
        return filas
    except Exception as exc:
        raise ErrorArchivo("No se pudo leer la hoja de datos del Excel.") from exc
    finally:
        libro.close()


def leer_tabla(contenido: bytes, nombre_archivo: str, tipo: str) -> tuple[list[str], list[tuple[int, dict]]]:
    """Devuelve (columnas_ignoradas, [(numero_de_fila, {columna: texto}), ...]). Lanza ErrorArchivo si no sirve."""
    if tipo not in TIPOS:
        raise ErrorArchivo("Tipo de carga no válido.")
    if not contenido:
        raise ErrorArchivo("El archivo está vacío.")
    if len(contenido) > MAX_BYTES:
        raise ErrorArchivo(f"El archivo supera el máximo de {MAX_BYTES // (1024 * 1024)} MB.")
    extension = os.path.splitext((nombre_archivo or "").lower())[1]
    if extension == ".csv":
        filas = _filas_csv(contenido)
    elif extension == ".xlsx":
        filas = _filas_xlsx(contenido)
    else:
        raise ErrorArchivo("Formato no admitido. Sube un archivo .csv o .xlsx.")

    filas = [f for f in filas if any(c.strip() for c in f)]  # descarta filas totalmente vacías
    if not filas:
        raise ErrorArchivo("El archivo no tiene datos.")
    cabecera, datos = filas[0], filas[1:]
    if not datos:
        raise ErrorArchivo("El archivo solo tiene la fila de encabezados; no hay filas de datos.")
    if len(datos) > MAX_FILAS:
        raise ErrorArchivo(f"El archivo tiene más de {MAX_FILAS} filas. Divídelo en varios archivos.")

    esperadas = COLUMNAS[tipo]
    posiciones: dict[str, int] = {}
    ignoradas = []
    for indice, titulo in enumerate(cabecera):
        if not titulo.strip():
            continue
        canonica = _ALIAS.get(_clave_columna(titulo))
        if canonica is None or canonica not in esperadas["obligatorias"] + esperadas["opcionales"]:
            ignoradas.append(titulo.strip()[:40])
        elif canonica in posiciones:
            raise ErrorArchivo(f"La columna '{canonica}' aparece repetida en el encabezado.")
        else:
            posiciones[canonica] = indice
    faltan = [c for c in esperadas["obligatorias"] if c not in posiciones]
    if faltan:
        raise ErrorArchivo("Faltan columnas obligatorias: " + ", ".join(faltan) + ".")

    # Número de fila como lo ve la persona en Excel: el encabezado es la fila 1.
    resultado = []
    for orden, fila in enumerate(datos, start=2):
        resultado.append((orden, {c: (fila[i] if i < len(fila) else "") for c, i in posiciones.items()}))
    return ignoradas, resultado


# ------------------------------------------------------------------------------------------------ informe
class _Informe:
    def __init__(self, tipo: str, simulacion: bool, total: int):
        self.datos = {
            "tipo": tipo, "simulacion": simulacion, "total_filas": total, "filas_con_error": 0, "nuevas": 0,
            "ya_existentes": 0, "errores": [], "errores_total": 0, "advertencias": [], "advertencias_total": 0,
            "aplicado": False,
        }
        self._filas_error: set[int] = set()
        self.afectados: set[str] = set()

    def error(self, fila: int, campo: str, motivo: str) -> None:
        self.datos["errores_total"] += 1
        self._filas_error.add(fila)
        if len(self.datos["errores"]) < MAX_ERRORES_INFORME:
            self.datos["errores"].append({"fila": fila, "campo": campo, "motivo": motivo})

    def advertencia(self, fila: int, motivo: str) -> None:
        self.datos["advertencias_total"] += 1
        if len(self.datos["advertencias"]) < MAX_ADVERTENCIAS_INFORME:
            self.datos["advertencias"].append({"fila": fila, "motivo": motivo})

    @property
    def hay_errores(self) -> bool:
        return self.datos["errores_total"] > 0

    def cerrar(self) -> dict:
        self.datos["filas_con_error"] = len(self._filas_error)
        return self.datos


def _validar_campo(informe: _Informe, fila: int, campo: str, funcion, *args):
    """Ejecuta una validación; si falla registra el error y devuelve un centinela."""
    try:
        return funcion(*args)
    except ValueError as exc:
        mensaje = str(exc)
        if campo == "dni" and args and isinstance(args[0], str) and args[0].strip().isdigit() and len(args[0].strip()) == 7:
            mensaje += " Si tenía un cero al inicio, Excel pudo quitarlo: da formato Texto a la columna."
        informe.error(fila, campo, mensaje)
        return _INVALIDO


_INVALIDO = object()


def _por_trozos(conexion, consulta_con_marcas: str, ids: list[str]) -> list:
    """Ejecuta una consulta con 'IN ({marcas})' en trozos para no superar el límite de variables de SQLite."""
    filas = []
    for i in range(0, len(ids), _LOTE_SQL):
        trozo = ids[i:i + _LOTE_SQL]
        filas.extend(conexion.execute(consulta_con_marcas.format(marcas=",".join("?" * len(trozo))), trozo).fetchall())
    return filas


def _estudiantes_visibles(conexion, usuario: dict) -> set[str]:
    """Directivo: todos. Docente: solo los de su aula (sin aula asignada no ve ninguno), igual que la API individual."""
    if usuario["rol"] == "directivo":
        return {f[0] for f in conexion.execute("SELECT id_estudiante FROM estudiantes")}
    if not usuario.get("aula"):
        return set()
    return {f[0] for f in conexion.execute("SELECT id_estudiante FROM estudiantes WHERE aula = ?", (usuario["aula"],))}


def _id_visible(informe, fila, valor, visibles):
    id_estudiante = _validar_campo(informe, fila, "id_estudiante", v.normalizar_id_institucional, valor)
    if id_estudiante is _INVALIDO:
        return _INVALIDO
    if id_estudiante not in visibles:
        informe.error(fila, "id_estudiante", "Estudiante no encontrado.")  # igual para 'no existe' y 'otra aula'
        return _INVALIDO
    return id_estudiante


def _clave_curso(nombre: str) -> str:
    return v.clave_curso(nombre)  # ignora mayúsculas, tildes, espacios y signos (misma regla que la API)


# -------------------------------------------------------------------------------------------- por tipo
def _preparar_estudiantes(conexion, filas, informe):
    campos = ("dni", "nombre_completo", "aula", "telefono_apoderado")
    existentes = {f[0]: dict(zip(campos, f[1:])) for f in conexion.execute(
        "SELECT id_estudiante, dni, nombre_completo, aula, telefono_apoderado FROM estudiantes")}
    dni_a_id = {f["dni"]: id_e for id_e, f in existentes.items() if f["dni"]}
    con_catalogo = catalogo.hay_catalogo(conexion)
    vistos_id: dict[str, int] = {}
    vistos_dni: dict[str, int] = {}
    # IDs escritos a mano en el archivo: los automáticos no deben chocar con ellos aunque aparezcan más abajo.
    reservados = {(f.get("id_estudiante") or "").strip() for _, f in filas}
    reservados.discard("")
    nuevas = []
    for numero, f in filas:
        bruto_id = (f.get("id_estudiante") or "").strip()
        id_e = _validar_campo(informe, numero, "id_estudiante", v.normalizar_id_institucional, bruto_id) if bruto_id else None
        nombre = _validar_campo(informe, numero, "nombre_completo", v.normalizar_nombre, f.get("nombre_completo", ""))
        dni = _validar_campo(informe, numero, "dni", v.normalizar_dni, f.get("dni")) if "dni" in f else None
        aula = _validar_campo(informe, numero, "aula", v.normalizar_aula, f.get("aula")) if "aula" in f else None
        tel = _validar_campo(informe, numero, "telefono_apoderado", v.normalizar_telefono, f.get("telefono_apoderado")) if "telefono_apoderado" in f else None
        if any(x is _INVALIDO for x in (id_e, nombre, dni, aula, tel)):
            continue
        if id_e is not None:
            if id_e in vistos_id:
                informe.error(numero, "id_estudiante", f"ID repetido en el archivo (también en la fila {vistos_id[id_e]}).")
                continue
            vistos_id[id_e] = numero
        if dni:
            if dni in vistos_dni:
                informe.error(numero, "dni", f"DNI repetido en el archivo (también en la fila {vistos_dni[dni]}).")
                continue
            vistos_dni[dni] = numero
        if id_e is None and dni and dni in dni_a_id:
            # Sin ID pero con un DNI ya registrado: es ese estudiante (así volver a subir el archivo no duplica).
            id_e = dni_a_id[dni]
            if id_e in vistos_id:
                informe.error(numero, "dni", f"Ese DNI ya corresponde al ID {id_e}, que aparece en la fila {vistos_id[id_e]}.")
                continue
            vistos_id[id_e] = numero
        if id_e is not None and dni and dni_a_id.get(dni, id_e) != id_e:
            informe.error(numero, "dni", "Ese DNI ya está registrado para otro estudiante.")
            continue
        previo = existentes.get(id_e) if id_e is not None else None
        if previo is not None:
            comparados = {"nombre_completo": nombre}
            if "dni" in f:
                comparados["dni"] = dni
            if "aula" in f:
                comparados["aula"] = aula
            if "telefono_apoderado" in f:
                comparados["telefono_apoderado"] = tel
            if all((previo[k] or None) == (val or None) for k, val in comparados.items()):
                informe.datos["ya_existentes"] += 1
            else:
                informe.error(numero, "id_estudiante", "El ID ya existe con datos distintos. Para corregirlo usa la edición individual.")
            continue
        if aula and con_catalogo and not catalogo.aula_existe(conexion, aula):
            informe.error(numero, "aula", f"El aula «{aula}» no existe. Créala antes (pestaña «Aulas y materias») o corrige el nombre.")
            continue
        if id_e is None:
            id_e = catalogo.siguiente_id_estudiante(conexion, reservados)
            reservados.add(id_e)
            vistos_id[id_e] = numero
            if not dni:
                informe.advertencia(numero, f"Sin ID ni DNI: se asignó {id_e}. Si subes el archivo otra vez se creará un duplicado.")
        nuevas.append((id_e, dni, nombre, aula, tel))
    return nuevas, ("INSERT INTO estudiantes (id_estudiante, dni, nombre_completo, aula, telefono_apoderado) VALUES (?, ?, ?, ?, ?)")


def _preparar_aulas(conexion, filas, informe):
    """Una fila por grado: crea las aulas grado+sección y añade las materias a la malla del grado. Nunca borra ni cambia nada."""
    aulas_previas = {f["nombre"]: (f["grado"], f["seccion"]) for f in conexion.execute("SELECT nombre, grado, seccion FROM aulas")}
    malla_previa = {(f["grado"], f["materia"]) for f in conexion.execute("SELECT grado, materia FROM malla_grado")}
    grafias = catalogo._grafias_de_materias(conexion)
    aulas_nuevas: list[tuple] = []
    malla_nueva: list[tuple] = []
    aulas_vistas: dict[str, tuple] = {}
    for numero, f in filas:
        grado = _validar_campo(informe, numero, "grado", catalogo.normalizar_grado, f.get("grado"))
        crudas = catalogo.separar_lista(f.get("secciones"), ";,")
        if not crudas:
            informe.error(numero, "secciones", "Escribe al menos una sección (por ejemplo A;B;C).")
            continue
        if len(crudas) > catalogo.MAX_SECCIONES_POR_GRADO:
            informe.error(numero, "secciones", f"Máximo {catalogo.MAX_SECCIONES_POR_GRADO} secciones por grado.")
            continue
        secciones = [_validar_campo(informe, numero, "secciones", catalogo.normalizar_seccion, s) for s in crudas]
        materias = [_validar_campo(informe, numero, "materias", catalogo.normalizar_materia, m)
                    for m in catalogo.separar_lista(f.get("materias"), ";")]
        if grado is _INVALIDO or any(x is _INVALIDO for x in secciones + materias):
            continue
        nombres = []
        try:
            for seccion in dict.fromkeys(secciones):
                nombres.append((catalogo.nombre_aula(grado, seccion), seccion))
        except ValueError as exc:
            informe.error(numero, "grado", str(exc))
            continue
        hay_choque = False
        for nombre, seccion in nombres:
            otra = aulas_previas.get(nombre) or aulas_vistas.get(nombre)
            if otra is not None and otra != (grado, seccion):
                informe.error(numero, "secciones", f"El aula «{nombre}» ya existe como {otra[0]} / {otra[1]}. Cambia el grado o la sección.")
                hay_choque = True
        if hay_choque:
            continue
        for nombre, seccion in nombres:
            if nombre in aulas_previas or nombre in aulas_vistas:
                informe.datos["ya_existentes"] += 1
                continue
            aulas_vistas[nombre] = (grado, seccion)
            aulas_nuevas.append((nombre, grado, seccion))
        for materia in materias:
            clave = v.clave_curso(materia)
            canonica = grafias.setdefault(clave, materia)
            if canonica != materia:
                informe.advertencia(numero, f"Materia '{materia}' unificada con '{canonica}'.")
            if (grado, canonica) in malla_previa:
                informe.datos["ya_existentes"] += 1
                continue
            malla_previa.add((grado, canonica))
            malla_nueva.append((grado, canonica))
    todas = aulas_nuevas + malla_nueva
    return todas, [
        ("INSERT INTO aulas (nombre, grado, seccion) VALUES (?, ?, ?)", aulas_nuevas),
        ("INSERT INTO malla_grado (grado, materia) VALUES (?, ?)", malla_nueva),
    ]


def _preparar_calificaciones(conexion, filas, informe, usuario):
    visibles = _estudiantes_visibles(conexion, usuario)
    cursos = {}  # clave normalizada -> grafía que se conserva (la ya existente tiene prioridad)
    for (nombre,) in conexion.execute("SELECT DISTINCT curso_modulo FROM calificaciones ORDER BY curso_modulo"):
        cursos.setdefault(_clave_curso(nombre), nombre)

    validas = []
    for numero, f in filas:
        id_e = _id_visible(informe, numero, f.get("id_estudiante"), visibles)
        curso = _validar_campo(informe, numero, "curso_modulo", v.normalizar_texto_libre, f.get("curso_modulo"), 120)
        nota = _validar_campo(informe, numero, "nota_obtenida", v.normalizar_nota, f.get("nota_obtenida"))
        periodo = _validar_campo(informe, numero, "periodo_evaluacion", v.normalizar_texto_libre, f.get("periodo_evaluacion"), 80)
        if _INVALIDO in (id_e, curso, nota, periodo):
            continue
        canonico = cursos.setdefault(_clave_curso(curso), curso)
        if canonico != curso:
            informe.advertencia(numero, f"Curso '{curso}' unificado con '{canonico}'.")
        validas.append((numero, id_e, canonico, nota, periodo))

    ids = sorted({r[1] for r in validas})
    existentes = {(f[0], f[1], f[2], f[3]) for f in _por_trozos(
        conexion, "SELECT id_estudiante, curso_modulo, periodo_evaluacion, nota_obtenida FROM calificaciones WHERE id_estudiante IN ({marcas})", ids)}
    vistos: dict[tuple, int] = {}
    nuevas = []
    for numero, id_e, curso, nota, periodo in validas:
        clave = (id_e, curso, periodo, nota)
        if clave in existentes:
            informe.datos["ya_existentes"] += 1
            continue
        if clave in vistos:
            informe.error(numero, "id_estudiante", f"Fila repetida en el archivo (igual a la fila {vistos[clave]}).")
            continue
        vistos[clave] = numero
        nuevas.append((id_e, curso, nota, periodo))
    return nuevas, "INSERT INTO calificaciones (id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion) VALUES (?, ?, ?, ?)"


def _preparar_asistencias(conexion, filas, informe, usuario, hoy):
    visibles = _estudiantes_visibles(conexion, usuario)
    validas = []
    for numero, f in filas:
        id_e = _id_visible(informe, numero, f.get("id_estudiante"), visibles)
        fecha = _validar_campo(informe, numero, "fecha", v.normalizar_fecha_asistencia, f.get("fecha"), hoy)
        estado = _validar_campo(informe, numero, "estado_asistencia", v.normalizar_estado_asistencia, f.get("estado_asistencia"))
        if _INVALIDO in (id_e, fecha, estado):
            continue
        validas.append((numero, id_e, fecha, estado))

    ids = sorted({r[1] for r in validas})
    existentes = {(f[0], f[1]): f[2] for f in _por_trozos(
        conexion, "SELECT id_estudiante, fecha, estado_asistencia FROM asistencias WHERE id_estudiante IN ({marcas})", ids)}
    vistos: dict[tuple, int] = {}
    nuevas = []
    for numero, id_e, fecha, estado in validas:
        clave = (id_e, fecha)
        if clave in vistos:
            informe.error(numero, "fecha", f"Ya hay una asistencia de este estudiante en esa fecha en la fila {vistos[clave]}.")
            continue
        vistos[clave] = numero
        if clave in existentes:
            if existentes[clave] == estado:
                informe.datos["ya_existentes"] += 1
            else:
                informe.error(numero, "estado_asistencia", f"Ya existe una asistencia en esa fecha con estado '{existentes[clave]}'.")
            continue
        nuevas.append((id_e, fecha, estado))
    return nuevas, "INSERT INTO asistencias (id_estudiante, fecha, estado_asistencia) VALUES (?, ?, ?)"


# ---------------------------------------------------------------------------------------------- principal
def importar(conexion, tipo: str, filas: list[tuple[int, dict]], usuario: dict, simular: bool = True,
             hoy: Optional[date] = None) -> dict:
    """Valida todas las filas y, si no hay errores y `simular` es False, las inserta en una sola transacción.

    `usuario` = {"rol": "docente" | "directivo", "aula": str | None}, tomado de la base (no del token).
    Devuelve el informe; el conjunto de estudiantes afectados queda en informe["_afectados"] (lista) para que
    la API vuelva a evaluar su riesgo, y debe retirarse antes de responder al cliente.
    """
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de carga no válido: {tipo}")
    if tipo in TIPOS_SOLO_DIRECTIVO and usuario.get("rol") != "directivo":
        raise PermissionError("Solo un directivo puede importar estudiantes y aulas.")

    informe = _Informe(tipo, simular, len(filas))
    if tipo == "estudiantes":
        nuevas, sentencia = _preparar_estudiantes(conexion, filas, informe)
    elif tipo == "aulas":
        nuevas, sentencia = _preparar_aulas(conexion, filas, informe)
    elif tipo == "calificaciones":
        nuevas, sentencia = _preparar_calificaciones(conexion, filas, informe, usuario)
    else:
        nuevas, sentencia = _preparar_asistencias(conexion, filas, informe, usuario, hoy or date.today())

    informe.datos["nuevas"] = len(nuevas)
    if not simular and not informe.hay_errores and nuevas:
        try:
            for sql, lote in (sentencia if isinstance(sentencia, list) else [(sentencia, nuevas)]):
                if lote:
                    conexion.executemany(sql, lote)
            conexion.commit()
        except Exception:
            conexion.rollback()
            raise
        informe.datos["aplicado"] = True
        informe.afectados = set() if tipo == "aulas" else {fila[0] for fila in nuevas}
    resultado = informe.cerrar()
    resultado["_afectados"] = sorted(informe.afectados)
    return resultado
