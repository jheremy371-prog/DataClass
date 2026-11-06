"""Plantillas de Excel (.xlsx) para la carga masiva.

Cada plantilla trae dos hojas:
    * «Datos»: la que se llena y se sube. Es la primera hoja, con los encabezados exactos, formato Texto en las
      columnas que lo necesitan (así el DNI no pierde ceros) y validaciones de Excel (estado, nota).
    * «Instrucciones»: explica cada columna, con ejemplos y errores frecuentes. El importador NO la lee.

Los ejemplos están solo en «Instrucciones» y no en «Datos», para que nadie importe por error filas de ejemplo.
Los encabezados salen de api/importacion.py (COLUMNAS), de modo que plantilla e importador no se desfasen.
"""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from api import importacion

HOJA_DATOS = importacion.HOJA_DATOS
HOJA_INSTRUCCIONES = "Instrucciones"
FILAS_FORMATEADAS = importacion.MAX_FILAS  # formato y validaciones hasta el máximo que admite el importador

_AZUL = "1769AA"
_AZUL_CLARO = "EAF4FC"
_BORDE = Border(*(Side(style="thin", color="C9D6E2"),) * 4)

# columna -> (obligatoria, formato esperado, ejemplo, nota)
ESPECIFICACION = {
    "estudiantes": {
        "titulo": "Plantilla de carga de estudiantes",
        "columnas": {
            "nombre_completo": (True, "Solo letras, espacios, apóstrofe, guion y punto (mín. 2 caracteres).", "Ana Pérez Rojas",
                                "Nombres y apellidos. No uses números ni símbolos."),
            "id_estudiante": (False, "Déjalo VACÍO para que el sistema lo genere (2026-0001, 2026-0002...). Si lo escribes: letras, números, punto, guion o guion bajo (máx. 50).", "2026-0001",
                              "Solo llénalo si tu institución ya tiene códigos propios que quieres conservar. No puede repetirse en el archivo."),
            "dni": (False, "Exactamente 8 dígitos. Déjalo vacío si no se tiene.", "12345678",
                    "La columna ya tiene formato Texto: no lo cambies o Excel quitará los ceros iniciales."),
            "aula": (False, "Texto corto (máx. 50). Si ya creaste las aulas, debe coincidir con una de ellas (ej. 1° SECUNDARIA A).", "1° SECUNDARIA A",
                     "Define quién puede ver al estudiante: cada docente ve solo su aula. Carga primero las aulas (tipo «aulas») para que existan."),
            "telefono_apoderado": (False, "7 a 15 dígitos; puede empezar con +.", "987654321",
                                   "Se aceptan espacios y guiones; se limpian al importar."),
        },
        "ejemplos": [
            ["Ana Pérez Rojas", "", "12345678", "1° SECUNDARIA A", "987654321"],
            ["Luis Soto Vega", "", "", "1° SECUNDARIA A", ""],
        ],
        "errores": [
            "DNI con 7 dígitos: Excel quitó un cero inicial. Escríbelo completo (la columna ya es de texto).",
            "Dos filas con el mismo id_estudiante o el mismo DNI.",
            "Escribir un aula que no existe: primero carga las aulas (plantilla «aulas») o créalas en «Aulas y materias».",
            "Sin ID ni DNI no se puede detectar duplicados: si subes dos veces el archivo se crean dos veces los mismos estudiantes.",
            "Un id_estudiante que ya existe con datos distintos: el sistema no sobrescribe; corrígelo desde «Registro académico → Corregir registros».",
            "Nombres con números o símbolos.",
        ],
    },
    "calificaciones": {
        "titulo": "Plantilla de carga de calificaciones",
        "columnas": {
            "id_estudiante": (True, "El mismo código con el que se registró al estudiante.", "EST-001",
                              "El estudiante debe existir antes: primero importa los estudiantes. Un docente solo puede cargar a su aula."),
            "curso_modulo": (True, "Texto (máx. 120). No puede empezar con =, +, - ni @.", "Matemática",
                             "Escribe siempre igual el nombre de cada curso. Se unifican mayúsculas, tildes y espacios."),
            "nota_obtenida": (True, "Número de 0 a 20, con coma o punto decimal.", "14,5",
                              "La columna avisa si escribes un valor fuera de 0 a 20."),
            "periodo_evaluacion": (True, "Texto (máx. 80).", "2026-II",
                                   "Por ejemplo 2026-II, Bimestre 1 o Módulo 2. Mantén el mismo estilo en todo el archivo."),
        },
        "ejemplos": [
            ["EST-001", "Matemática", "14,5", "2026-II"],
            ["EST-002", "Matemática", "11", "2026-II"],
        ],
        "errores": [
            "Notas fuera del rango de 0 a 20 o con texto («aprobado», «NP»).",
            "id_estudiante que no existe o que pertenece a otra aula (el sistema responde igual para no revelar datos).",
            "La misma nota repetida dos veces en el archivo (mismo estudiante, curso, periodo y nota).",
            "Cursos escritos de formas muy distintas («Matemática» y «Matemáticas Aplicadas») se tratan como cursos diferentes.",
        ],
    },
    "asistencias": {
        "titulo": "Plantilla de carga de asistencias",
        "columnas": {
            "id_estudiante": (True, "El mismo código con el que se registró al estudiante.", "EST-001",
                              "El estudiante debe existir antes. Un docente solo puede cargar a su aula."),
            "fecha": (True, "Fecha del día: AAAA-MM-DD o DD/MM/AAAA. No puede ser futura.", "2026-10-01",
                      "Si escribes la fecha en Excel, la columna la muestra como AAAA-MM-DD."),
            "estado_asistencia": (True, "presente, tardanza, falta o justificada (también P, T, F, J).", "presente",
                                  "Elige de la lista desplegable de la columna."),
        },
        "ejemplos": [
            ["EST-001", "2026-10-01", "presente"],
            ["EST-002", "2026-10-01", "falta"],
        ],
        "errores": [
            "Fechas futuras o con formato raro (por ejemplo 31/02/2026).",
            "Estados que no están en la lista (por ejemplo «asistió» o «NA»).",
            "Dos filas del mismo estudiante en la misma fecha.",
            "Una fecha que ya tiene otro estado registrado: el sistema no sobrescribe; corrígelo desde «Registro académico → Corregir registros».",
        ],
    },
    "aulas": {
        "titulo": "Plantilla de carga de aulas y materias (malla curricular)",
        "columnas": {
            "grado": (True, "Nombre del año o grado, como lo llama tu institución (máx. 40).", "1° Secundaria",
                      "Ejemplos: 1° Secundaria, 5° Primaria, 3 años, Ciclo II. Escríbelo siempre igual en todas las filas."),
            "secciones": (True, "Secciones del grado separadas por punto y coma (;). Máx. 30.", "A;B;C",
                          "Cada sección crea un aula: «1° Secundaria» + «A» -> aula «1° SECUNDARIA A». Si el grado tiene una sola sección, escribe una sola (ej. U)."),
            "materias": (False, "Materias del grado separadas por punto y coma (;). Cada una máx. 120.", "Matemática;Comunicación;Ciencia y Tecnología",
                         "Es la malla curricular del grado: todas sus secciones usan las mismas materias. Puedes dejarlo vacío y añadirlas después."),
        },
        "ejemplos": [
            ["1° Secundaria", "A;B;C", "Matemática;Comunicación;Ciencia y Tecnología;Inglés;Educación Física"],
            ["2° Secundaria", "A;B", "Matemática;Comunicación;Ciencia y Tecnología;Inglés;Arte y Cultura"],
        ],
        "errores": [
            "Escribir el mismo grado de dos formas («1° Secundaria» y «1ro secundaria»): se crean como grados distintos.",
            "Separar con coma las materias (usa punto y coma; la coma sirve solo para las secciones).",
            "Dos grados cuyo nombre junto con la sección da el mismo aula: el sistema avisa del choque y no guarda nada.",
            "Repetir una fila ya cargada no duplica nada: lo que ya existe se omite. Para quitar una materia o un aula usa «Aulas y materias».",
        ],
    },
}

