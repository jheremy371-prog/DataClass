"""Pruebas del catálogo académico: IDs automáticos, aulas por grado, malla curricular y su carga masiva."""
import gc
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

import api.database as database
from api import catalogo
from api import importacion as imp
from api import plantillas

DIRECTIVO = {"rol": "directivo", "aula": None}
DOCENTE = {"rol": "docente", "aula": "1° SECUNDARIA A"}


def leer(texto, tipo):
    return imp.leer_tabla(texto.encode("utf-8"), "x.csv", tipo)[1]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_original = database.DB_PATH
        database.DB_PATH = Path(self._tmp.name) / "catalogo.db"
        database.inicializar_esquema()
        self.con = database.obtener_conexion()

    def tearDown(self):
        self.con.close()
        database.DB_PATH = self._db_original
        gc.collect()
        self._tmp.cleanup()

    def importar(self, tipo, texto, usuario=DIRECTIVO, simular=False):
        return imp.importar(self.con, tipo, leer(texto, tipo), usuario, simular=simular)


class PruebasIdAutomatico(Base):
    def test_primer_id_y_correlativo(self):
        anio = date.today().year
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con), f"{anio}-0001")
        self.con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo) VALUES (?, 'Ana')", (f"{anio}-0007",))
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con), f"{anio}-0008")

    def test_ignora_ids_propios_de_la_institucion_y_respeta_reservados(self):
        anio = date.today().year
        self.con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo) VALUES ('EST-050', 'Ana')")
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con), f"{anio}-0001")
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, reservados=[f"{anio}-0003"]), f"{anio}-0004")

    def test_importar_sin_id_genera_ids_distintos(self):
        informe = self.importar("estudiantes", "nombre_completo,dni\nAna Pérez,12345678\nLuis Soto,87654321\n")
        self.assertEqual((informe["nuevas"], informe["aplicado"], informe["errores_total"]), (2, True, 0))
        ids = [f[0] for f in self.con.execute("SELECT id_estudiante FROM estudiantes ORDER BY id_estudiante")]
        anio = date.today().year
        self.assertEqual(ids, [f"{anio}-0001", f"{anio}-0002"])

    def test_id_automatico_no_choca_con_id_escrito_mas_abajo_en_el_archivo(self):
        anio = date.today().year
        informe = self.importar("estudiantes", f"nombre_completo,id_estudiante,dni\nAna Pérez,,12345678\nLuis Soto,{anio}-0001,87654321\n")
        self.assertEqual((informe["aplicado"], informe["errores_total"]), (True, 0))
        filas = dict(self.con.execute("SELECT nombre_completo, id_estudiante FROM estudiantes").fetchall())
        self.assertEqual(filas["Luis Soto"], f"{anio}-0001")
        self.assertEqual(filas["Ana Pérez"], f"{anio}-0002")

    def test_volver_a_subir_el_archivo_con_dni_no_duplica(self):
        archivo = "nombre_completo,dni,aula\nAna Pérez,12345678,A-1\n"
        self.importar("estudiantes", archivo)
        informe = self.importar("estudiantes", archivo)
        self.assertEqual((informe["nuevas"], informe["ya_existentes"], informe["errores_total"]), (0, 1, 0))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM estudiantes").fetchone()[0], 1)

    def test_sin_id_ni_dni_avisa_del_riesgo_de_duplicados(self):
        informe = self.importar("estudiantes", "nombre_completo\nAna Pérez\n")
        self.assertEqual(informe["advertencias_total"], 1)


