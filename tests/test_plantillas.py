"""Pruebas de las plantillas de Excel: encabezados, formatos, validaciones y recorrido completo con el importador."""
import gc
import io
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

import api.database as database
from api import importacion as imp
from api import plantillas

DIRECTIVO = {"rol": "directivo", "aula": None}


def abrir(tipo):
    return load_workbook(io.BytesIO(plantillas.crear_plantilla_xlsx(tipo)))


class PruebasEstructura(unittest.TestCase):
    def test_hoja_datos_es_la_primera_y_los_encabezados_coinciden_con_el_importador(self):
        for tipo in imp.TIPOS:
            with self.subTest(tipo=tipo):
                libro = abrir(tipo)
                self.assertEqual(libro.sheetnames, ["Datos", "Instrucciones"])
                esperado = list(imp.COLUMNAS[tipo]["obligatorias"] + imp.COLUMNAS[tipo]["opcionales"])
                self.assertEqual([c.value for c in libro["Datos"][1]], esperado)

    def test_la_especificacion_cubre_todas_las_columnas_del_importador(self):
        for tipo in imp.TIPOS:
            columnas = set(imp.COLUMNAS[tipo]["obligatorias"] + imp.COLUMNAS[tipo]["opcionales"])
            self.assertEqual(set(plantillas.ESPECIFICACION[tipo]["columnas"]), columnas)
            for nombre in imp.COLUMNAS[tipo]["obligatorias"]:
                self.assertTrue(plantillas.ESPECIFICACION[tipo]["columnas"][nombre][0])

    def test_dni_e_ids_tienen_formato_texto(self):
        ws = abrir("estudiantes")["Datos"]
        for columna in "ABCDE":
            self.assertEqual(ws[f"{columna}2"].number_format, "@")
            self.assertEqual(ws[f"{columna}{imp.MAX_FILAS + 1}"].number_format, "@")

    def test_validaciones_de_estado_y_nota(self):
        ws = abrir("asistencias")["Datos"]
        validaciones = ws.data_validations.dataValidation
        self.assertEqual(len(validaciones), 1)
        self.assertEqual(validaciones[0].type, "list")
        self.assertIn("justificada", validaciones[0].formula1)
        ws = abrir("calificaciones")["Datos"]
        self.assertEqual(ws.data_validations.dataValidation[0].type, "decimal")

    def test_los_ejemplos_estan_solo_en_instrucciones(self):
        for tipo in imp.TIPOS:
            ws = abrir(tipo)["Datos"]
            self.assertTrue(all(c.value is None for c in ws[2]))
        textos = [str(c.value) for fila in abrir("estudiantes")["Instrucciones"].iter_rows() for c in fila if c.value]
        self.assertIn("Ana Pérez Rojas", textos)

    def test_tipo_invalido(self):
        with self.assertRaises(ValueError):
            plantillas.crear_plantilla_xlsx("otra_cosa")


class PruebasRecorridoCompleto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_original = database.DB_PATH
        database.DB_PATH = Path(self._tmp.name) / "plantillas.db"
        database.inicializar_esquema()
        self.con = database.obtener_conexion()

    def tearDown(self):
        self.con.close()
        database.DB_PATH = self._db_original
        gc.collect()
        self._tmp.cleanup()

    def llenar(self, tipo, filas):
        libro = abrir(tipo)
        ws = libro["Datos"]
        for numero, fila in enumerate(filas, start=2):
            for columna, valor in enumerate(fila, start=1):
                ws.cell(row=numero, column=columna, value=valor)
        buffer = io.BytesIO()
        libro.save(buffer)
        return buffer.getvalue()

    def test_plantilla_vacia_se_rechaza_con_mensaje_claro(self):
        with self.assertRaises(imp.ErrorArchivo) as ctx:
            imp.leer_tabla(plantillas.crear_plantilla_xlsx("estudiantes"), "p.xlsx", "estudiantes")
        self.assertIn("solo tiene la fila de encabezados", str(ctx.exception))

    def test_plantilla_llenada_se_importa_y_conserva_ceros_del_dni(self):
        contenido = self.llenar("estudiantes", [["Ana Pérez Rojas", "EST-001", "01234567", "A-101", "987654321"],
                                                ["Luis Soto Vega", "EST-002", None, "A-101", None]])
        _, filas = imp.leer_tabla(contenido, "p.xlsx", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO, simular=False)
        self.assertEqual((informe["nuevas"], informe["aplicado"], informe["errores_total"]), (2, True, 0))
        self.assertEqual(self.con.execute("SELECT dni FROM estudiantes WHERE id_estudiante='EST-001'").fetchone()[0], "01234567")

    def test_asistencias_y_calificaciones_desde_plantilla(self):
        self.con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo, aula) VALUES ('EST-001', 'Ana', 'A-101')")
        self.con.commit()
        from datetime import date

        contenido = self.llenar("asistencias", [["EST-001", date(2026, 10, 1), "presente"]])
        _, filas = imp.leer_tabla(contenido, "p.xlsx", "asistencias")
        informe = imp.importar(self.con, "asistencias", filas, DIRECTIVO, simular=False, hoy=date(2026, 10, 23))
        self.assertEqual((informe["nuevas"], informe["aplicado"]), (1, True))

        contenido = self.llenar("calificaciones", [["EST-001", "Matemática", 14.5, "2026-II"]])
        _, filas = imp.leer_tabla(contenido, "p.xlsx", "calificaciones")
        informe = imp.importar(self.con, "calificaciones", filas, DIRECTIVO, simular=False)
        self.assertEqual((informe["nuevas"], informe["aplicado"]), (1, True))

    def test_el_importador_lee_la_hoja_datos_aunque_no_sea_la_primera(self):
        libro = abrir("estudiantes")
        libro.move_sheet("Datos", offset=1)
        ws = libro["Datos"]
        ws["A2"], ws["B2"] = "Rosa Díaz", "EST-009"
        buffer = io.BytesIO()
        libro.save(buffer)
        self.assertEqual(libro.sheetnames[0], "Instrucciones")
        _, filas = imp.leer_tabla(buffer.getvalue(), "p.xlsx", "estudiantes")
        self.assertEqual(filas[0][1]["id_estudiante"], "EST-009")


if __name__ == "__main__":
    unittest.main()