_PASOS = (
    "Llena la hoja «Datos» a partir de la fila 2. No cambies ni borres la fila de encabezados.",
    "Las columnas en azul oscuro son obligatorias; las de azul claro son opcionales.",
    "No agregues columnas con otros nombres (se ignoran) ni dejes filas a medias.",
    "Guarda el archivo como .xlsx (sin macros) y súbelo en la pestaña «Carga masiva» (las aulas y materias, en «Aulas y materias»).",
    "Pulsa «Validar archivo»: el sistema indica la fila y el campo de cada error y NO guarda nada si hay errores.",
    "Corrige y vuelve a validar. Cuando salga «Archivo válido», confirma la importación.",
    "Importante: solo se lee la hoja «Datos». Esta hoja de instrucciones no se importa.",
)


def _encabezado(celda, obligatoria: bool) -> None:
    celda.font = Font(bold=True, color="FFFFFF" if obligatoria else _AZUL)
    celda.fill = PatternFill("solid", fgColor=_AZUL if obligatoria else _AZUL_CLARO)
    celda.alignment = Alignment(horizontal="center", vertical="center")
    celda.border = _BORDE


def _hoja_datos(libro, tipo: str, columnas: list[str]) -> None:
    ws = libro.active
    ws.title = HOJA_DATOS
    espec = ESPECIFICACION[tipo]["columnas"]
    for indice, nombre in enumerate(columnas, start=1):
        _encabezado(ws.cell(row=1, column=indice, value=nombre), espec[nombre][0])
        ws.column_dimensions[get_column_letter(indice)].width = max(18, len(nombre) + 6)
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"

    ultima = FILAS_FORMATEADAS + 1
    for indice, nombre in enumerate(columnas, start=1):
        formato = {"fecha": "yyyy-mm-dd", "nota_obtenida": "0.0#"}.get(nombre, "@")  # @ = Texto (conserva ceros)
        for fila in range(2, ultima + 1):
            ws.cell(row=fila, column=indice).number_format = formato

    letra = {nombre: get_column_letter(i) for i, nombre in enumerate(columnas, start=1)}
    if "estado_asistencia" in letra:
        validacion = DataValidation(
            type="list", formula1='"presente,tardanza,falta,justificada"', allow_blank=True,
            errorTitle="Estado no válido", error="Elige presente, tardanza, falta o justificada.",
            promptTitle="Estado", prompt="Elige de la lista.",
        )
        validacion.add(f"{letra['estado_asistencia']}2:{letra['estado_asistencia']}{ultima}")
        ws.add_data_validation(validacion)
    if "nota_obtenida" in letra:
        validacion = DataValidation(
            type="decimal", operator="between", formula1="0", formula2="20", allow_blank=True,
            errorTitle="Nota no válida", error="La nota debe ser un número de 0 a 20.",
        )
        validacion.add(f"{letra['nota_obtenida']}2:{letra['nota_obtenida']}{ultima}")
        ws.add_data_validation(validacion)


