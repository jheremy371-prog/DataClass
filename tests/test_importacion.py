"""Pruebas de la carga masiva (api/importacion.py). Funcionan con unittest y con pytest, sin FastAPI."""
import gc
import io
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from openpyxl import Workbook

import api.database as database
from api import importacion as imp

HOY = date(2026, 10, 23)
DIRECTIVO = {"rol": "directivo", "aula": None}
DOCENTE_A = {"rol": "docente", "aula": "A-1"}


def csv_bytes(texto: str) -> bytes:
    return texto.encode("utf-8")


def leer(texto: str, tipo: str, nombre="datos.csv"):
    return imp.leer_tabla(csv_bytes(texto), nombre, tipo)[1]


class BaseBD(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_original = database.DB_PATH
        database.DB_PATH = Path(self._tmp.name) / "importacion.db"
        database.inicializar_esquema()
        self.con = database.obtener_conexion()

    def tearDown(self):
        self.con.close()
        database.DB_PATH = self._db_original
        gc.collect()  # suelta cualquier conexión pendiente antes de borrar el archivo (Windows)
        self._tmp.cleanup()

    def estudiante(self, id_e, aula="A-1", dni=None, nombre=None):
        self.con.execute(
            "INSERT INTO estudiantes (id_estudiante, dni, nombre_completo, aula) VALUES (?, ?, ?, ?)",
            (id_e, dni, nombre or f"Alumno {id_e}", aula),
        )
        self.con.commit()

    def contar(self, tabla):
        return self.con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


class PruebasLectura(unittest.TestCase):
    def test_csv_con_punto_y_coma_alias_y_tildes_en_encabezado(self):
        ignoradas, filas = imp.leer_tabla(
            csv_bytes("Código;Nombre;DNI;Observación\nE1;Ana Pérez;12345678;nada\n"), "x.csv", "estudiantes")
        self.assertEqual(ignoradas, ["Observación"])
        self.assertEqual(filas, [(2, {"id_estudiante": "E1", "nombre_completo": "Ana Pérez", "dni": "12345678"})])

    def test_csv_cp1252_de_excel(self):
        contenido = "id;nombre\nE1;José Núñez\n".encode("cp1252")
        _, filas = imp.leer_tabla(contenido, "x.csv", "estudiantes")
        self.assertEqual(filas[0][1]["nombre_completo"], "José Núñez")

    def test_faltan_columnas_obligatorias(self):
        with self.assertRaises(imp.ErrorArchivo) as ctx:
            leer("id_estudiante,fecha\nE1,2026-10-01\n", "asistencias")
        self.assertIn("estado_asistencia", str(ctx.exception))

    def test_columna_repetida(self):
        with self.assertRaises(imp.ErrorArchivo):
            leer("id,codigo,nombre\nE1,E1,Ana\n", "estudiantes")

    def test_extension_no_admitida_vacio_y_solo_encabezado(self):
        with self.assertRaises(imp.ErrorArchivo):
            imp.leer_tabla(b"abc", "datos.xls", "estudiantes")
        with self.assertRaises(imp.ErrorArchivo):
            imp.leer_tabla(b"", "datos.csv", "estudiantes")
        with self.assertRaises(imp.ErrorArchivo):
            leer("id,nombre\n", "estudiantes")

    def test_demasiadas_filas(self):
        original = imp.MAX_FILAS
        imp.MAX_FILAS = 3
        try:
            with self.assertRaises(imp.ErrorArchivo):
                leer("id,nombre\n" + "".join(f"E{i},Ana\n" for i in range(4)), "estudiantes")
        finally:
            imp.MAX_FILAS = original

    def test_excel_numeros_y_fechas(self):
        libro = Workbook()
        hoja = libro.active
        hoja.append(["id_estudiante", "fecha", "estado"])
        hoja.append([101, date(2026, 10, 1), "P"])
        buffer = io.BytesIO()
        libro.save(buffer)
        _, filas = imp.leer_tabla(buffer.getvalue(), "a.xlsx", "asistencias")
        self.assertEqual(filas[0][1], {"id_estudiante": "101", "fecha": "2026-10-01", "estado_asistencia": "P"})

    def test_excel_corrupto(self):
        with self.assertRaises(imp.ErrorArchivo):
            imp.leer_tabla(b"no soy un zip", "a.xlsx", "asistencias")

    def test_excel_con_macros_rechazado(self):
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("xl/vbaProject.bin", b"x")
        with self.assertRaises(imp.ErrorArchivo):
            imp.leer_tabla(buffer.getvalue(), "a.xlsx", "asistencias")


class PruebasEstudiantes(BaseBD):
    def test_simulacion_no_escribe(self):
        filas = leer("id_estudiante,nombre_completo,dni,aula\nE1,Ana Pérez,12345678,A-1\n", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO, simular=True)
        self.assertEqual((informe["nuevas"], informe["aplicado"]), (1, False))
        self.assertEqual(self.contar("estudiantes"), 0)

    def test_importa_y_es_idempotente(self):
        filas = leer("id_estudiante,nombre_completo,dni,aula\nE1,Ana Pérez,12345678,A-1\nE2,Luis Soto,,A-1\n", "estudiantes")
        primero = imp.importar(self.con, "estudiantes", filas, DIRECTIVO, simular=False)
        self.assertEqual((primero["nuevas"], primero["aplicado"]), (2, True))
        segundo = imp.importar(self.con, "estudiantes", filas, DIRECTIVO, simular=False)
        self.assertEqual((segundo["nuevas"], segundo["ya_existentes"], segundo["aplicado"]), (0, 2, False))
        self.assertEqual(self.contar("estudiantes"), 2)

    def test_todo_o_nada_si_hay_un_error(self):
        filas = leer("id_estudiante,nombre_completo,dni\nE1,Ana,12345678\nE2,Luis,1234\n", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO, simular=False)
        self.assertFalse(informe["aplicado"])
        self.assertEqual(informe["errores"][0]["fila"], 3)
        self.assertEqual(informe["errores"][0]["campo"], "dni")
        self.assertEqual(self.contar("estudiantes"), 0)

    def test_dni_de_siete_digitos_sugiere_formato_texto(self):
        filas = leer("id_estudiante,nombre_completo,dni\nE1,Ana,1234567\n", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO)
        self.assertIn("formato Texto", informe["errores"][0]["motivo"])

    def test_no_sobrescribe_datos_distintos_ni_dni_ajeno(self):
        self.estudiante("E1", dni="11111111", nombre="Ana Pérez")
        filas = leer("id_estudiante,nombre_completo\nE1,Otra Persona\n", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO, simular=False)
        self.assertIn("distintos", informe["errores"][0]["motivo"])
        filas = leer("id_estudiante,nombre_completo,dni\nE9,Nuevo Alumno,11111111\n", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO, simular=False)
        self.assertIn("otro estudiante", informe["errores"][0]["motivo"])

    def test_duplicados_dentro_del_archivo(self):
        filas = leer("id_estudiante,nombre_completo,dni\nE1,Ana,12345678\nE1,Ana,\nE2,Luis,12345678\n", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO)
        motivos = [e["motivo"] for e in informe["errores"]]
        self.assertTrue(any("ID repetido" in m for m in motivos))
        self.assertTrue(any("DNI repetido" in m for m in motivos))

    def test_formula_en_aula_rechazada(self):
        filas = leer("id_estudiante,nombre_completo,aula\nE1,Ana,=1+1\n", "estudiantes")
        informe = imp.importar(self.con, "estudiantes", filas, DIRECTIVO)
        self.assertEqual(informe["errores"][0]["campo"], "aula")

    def test_docente_no_puede_importar_estudiantes(self):
        filas = leer("id_estudiante,nombre_completo\nE1,Ana\n", "estudiantes")
        with self.assertRaises(PermissionError):
            imp.importar(self.con, "estudiantes", filas, DOCENTE_A, simular=False)


class PruebasCalificaciones(BaseBD):
    ENCABEZADO = "id_estudiante,curso,nota,periodo\n"

    def test_importa_con_coma_decimal_y_es_idempotente(self):
        self.estudiante("E1")
        filas = leer(self.ENCABEZADO + 'E1,Matemática,"14,5",Bimestre 1\nE1,Matemática,16,Bimestre 1\n', "calificaciones")
        primero = imp.importar(self.con, "calificaciones", filas, DIRECTIVO, simular=False)
        self.assertEqual((primero["nuevas"], primero["aplicado"], primero["_afectados"]), (2, True, ["E1"]))
        segundo = imp.importar(self.con, "calificaciones", filas, DIRECTIVO, simular=False)
        self.assertEqual((segundo["nuevas"], segundo["ya_existentes"]), (0, 2))
        self.assertEqual(self.contar("calificaciones"), 2)

    def test_nota_fuera_de_rango_y_estudiante_inexistente(self):
        self.estudiante("E1")
        filas = leer(self.ENCABEZADO + "E1,Mate,25,B1\nXX,Mate,10,B1\nE1,Mate,abc,B1\n", "calificaciones")
        informe = imp.importar(self.con, "calificaciones", filas, DIRECTIVO, simular=False)
        self.assertEqual({(e["fila"], e["campo"]) for e in informe["errores"]},
                         {(2, "nota_obtenida"), (3, "id_estudiante"), (4, "nota_obtenida")})
        self.assertEqual(self.contar("calificaciones"), 0)

    def test_unifica_curso_con_distinta_grafia(self):
        self.estudiante("E1")
        self.con.execute("INSERT INTO calificaciones (id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion) "
                         "VALUES ('E1', 'Matemática', 12, 'B1')")
        self.con.commit()
        filas = leer(self.ENCABEZADO + "E1,  matematica ,15,B2\n", "calificaciones")
        informe = imp.importar(self.con, "calificaciones", filas, DIRECTIVO, simular=False)
        self.assertEqual(informe["advertencias_total"], 1)
        cursos = {f[0] for f in self.con.execute("SELECT DISTINCT curso_modulo FROM calificaciones")}
        self.assertEqual(cursos, {"Matemática"})

    def test_fila_repetida_en_el_archivo_es_error(self):
        self.estudiante("E1")
        filas = leer(self.ENCABEZADO + "E1,Mate,15,B1\nE1,Mate,15,B1\n", "calificaciones")
        informe = imp.importar(self.con, "calificaciones", filas, DIRECTIVO)
        self.assertIn("repetida", informe["errores"][0]["motivo"])

    def test_docente_solo_ve_su_aula_y_no_revela_si_existe(self):
        self.estudiante("A1", aula="A-1")
        self.estudiante("B1", aula="B-1")
        filas = leer(self.ENCABEZADO + "A1,Mate,15,B1\nB1,Mate,15,B1\nNOEXISTE,Mate,15,B1\n", "calificaciones")
        informe = imp.importar(self.con, "calificaciones", filas, DOCENTE_A, simular=False)
        self.assertFalse(informe["aplicado"])
        motivos = {e["fila"]: e["motivo"] for e in informe["errores"]}
        self.assertEqual(motivos[3], motivos[4])  # misma respuesta: otra aula o inexistente
        self.assertNotIn(2, motivos)

    def test_docente_sin_aula_no_importa_nada(self):
        self.estudiante("A1", aula="A-1")
        filas = leer(self.ENCABEZADO + "A1,Mate,15,B1\n", "calificaciones")
        informe = imp.importar(self.con, "calificaciones", filas, {"rol": "docente", "aula": None})
        self.assertEqual(informe["errores_total"], 1)

    def test_muchos_estudiantes_supera_limite_de_variables_sql(self):
        for i in range(1100):
            self.con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo, aula) VALUES (?, ?, 'A-1')",
                             (f"E{i}", f"Alumno {i}"))
        self.con.commit()
        filas = leer(self.ENCABEZADO + "".join(f"E{i},Mate,15,B1\n" for i in range(1100)), "calificaciones")
        informe = imp.importar(self.con, "calificaciones", filas, DIRECTIVO, simular=False)
        self.assertEqual((informe["nuevas"], informe["aplicado"]), (1100, True))
        segundo = imp.importar(self.con, "calificaciones", filas, DIRECTIVO, simular=False)
        self.assertEqual(segundo["ya_existentes"], 1100)


