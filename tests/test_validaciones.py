"""Pruebas de las reglas de validación (DNI, teléfono, nombre, ID). Funcionan con unittest y con pytest."""
import unittest

from api import validaciones as v


class PruebasDNI(unittest.TestCase):
    def test_acepta_ocho_digitos(self):
        self.assertEqual(v.normalizar_dni("12345678"), "12345678")
        self.assertEqual(v.normalizar_dni("00000001"), "00000001")  # conserva ceros iniciales
        self.assertEqual(v.normalizar_dni("  76543210  "), "76543210")  # recorta espacios de los bordes

    def test_vacio_es_sin_dni(self):
        for valor in (None, "", "   "):
            self.assertIsNone(v.normalizar_dni(valor))

    def test_rechaza_letras_y_simbolos(self):
        for malo in ("abcdefgh", "1234567a", "a2345678", "12-45678", "12.45678", "1234 678", "12345678\n9",
                     "1234567", "123456789", "123456789012", "'; DROP TABLE x;--", "<script>", "1234567%"):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_dni(malo)

    def test_rechaza_digitos_unicode(self):
        # str.isdigit() y \\d los aceptan; aquí no deben pasar.
        for malo in ("١٢٣٤٥٦٧٨", "１２３４５６７８", "1234567²"):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_dni(malo)

    def test_rechaza_numeros_json(self):
        for malo in (12345678, 1234567.0, True, ["12345678"]):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_dni(malo)

    def test_limpieza_del_campo(self):
        self.assertEqual(v.solo_digitos_ascii("12a3-4 5٣6"), "123456")
        self.assertEqual(v.solo_digitos_ascii("abc"), "")
        self.assertEqual(v.solo_digitos_ascii(None), "")


class PruebasTelefono(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(v.normalizar_telefono("987654321"), "987654321")
        self.assertEqual(v.normalizar_telefono("+51 987-654-321"), "+51987654321")
        self.assertEqual(v.normalizar_telefono("(01) 456 7890"), "014567890")
        self.assertIsNone(v.normalizar_telefono(""))
        self.assertIsNone(v.normalizar_telefono(None))

    def test_invalidos(self):
        for malo in ("abc", "98765", "9876543210123456", "98765432a", "++51987654321", "987+654321", 987654321):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_telefono(malo)


class PruebasNombre(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(v.normalizar_nombre("  María   José  Núñez "), "María José Núñez")
        self.assertEqual(v.normalizar_nombre("O'Brien-Pérez Jr."), "O'Brien-Pérez Jr.")
        self.assertEqual(v.normalizar_nombre("Carlos Mendoza"), "Carlos Mendoza")
        self.assertEqual(v.normalizar_nombre("Ana\nLuz"), "Ana Luz")  # saltos de línea se normalizan a espacio

    def test_invalidos(self):
        for malo in ("", " ", "A", " a ", "Juan123", "<b>Juan</b>", "Ana\x00Luz", "Pedro;--", 123, None):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_nombre(malo)


class PruebasIdInstitucional(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(v.normalizar_id_institucional(" EST-001 "), "EST-001")
        self.assertEqual(v.normalizar_id_institucional("a1"), "a1")

    def test_invalidos(self):
        for malo in ("", "   ", "-EST", "EST 001", "EST/001", "EST'001", "A" * 51, "../etc", None):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_id_institucional(malo)


class PruebasNombreYCorreoEstrictos(unittest.TestCase):
    def test_el_nombre_debe_empezar_con_una_letra(self):
        for malo in ("-Ana", ".Ana", "'Ana", "--", "..", "- -", "'’"):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_nombre(malo)
        self.assertEqual(v.normalizar_nombre("D'Angelo-Paz"), "D'Angelo-Paz")  # signos permitidos dentro del nombre

    def test_correo_valido_se_normaliza(self):
        self.assertEqual(v.normalizar_correo("  Docente.A@Colegio.EDU.pe "), "docente.a@colegio.edu.pe")
        self.assertEqual(v.normalizar_correo("admin@test.edu"), "admin@test.edu")

    def test_correo_invalido_se_rechaza(self):
        for malo in ("", "sin-arroba", "@dominio.edu", "usuario@", "usuario@dominio", "usuario@.edu", "usuario@dominio.",
                     "a b@dominio.edu", "a@b@dominio.edu", "usuario@dominio..edu", "usuario@domi\nnio.edu", "x" * 180 + "@a.edu"):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    v.normalizar_correo(malo)
        with self.assertRaises(ValueError):
            v.normalizar_correo(None)


if __name__ == "__main__":
    unittest.main()


def test_primera_ip_valida_toma_la_primera_direccion_de_x_forwarded_for():
    from api.validaciones import primera_ip_valida

    assert primera_ip_valida("203.0.113.5") == "203.0.113.5"
    assert primera_ip_valida(" 203.0.113.5 , 10.0.0.1") == "203.0.113.5"
    assert primera_ip_valida("2001:db8::1") == "2001:db8::1"


def test_primera_ip_valida_rechaza_basura():
    from api.validaciones import primera_ip_valida

    for malo in (None, "", "   ", "no-es-ip", "999.1.1.1", "1.2.3.4; DROP TABLE", ", 1.2.3.4", 123):
        assert primera_ip_valida(malo) is None


def test_normalizar_aula_unifica_mayusculas_y_espacios():
    from api.validaciones import normalizar_aula

    assert normalizar_aula("a-302") == "A-302"
    assert normalizar_aula("  A-302 ") == "A-302"
    assert normalizar_aula("3ro   b") == "3RO B"
    assert normalizar_aula("Ａ-３０２") == "A-302"  # caracteres de ancho completo (NFKC)
    assert normalizar_aula("") is None and normalizar_aula("   ") is None and normalizar_aula(None) is None


def test_normalizar_aula_rechaza_formulas_y_texto_largo():
    import pytest
    from api.validaciones import normalizar_aula

    for malo in ("=1+1", "+cmd", "-2", "@SUM(A1)", "A" * 51, 123):
        with pytest.raises(ValueError):
            normalizar_aula(malo)


def test_clave_curso_ignora_tildes_mayusculas_y_signos():
    from api.validaciones import clave_curso

    assert clave_curso("Matemática") == clave_curso(" matematica ") == clave_curso("MATEMÁTICA.")
    assert clave_curso("Matemática I") != clave_curso("Matemática II")
