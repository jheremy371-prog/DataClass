"""Límite de intentos fallidos de inicio de sesión (en memoria, sin dependencias externas).

Tras `max_intentos` fallos dentro de `ventana` segundos, la clave (un correo o una IP) queda bloqueada durante
`bloqueo` segundos. Un inicio de sesión correcto borra los fallos del correo.

Límites: el estado vive en la memoria del proceso. Si ejecutas varios procesos (varios workers de uvicorn) cada uno
lleva su propia cuenta; para eso habría que guardar los contadores en la base de datos o en Redis.
"""
import math
import threading
import time
from collections import deque


class LimitadorIntentos:
    def __init__(self, max_intentos=5, ventana=300.0, bloqueo=300.0, reloj=time.monotonic, max_claves=10_000):
        if max_intentos < 1:
            raise ValueError("max_intentos debe ser al menos 1.")
        self.max_intentos = max_intentos
        self.ventana = float(ventana)
        self.bloqueo = float(bloqueo)
        self._reloj = reloj
        self._max_claves = max_claves
        self._fallos: dict[str, deque] = {}
        self._bloqueado_hasta: dict[str, float] = {}
        self._cerrojo = threading.Lock()

    def segundos_bloqueado(self, clave: str) -> int:
        """0 si puede intentar; si no, los segundos que faltan (redondeados hacia arriba)."""
        with self._cerrojo:
            hasta = self._bloqueado_hasta.get(clave)
            if hasta is None:
                return 0
            restante = hasta - self._reloj()
            if restante <= 0:
                del self._bloqueado_hasta[clave]
                return 0
            return math.ceil(restante)

    def registrar_fallo(self, clave: str) -> None:
        with self._cerrojo:
            ahora = self._reloj()
            if len(self._fallos) + len(self._bloqueado_hasta) > self._max_claves:
                self._purgar(ahora)
            fallos = self._fallos.setdefault(clave, deque())
            while fallos and ahora - fallos[0] > self.ventana:
                fallos.popleft()
            fallos.append(ahora)
            if len(fallos) >= self.max_intentos:
                self._bloqueado_hasta[clave] = ahora + self.bloqueo
                del self._fallos[clave]

    def limpiar(self, clave: str) -> None:
        """Borra los fallos y el bloqueo de la clave (tras un inicio de sesión correcto)."""
        with self._cerrojo:
            self._fallos.pop(clave, None)
            self._bloqueado_hasta.pop(clave, None)

    def _purgar(self, ahora: float) -> None:
        """Elimina entradas caducadas para que la memoria no crezca sin límite."""
        for clave in [c for c, hasta in self._bloqueado_hasta.items() if hasta <= ahora]:
            del self._bloqueado_hasta[clave]
        for clave in [c for c, f in self._fallos.items() if not f or ahora - f[-1] > self.ventana]:
            del self._fallos[clave]