def _hoja_instrucciones(libro, tipo: str, columnas: list[str]) -> None:
    ws = libro.create_sheet(HOJA_INSTRUCCIONES)
    espec = ESPECIFICACION[tipo]
    ajuste = Alignment(wrap_text=True, vertical="top")
    ws["A1"] = espec["titulo"]
    ws["A1"].font = Font(bold=True, size=16, color=_AZUL)

    fila = 3
    ws.cell(row=fila, column=1, value="Cómo usar esta plantilla").font = Font(bold=True, size=12)
    for numero, paso in enumerate(_PASOS, start=1):
        fila += 1
        ws.cell(row=fila, column=1, value=f"{numero}. {paso}").alignment = Alignment(wrap_text=False)

    fila += 2
    ws.cell(row=fila, column=1, value="Columnas").font = Font(bold=True, size=12)
    fila += 1
    for indice, titulo in enumerate(("Columna", "¿Obligatoria?", "Formato", "Ejemplo", "Notas"), start=1):
        _encabezado(ws.cell(row=fila, column=indice, value=titulo), True)
    for nombre in columnas:
        obligatoria, formato, ejemplo, nota = espec["columnas"][nombre]
        fila += 1
        for indice, valor in enumerate((nombre, "Sí" if obligatoria else "No", formato, ejemplo, nota), start=1):
            celda = ws.cell(row=fila, column=indice, value=valor)
            celda.alignment, celda.border = ajuste, _BORDE
            if indice == 4:
                celda.number_format = "@"

    fila += 2
    ws.cell(row=fila, column=1, value="Ejemplo de cómo se ven las filas (cópialas a la hoja «Datos» solo si quieres probar)").font = Font(bold=True, size=12)
    fila += 1
    for indice, nombre in enumerate(columnas, start=1):
        _encabezado(ws.cell(row=fila, column=indice, value=nombre), espec["columnas"][nombre][0])
    for ejemplo in espec["ejemplos"]:
        fila += 1
        for indice, valor in enumerate(ejemplo, start=1):
            celda = ws.cell(row=fila, column=indice, value=valor)
            celda.number_format, celda.border = "@", _BORDE

    fila += 2
    ws.cell(row=fila, column=1, value="Errores frecuentes").font = Font(bold=True, size=12)
    for error in espec["errores"]:
        fila += 1
        ws.cell(row=fila, column=1, value=f"• {error}")

    for letra, ancho in zip("ABCDE", (22, 15, 46, 20, 60)):
        ws.column_dimensions[letra].width = ancho
    ws.sheet_view.showGridLines = False


def crear_plantilla_xlsx(tipo: str) -> bytes:
    """Devuelve el contenido del .xlsx de la plantilla de `tipo` (estudiantes, calificaciones, asistencias o aulas)."""
    if tipo not in importacion.TIPOS:
        raise ValueError(f"Tipo de plantilla no válido: {tipo}")
    columnas = list(importacion.COLUMNAS[tipo]["obligatorias"] + importacion.COLUMNAS[tipo]["opcionales"])
    libro = Workbook()
    _hoja_datos(libro, tipo, columnas)  # primera hoja: la que se importa
    _hoja_instrucciones(libro, tipo, columnas)
    libro.active = 0
    buffer = BytesIO()
    libro.save(buffer)
    return buffer.getvalue()
