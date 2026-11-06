"""LimitadorIntentos con reloj simulado (sin esperas reales)."""
import pytest

from api.limitador import LimitadorIntentos


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def avanzar(self, segundos):
        self.t += segundos


@pytest.fixture
def reloj():
    return Reloj()


def limitador(reloj, **kw):
    return LimitadorIntentos(max_intentos=3, ventana=60, bloqueo=120, reloj=reloj, **kw)


def fallar(lim, clave, veces):
    for _ in range(veces):
        lim.registrar_fallo(clave)


def test_menos_fallos_que_el_maximo_no_bloquea(reloj):
    lim = limitador(reloj)
    fallar(lim, "a@x.edu", 2)
    assert lim.segundos_bloqueado("a@x.edu") == 0


def test_alcanzar_el_maximo_bloquea_y_cuenta_regresiva(reloj):
    lim = limitador(reloj)
    fallar(lim, "a@x.edu", 3)
    assert lim.segundos_bloqueado("a@x.edu") == 120
    reloj.avanzar(30.2)
    assert lim.segundos_bloqueado("a@x.edu") == 90  # 89.8 redondeado hacia arriba


def test_el_bloqueo_termina_y_empieza_de_cero(reloj):
    lim = limitador(reloj)
    fallar(lim, "a@x.edu", 3)
    reloj.avanzar(120)
    assert lim.segundos_bloqueado("a@x.edu") == 0
    fallar(lim, "a@x.edu", 2)  # los fallos anteriores no se arrastran
    assert lim.segundos_bloqueado("a@x.edu") == 0


def test_fallos_fuera_de_la_ventana_no_cuentan(reloj):
    lim = limitador(reloj)
    fallar(lim, "a@x.edu", 2)
    reloj.avanzar(61)
    lim.registrar_fallo("a@x.edu")
    assert lim.segundos_bloqueado("a@x.edu") == 0


def test_las_claves_son_independientes(reloj):
    lim = limitador(reloj)
    fallar(lim, "a@x.edu", 3)
    assert lim.segundos_bloqueado("a@x.edu") > 0
    assert lim.segundos_bloqueado("b@x.edu") == 0


def test_limpiar_quita_fallos_y_bloqueo(reloj):
    lim = limitador(reloj)
    fallar(lim, "a@x.edu", 2)
    lim.limpiar("a@x.edu")
    lim.registrar_fallo("a@x.edu")
    assert lim.segundos_bloqueado("a@x.edu") == 0
    fallar(lim, "a@x.edu", 2)
    assert lim.segundos_bloqueado("a@x.edu") > 0
    lim.limpiar("a@x.edu")
    assert lim.segundos_bloqueado("a@x.edu") == 0
    lim.limpiar("nunca-visto")  # no falla con claves desconocidas


def test_fallos_durante_el_bloqueo_no_lo_extienden(reloj):
    lim = limitador(reloj)
    fallar(lim, "a@x.edu", 3)
    reloj.avanzar(100)
    lim.registrar_fallo("a@x.edu")
    assert lim.segundos_bloqueado("a@x.edu") == 20


def test_la_memoria_no_crece_sin_limite(reloj):
    lim = LimitadorIntentos(max_intentos=3, ventana=60, bloqueo=120, reloj=reloj, max_claves=50)
    for i in range(200):
        lim.registrar_fallo(f"u{i}@x.edu")
        reloj.avanzar(61)  # cada fallo caduca antes del siguiente
    assert len(lim._fallos) + len(lim._bloqueado_hasta) <= 51


def test_maximo_invalido():
    with pytest.raises(ValueError):
        LimitadorIntentos(max_intentos=0)
