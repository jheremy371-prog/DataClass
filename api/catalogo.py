"""Catálogo académico: aulas por año/grado, malla curricular (materias por grado) e IDs automáticos de estudiantes.

Modelo (pensado para que cada institución cargue su propia estructura):
    * Grado   = «año» de estudios con el nombre que use la institución («1° Secundaria», «3 años», «Ciclo II»...).
    * Aula    = grado + sección. Su nombre se arma solo («1° SECUNDARIA A») y es el texto que se guarda en
                estudiantes.aula, de modo que el acceso de cada docente por aula sigue funcionando igual.
    * Malla   = materias de un grado. Todas las secciones del grado heredan esas materias.
Este módulo no depende de FastAPI: recibe una conexión SQLite, así se prueba de forma aislada.
"""
import re
import unicodedata
from datetime import date
from typing import Iterable, Optional

from api import validaciones as v

MAX_SECCIONES_POR_GRADO = 30


# ------------------------------------------------------------------------------------------------ normalización
def normalizar_grado(valor) -> str:
    if isinstance(valor, str):
        valor = unicodedata.normalize("NFKC", valor)
    texto = v.normalizar_texto_libre(valor, 40)
    return texto.upper()


def normalizar_seccion(valor) -> str:
    if isinstance(valor, str):
        valor = unicodedata.normalize("NFKC", valor)
    texto = v.normalizar_texto_libre(valor, 10)
    return texto.upper()


def normalizar_materia(valor) -> str:
    return v.normalizar_texto_libre(valor, 120)


def nombre_aula(grado: str, seccion: str) -> str:
    """«1° SECUNDARIA» + «A» -> «1° SECUNDARIA A». Lanza ValueError si supera los 50 caracteres de aula."""
    nombre = v.normalizar_aula(f"{grado} {seccion}")
    if nombre is None:
        raise ValueError("El aula no puede quedar vacía.")
    return nombre


def separar_lista(texto: Optional[str], separadores: str = ";") -> list[str]:
    """Parte «A; B ,C» en ['A','B','C'] ignorando vacíos y repetidos (sin importar mayúsculas)."""
    if not texto:
        return []
    partes = re.split("[" + re.escape(separadores) + "]", str(texto))
    vistos, resultado = set(), []
    for parte in partes:
        limpio = parte.strip()
        if limpio and limpio.lower() not in vistos:
            vistos.add(limpio.lower())
            resultado.append(limpio)
    return resultado


# ------------------------------------------------------------------------------------------------ IDs de estudiante
def siguiente_id_estudiante(conexion, reservados: Iterable[str] = (), anio: Optional[int] = None) -> str:
    """ID automático «AAAA-0001», «AAAA-0002»... (el año es el actual). Nunca repite uno existente, reservado o ya usado.

    Además de los IDs que existen hoy, mira el contador `secuencias` (lo sube un trigger en cada alta), que no retrocede
    al borrar: así un ID de un estudiante eliminado no pasa a otra persona y la bitácora no queda apuntando a un reutilizado.
    """
    anio = anio or date.today().year
    patron = re.compile(rf"{anio}-(\d+)")
    mayor = 0
    try:
        fila = conexion.execute("SELECT valor FROM secuencias WHERE nombre = ?", (str(anio),)).fetchone()
        if fila is not None:
            mayor = int(fila[0])
    except Exception:  # base sin la tabla (anterior a la v2 del esquema): se calcula solo con lo existente
        pass
    for (existente,) in conexion.execute("SELECT id_estudiante FROM estudiantes WHERE id_estudiante LIKE ?", (f"{anio}-%",)):
        coincide = patron.fullmatch(existente)
        if coincide:
            mayor = max(mayor, int(coincide.group(1)))
    for reservado in reservados:
        coincide = patron.fullmatch(str(reservado))
        if coincide:
            mayor = max(mayor, int(coincide.group(1)))
    return f"{anio}-{mayor + 1:04d}"


# ------------------------------------------------------------------------------------------------ consultas
def hay_catalogo(conexion) -> bool:
    return conexion.execute("SELECT 1 FROM aulas LIMIT 1").fetchone() is not None


def aula_existe(conexion, aula: str) -> bool:
    return conexion.execute("SELECT 1 FROM aulas WHERE nombre = ?", (aula,)).fetchone() is not None


def materias_de_grado(conexion, grado: str) -> list[str]:
    return [f[0] for f in conexion.execute("SELECT materia FROM malla_grado WHERE grado = ? ORDER BY materia", (grado,))]