class PruebasAsistencias(BaseBD):
    ENCABEZADO = "id_estudiante,fecha,estado\n"

    def test_importa_acepta_formatos_de_fecha_e_iniciales(self):
        self.estudiante("E1")
        filas = leer(self.ENCABEZADO + "E1,2026-10-01,P\nE1,02/10/2026,falta\n", "asistencias")
        informe = imp.importar(self.con, "asistencias", filas, DIRECTIVO, simular=False, hoy=HOY)
        self.assertEqual((informe["nuevas"], informe["aplicado"]), (2, True))
        estados = dict(self.con.execute("SELECT fecha, estado_asistencia FROM asistencias").fetchall())
        self.assertEqual(estados, {"2026-10-01": "presente", "2026-10-02": "falta"})

    def test_fecha_futura_y_estado_invalido(self):
        self.estudiante("E1")
        filas = leer(self.ENCABEZADO + "E1,2026-12-01,P\nE1,2026-10-01,quizas\nE1,31/02/2026,P\n", "asistencias")
        informe = imp.importar(self.con, "asistencias", filas, DIRECTIVO, hoy=HOY)
        self.assertEqual({(e["fila"], e["campo"]) for e in informe["errores"]},
                         {(2, "fecha"), (3, "estado_asistencia"), (4, "fecha")})

    def test_conflicto_con_estado_existente_no_se_sobrescribe(self):
        self.estudiante("E1")
        self.con.execute("INSERT INTO asistencias (id_estudiante, fecha, estado_asistencia) VALUES ('E1', '2026-10-01', 'falta')")
        self.con.commit()
        filas = leer(self.ENCABEZADO + "E1,2026-10-01,presente\n", "asistencias")
        informe = imp.importar(self.con, "asistencias", filas, DIRECTIVO, simular=False, hoy=HOY)
        self.assertIn("falta", informe["errores"][0]["motivo"])
        self.assertEqual(self.con.execute("SELECT estado_asistencia FROM asistencias").fetchone()[0], "falta")

    def test_reenviar_el_mismo_archivo_no_duplica(self):
        self.estudiante("E1")
        filas = leer(self.ENCABEZADO + "E1,2026-10-01,presente\n", "asistencias")
        imp.importar(self.con, "asistencias", filas, DIRECTIVO, simular=False, hoy=HOY)
        informe = imp.importar(self.con, "asistencias", filas, DIRECTIVO, simular=False, hoy=HOY)
        self.assertEqual((informe["ya_existentes"], informe["nuevas"]), (1, 0))
        self.assertEqual(self.contar("asistencias"), 1)

    def test_limite_de_errores_en_el_informe(self):
        self.estudiante("E1")
        filas = leer(self.ENCABEZADO + "".join("E1,2026-10-01,zzz\n" for _ in range(300)), "asistencias")
        informe = imp.importar(self.con, "asistencias", filas, DIRECTIVO, hoy=HOY)
        self.assertEqual(informe["errores_total"], 300)
        self.assertEqual(len(informe["errores"]), imp.MAX_ERRORES_INFORME)


if __name__ == "__main__":
    unittest.main()
