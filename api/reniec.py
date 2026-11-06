"""Verificación de un DNI contra RENIEC mediante Scrall (https://scrall.net).

Reglas de diseño:
- La clave de Scrall vive solo en el servidor (variable SCRALL_API_KEY); el navegador nunca la ve.
- El formato (8 dígitos ASCII) se valida ANTES de llamar, con las mismas reglas del resto de la app.
- Scrall permite 2 consultas cada 10 s: se aplica el mismo tope aquí, para no gastar la cuota ni recibir 429.
- Nunca se escribe en logs el DNI consultado ni la clave.
- Los errores se devuelven como `ResultadoDni` (sin excepciones) para que el endpoint decida el código HTTP.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import requests

from api import validaciones

URL_POR_DEFECTO = "https://api.scrall.net/v1/reniec/basico"
TIMEOUT_SEGUNDOS = 10


@dataclass
class ResultadoDni:
    # estado: ok | no_existe | formato | no_configurado | clave_invalida | limite | inalcanzable | error
    estado: str
    mensaje: str
    datos: Optional[dict] = field(default=None)
    reintentar_en: Optional[int] = None


class LimiteConsultas:
    """Ventana deslizante: como máximo `max_consultas` cada `ventana` segundos (en memoria)."""

    def __init__(self, max_consultas=2, ventana=10.0, reloj=time.monotonic):
        self.max_consultas, self.ventana, self._reloj = max_consultas, float(ventana), reloj
        self._marcas: deque = deque()
        self._cerrojo = threading.Lock()

    def reservar(self) -> int:
        """0 si se puede consultar ahora (y reserva el turno); si no, los segundos que faltan."""
        with self._cerrojo:
            ahora = self._reloj()
            while self._marcas and ahora - self._marcas[0] >= self.ventana:
                self._marcas.popleft()
            if len(self._marcas) >= self.max_consultas:
                return max(1, int(self.ventana - (ahora - self._marcas[0]) + 0.999))
            self._marcas.append(ahora)
            return 0


limite_global = LimiteConsultas()


def _primero(r: dict, *claves):
    for clave in claves:
        if r.get(clave) not in (None, ""):
            return r[clave]
    return None


def _datos_de(resultado: dict) -> dict:
    """Scrall responde con claves en mayúsculas (D_...) o en minúsculas según el endpoint."""
    return {
        "dni": _primero(resultado, "D_NUDNI", "nu_dni"),
        "nombres": _primero(resultado, "D_PRENOMBRES", "prenombres"),
        "apellido_paterno": _primero(resultado, "D_APEPATERNO", "ape_paterno"),
        "apellido_materno": _primero(resultado, "D_APEMATERNO", "ape_materno"),
        "fecha_nacimiento": _primero(resultado, "D_FENACIMIENTO", "fe_nacimiento"),
    }


def consultar_dni(dni, sesion=requests) -> ResultadoDni:
    try:
        dni = validaciones.normalizar_dni(dni)
    except ValueError as exc:
        return ResultadoDni("formato", str(exc))
    if dni is None:
        return ResultadoDni("formato", "Escribe un DNI de 8 dígitos.")

    clave = os.getenv("SCRALL_API_KEY", "").strip()
    if not clave:
        return ResultadoDni("no_configurado", "La verificación con RENIEC no está configurada en el servidor.")
    url = os.getenv("SCRALL_DNI_URL", "").strip() or URL_POR_DEFECTO
    esquema = os.getenv("SCRALL_AUTH_SCHEME", "Basic").strip() or "Basic"

    espera = limite_global.reservar()
    if espera:
        return ResultadoDni("limite", f"Demasiadas consultas seguidas. Reintenta en {espera} s.", reintentar_en=espera)

    try:
        res = sesion.post(
            url, json={"dni": dni}, timeout=TIMEOUT_SEGUNDOS,
            headers={"Authorization": f"{esquema} {clave}", "Content-Type": "application/json"},
        )
    except requests.Timeout:
        return ResultadoDni("inalcanzable", "RENIEC tardó demasiado en responder. Intenta de nuevo.")
    except requests.RequestException:
        return ResultadoDni("inalcanzable", "No se pudo conectar con el servicio de RENIEC.")

    if res.status_code == 401:
        return ResultadoDni("clave_invalida", "El servidor tiene una clave de RENIEC inválida. Avisa al administrador.")
    if res.status_code == 422:
        return ResultadoDni("formato", "El servicio rechazó el formato del DNI.")
    if res.status_code == 429:
        try:
            texto = str(res.json().get("message", ""))
        except ValueError:
            texto = ""
        encontrado = re.search(r"\d+", texto)
        espera = int(encontrado.group()) if encontrado else 10
        return ResultadoDni("limite", f"Límite de consultas alcanzado. Reintenta en {espera} s.", reintentar_en=espera)
    if not res.ok:
        return ResultadoDni("error", f"El servicio de RENIEC respondió con error {res.status_code}.")

    try:
        cuerpo = res.json()
    except ValueError:
        return ResultadoDni("error", "Respuesta inesperada del servicio de RENIEC.")
    mensaje = cuerpo.get("message") if isinstance(cuerpo, dict) else None
    if mensaje == "found data" and isinstance(cuerpo.get("result"), dict):
        return ResultadoDni("ok", "DNI verificado en RENIEC.", datos=_datos_de(cuerpo["result"]))
    if mensaje == "not found data":
        return ResultadoDni("no_existe", "Ese DNI no existe en RENIEC.")
    return ResultadoDni("error", "Respuesta inesperada del servicio de RENIEC.")