def listar_aulas(conexion, solo_aula: Optional[str] = None) -> list[dict]:
    """Aulas con sus materias (heredadas del grado) y la cantidad de estudiantes. `solo_aula` limita a una (docentes)."""
    consulta = (
        "SELECT a.nombre, a.grado, a.seccion, "
        "(SELECT COUNT(*) FROM estudiantes e WHERE e.aula = a.nombre) AS estudiantes FROM aulas a"
    )
    parametros: tuple = ()
    if solo_aula is not None:
        consulta += " WHERE a.nombre = ?"
        parametros = (solo_aula,)
    consulta += " ORDER BY a.grado, a.seccion"
    malla: dict[str, list[str]] = {}
    for grado, materia in conexion.execute("SELECT grado, materia FROM malla_grado ORDER BY materia"):
        malla.setdefault(grado, []).append(materia)
    return [
        {"nombre": f["nombre"], "grado": f["grado"], "seccion": f["seccion"],
         "materias": malla.get(f["grado"], []), "estudiantes": f["estudiantes"]}
        for f in conexion.execute(consulta, parametros).fetchall()
    ]


def listar_grados(conexion) -> list[dict]:
    """Un registro por grado, con sus secciones y su malla (incluye grados que solo tienen malla)."""
    secciones: dict[str, list[str]] = {}
    for grado, seccion in conexion.execute("SELECT grado, seccion FROM aulas ORDER BY seccion"):
        secciones.setdefault(grado, []).append(seccion)
    malla: dict[str, list[str]] = {}
    for grado, materia in conexion.execute("SELECT grado, materia FROM malla_grado ORDER BY materia"):
        malla.setdefault(grado, []).append(materia)
    return [{"grado": g, "secciones": secciones.get(g, []), "materias": malla.get(g, [])} for g in sorted(set(secciones) | set(malla))]


def _grafias_de_materias(conexion) -> dict[str, str]:
    """clave normalizada -> grafía ya guardada (la existente tiene prioridad, igual que con los cursos de las notas)."""
    grafias: dict[str, str] = {}
    for (materia,) in conexion.execute("SELECT DISTINCT materia FROM malla_grado ORDER BY materia"):
        grafias.setdefault(v.clave_curso(materia), materia)
    return grafias


# ------------------------------------------------------------------------------------------------ escritura
def crear_aulas(conexion, grado: str, secciones: Iterable[str]) -> tuple[list[str], list[str]]:
    """Crea las aulas grado+sección que falten. Devuelve (creadas, ya_existentes). Lanza ValueError si hay choque de nombres."""
    creadas, existentes = [], []
    for seccion in secciones:
        nombre = nombre_aula(grado, seccion)
        previa = conexion.execute("SELECT grado, seccion FROM aulas WHERE nombre = ?", (nombre,)).fetchone()
        if previa is not None:
            if (previa["grado"], previa["seccion"]) != (grado, seccion):
                raise ValueError(f"El aula «{nombre}» ya existe como {previa['grado']} / {previa['seccion']}. Cambia el nombre del grado o de la sección.")
            existentes.append(nombre)
            continue
        conexion.execute("INSERT INTO aulas (nombre, grado, seccion) VALUES (?, ?, ?)", (nombre, grado, seccion))
        creadas.append(nombre)
    return creadas, existentes


def agregar_materia(conexion, grado: str, materia: str) -> tuple[str, bool]:
    """Añade una materia a la malla del grado. Devuelve (grafía_final, es_nueva). «matematica» se une con «Matemática»."""
    canonica = _grafias_de_materias(conexion).get(v.clave_curso(materia), materia)
    ya = conexion.execute("SELECT 1 FROM malla_grado WHERE grado = ? AND materia = ?", (grado, canonica)).fetchone()
    if ya is not None:
        return canonica, False
    conexion.execute("INSERT INTO malla_grado (grado, materia) VALUES (?, ?)", (grado, canonica))
    return canonica, True


def quitar_materia(conexion, grado: str, materia: str) -> bool:
    return conexion.execute("DELETE FROM malla_grado WHERE grado = ? AND materia = ?", (grado, materia)).rowcount > 0


def eliminar_aula(conexion, nombre: str) -> str:
    """Borra un aula SIN estudiantes. Devuelve 'ok', 'no_existe' o 'con_estudiantes'."""
    if not aula_existe(conexion, nombre):
        return "no_existe"
    if conexion.execute("SELECT 1 FROM estudiantes WHERE aula = ? LIMIT 1", (nombre,)).fetchone():
        return "con_estudiantes"
    conexion.execute("DELETE FROM aulas WHERE nombre = ?", (nombre,))
    return "ok"