class PruebasAulasYMallas(Base):
    ARCHIVO = (
        "grado,secciones,materias\n"
        '1° Secundaria,"A;B","Matemática;Comunicación"\n'
        '2° Secundaria,C,Matemática\n'
    )

    def test_importa_aulas_y_malla(self):
        informe = self.importar("aulas", self.ARCHIVO)
        self.assertEqual((informe["aplicado"], informe["errores_total"]), (True, 0))
        self.assertEqual(informe["nuevas"], 3 + 3)  # 3 aulas + 3 materias de malla
        aulas = {a["nombre"]: a for a in catalogo.listar_aulas(self.con)}
        self.assertEqual(set(aulas), {"1° SECUNDARIA A", "1° SECUNDARIA B", "2° SECUNDARIA C"})
        self.assertEqual(aulas["1° SECUNDARIA B"]["materias"], ["Comunicación", "Matemática"])  # la malla es del grado
        self.assertEqual(aulas["2° SECUNDARIA C"]["materias"], ["Matemática"])

    def test_es_idempotente(self):
        self.importar("aulas", self.ARCHIVO)
        informe = self.importar("aulas", self.ARCHIVO)
        self.assertEqual((informe["nuevas"], informe["errores_total"]), (0, 0))
        self.assertGreater(informe["ya_existentes"], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM aulas").fetchone()[0], 3)

    def test_simulacion_no_guarda(self):
        informe = self.importar("aulas", self.ARCHIVO, simular=True)
        self.assertEqual((informe["nuevas"], informe["aplicado"]), (6, False))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM aulas").fetchone()[0], 0)

    def test_materia_se_unifica_con_la_grafia_existente(self):
        self.importar("aulas", "grado,secciones,materias\n1° Secundaria,A,Matemática\n")
        informe = self.importar("aulas", "grado,secciones,materias\n2° Secundaria,A,matematica\n")
        self.assertEqual(informe["advertencias_total"], 1)
        self.assertEqual(catalogo.materias_de_grado(self.con, "2° SECUNDARIA"), ["Matemática"])

    def test_choque_de_nombres_se_rechaza_sin_guardar(self):
        informe = self.importar("aulas", "grado,secciones\n1 A,B\n1,A B\n")
        self.assertGreater(informe["errores_total"], 0)
        self.assertFalse(informe["aplicado"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM aulas").fetchone()[0], 0)

    def test_errores_de_campos(self):
        informe = self.importar("aulas", "grado,secciones,materias\n,A,Matemática\n1° Secundaria,,Arte\n=1+1,A,\n")
        self.assertEqual({(e["fila"], e["campo"]) for e in informe["errores"]}, {(2, "grado"), (3, "secciones"), (4, "grado")})

    def test_un_docente_no_puede_importar_aulas(self):
        with self.assertRaises(PermissionError):
            self.importar("aulas", self.ARCHIVO, usuario=DOCENTE)

    def test_aula_inexistente_se_rechaza_cuando_ya_hay_catalogo(self):
        self.importar("aulas", self.ARCHIVO)
        informe = self.importar("estudiantes", "nombre_completo,dni,aula\nAna Pérez,12345678,9° INVENTADA\nLuis Soto,87654321,1° Secundaria A\n")
        self.assertEqual([(e["fila"], e["campo"]) for e in informe["errores"]], [(2, "aula")])
        self.assertFalse(informe["aplicado"])
        ok = self.importar("estudiantes", "nombre_completo,dni,aula\nLuis Soto,87654321,1° Secundaria A\n")
        self.assertTrue(ok["aplicado"])
        self.assertEqual(catalogo.listar_aulas(self.con, solo_aula="1° SECUNDARIA A")[0]["estudiantes"], 1)

    def test_sin_catalogo_el_aula_sigue_siendo_texto_libre(self):
        informe = self.importar("estudiantes", "nombre_completo,aula\nAna Pérez,A-302\n")
        self.assertTrue(informe["aplicado"])

    def test_crear_aulas_agregar_y_quitar_materias_y_borrar(self):
        creadas, existentes = catalogo.crear_aulas(self.con, "1° SECUNDARIA", ["A", "B"])
        self.assertEqual((creadas, existentes), (["1° SECUNDARIA A", "1° SECUNDARIA B"], []))
        self.assertEqual(catalogo.crear_aulas(self.con, "1° SECUNDARIA", ["A"]), ([], ["1° SECUNDARIA A"]))
        self.assertEqual(catalogo.agregar_materia(self.con, "1° SECUNDARIA", "Arte"), ("Arte", True))
        self.assertEqual(catalogo.agregar_materia(self.con, "1° SECUNDARIA", "arte"), ("Arte", False))
        self.con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo, aula) VALUES ('E1', 'Ana', '1° SECUNDARIA A')")
        self.assertEqual(catalogo.eliminar_aula(self.con, "1° SECUNDARIA A"), "con_estudiantes")
        self.assertEqual(catalogo.eliminar_aula(self.con, "1° SECUNDARIA B"), "ok")
        self.assertEqual(catalogo.eliminar_aula(self.con, "NO EXISTE"), "no_existe")
        self.assertTrue(catalogo.quitar_materia(self.con, "1° SECUNDARIA", "Arte"))
        self.assertFalse(catalogo.quitar_materia(self.con, "1° SECUNDARIA", "Arte"))

    def test_plantilla_de_aulas_llenada_se_importa(self):
        libro = plantillas.crear_plantilla_xlsx("aulas")
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(libro))
        self.assertEqual([c.value for c in wb["Datos"][1]], ["grado", "secciones", "materias"])
        ws = wb["Datos"]
        ws["A2"], ws["B2"], ws["C2"] = "3 años", "U", "Comunicación;Matemática"
        buffer = io.BytesIO()
        wb.save(buffer)
        _, filas = imp.leer_tabla(buffer.getvalue(), "p.xlsx", "aulas")
        informe = imp.importar(self.con, "aulas", filas, DIRECTIVO, simular=False)
        self.assertEqual((informe["aplicado"], informe["errores_total"], informe["nuevas"]), (True, 0, 3))


if __name__ == "__main__":
    unittest.main()
