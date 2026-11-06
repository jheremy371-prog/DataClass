"""Esquema SQLite (pragmas, versión, contador de IDs, tokens revocados) e integridad del modelo (M-03, M-04, N-05)."""
import gc
import json
import tempfile
import unittest
from pathlib import Path

import api.database as database
from api import catalogo, riesgo


class BaseBD(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_original = database.DB_PATH
        database.DB_PATH = Path(self._tmp.name) / "esquema.db"
        database.inicializar_esquema()
        self.con = database.obtener_conexion()

    def tearDown(self):
        self.con.close()
        database.DB_PATH = self._db_original
        gc.collect()
        self._tmp.cleanup()

    def alta(self, id_estudiante):
        self.con.execute("INSERT INTO estudiantes (id_estudiante, nombre_completo) VALUES (?, ?)", (id_estudiante, "Nombre Prueba"))
        self.con.commit()


class PruebasPragmasYVersion(BaseBD):
    def test_pragmas_de_la_conexion(self):
        self.assertEqual(self.con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.con.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
        self.assertEqual(self.con.execute("PRAGMA synchronous").fetchone()[0], 1)  # NORMAL
        self.assertEqual(self.con.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_la_version_del_esquema_queda_registrada(self):
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone()[0], database.ESQUEMA_VERSION)

    def test_inicializar_dos_veces_no_falla_ni_cambia_nada(self):
        self.alta("2026-0001")
        database.inicializar_esquema()
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM estudiantes").fetchone()[0], 1)
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone()[0], database.ESQUEMA_VERSION)

    def test_una_base_mas_nueva_que_el_programa_se_rechaza(self):
        self.con.execute(f"PRAGMA user_version = {database.ESQUEMA_VERSION + 1}")
        self.con.commit()
        with self.assertRaises(RuntimeError) as contexto:
            database.inicializar_esquema()
        self.assertIn("Actualiza DataClass", str(contexto.exception))

    def test_una_base_antigua_sin_version_se_migra(self):
        self.alta("2026-0007")
        self.con.execute("DELETE FROM secuencias")
        self.con.execute("PRAGMA user_version = 0")
        self.con.commit()
        database.inicializar_esquema()
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone()[0], database.ESQUEMA_VERSION)
        self.assertEqual(self.con.execute("SELECT valor FROM secuencias WHERE nombre = '2026'").fetchone()[0], 7)

    def test_existen_las_tablas_de_sesion_y_secuencias(self):
        tablas = {f[0] for f in self.con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertLessEqual({"tokens_revocados", "secuencias"}, tablas)


class PruebasContadorDeIds(BaseBD):
    def test_borrar_el_ultimo_no_libera_su_numero(self):
        for numero in (1, 2, 3):
            self.alta(f"2026-{numero:04d}")
        self.con.execute("DELETE FROM estudiantes WHERE id_estudiante = '2026-0003'")
        self.con.commit()
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, anio=2026), "2026-0004")

    def test_vaciar_toda_la_tabla_tampoco_reinicia_el_contador(self):
        self.alta("2026-0005")
        self.con.execute("DELETE FROM estudiantes")
        self.con.commit()
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, anio=2026), "2026-0006")

    def test_un_id_manual_mayor_adelanta_el_contador(self):
        self.alta("2026-0020")
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, anio=2026), "2026-0021")

    def test_cada_anio_lleva_su_propia_cuenta(self):
        self.alta("2026-0004")
        self.alta("2027-0001")
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, anio=2026), "2026-0005")
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, anio=2027), "2027-0002")
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, anio=2028), "2028-0001")

    def test_los_ids_con_otro_formato_no_tocan_el_contador(self):
        for id_raro in ("EST-001", "2026-AB", "2026-", "20260001", "2026-00x1"):
            self.alta(id_raro)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM secuencias").fetchone()[0], 0)
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, anio=2026), "2026-0001")

    def test_los_reservados_siguen_contando(self):
        self.alta("2026-0002")
        self.assertEqual(catalogo.siguiente_id_estudiante(self.con, reservados=["2026-0009"], anio=2026), "2026-0010")


class PruebasIntegridadDelModelo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        base = Path(self._tmp.name)
        self.pkl, self.js = base / "modelo.pkl", base / "modelo.json"
        self.pkl.write_bytes(b"contenido de un modelo")

    def tearDown(self):
        self._tmp.cleanup()

    def sellar(self, **extra):
        self.js.write_text(json.dumps({"version_modelo": "x", "sha256_pkl": riesgo.huella_sha256(self.pkl), **extra}), encoding="utf-8")

    def test_con_la_huella_correcta_se_acepta(self):
        self.sellar()
        self.assertEqual(riesgo.verificar_integridad_modelo(self.pkl, self.js), (True, ""))

    def test_un_pkl_alterado_se_rechaza(self):
        self.sellar()
        self.pkl.write_bytes(b"contenido de un modelo MALICIOSO")
        correcto, motivo = riesgo.verificar_integridad_modelo(self.pkl, self.js)
        self.assertFalse(correcto)
        self.assertIn("no coincide", motivo)

    def test_sin_huella_en_el_json_se_rechaza(self):
        self.js.write_text(json.dumps({"version_modelo": "x"}), encoding="utf-8")
        correcto, motivo = riesgo.verificar_integridad_modelo(self.pkl, self.js)
        self.assertFalse(correcto)
        self.assertIn("sha256_pkl", motivo)

    def test_json_ausente_o_danado_se_rechaza(self):
        self.assertFalse(riesgo.verificar_integridad_modelo(self.pkl, self.js)[0])
        self.js.write_text("{no es json", encoding="utf-8")
        self.assertFalse(riesgo.verificar_integridad_modelo(self.pkl, self.js)[0])
        self.js.write_text("[]", encoding="utf-8")
        self.assertFalse(riesgo.verificar_integridad_modelo(self.pkl, self.js)[0])

    def test_pkl_ausente_se_rechaza(self):
        self.sellar()
        self.pkl.unlink()
        self.assertFalse(riesgo.verificar_integridad_modelo(self.pkl, self.js)[0])

    def test_la_huella_en_mayusculas_tambien_vale(self):
        self.js.write_text(json.dumps({"sha256_pkl": riesgo.huella_sha256(self.pkl).upper()}), encoding="utf-8")
        self.assertTrue(riesgo.verificar_integridad_modelo(self.pkl, self.js)[0])

    def test_el_modelo_incluido_en_el_repositorio_esta_sellado(self):
        base = Path(__file__).resolve().parent.parent / "modelos"
        self.assertEqual(riesgo.verificar_integridad_modelo(base / "modelo_riesgo.pkl", base / "modelo_riesgo.json"), (True, ""))


if __name__ == "__main__":
    unittest.main()
