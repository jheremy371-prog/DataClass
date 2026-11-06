"""Contraseñas: hash versionado, política mínima y contraseñas temporales (H-04).

Sin dependencias de FastAPI, para poder probarlo de forma aislada.

Formato actual:  pbkdf2_sha256$<iteraciones>$<sal_hex>$<hash_hex>
Formato antiguo: <sal_hex>:<hash_hex>  (PBKDF2-SHA256 con 310.000 iteraciones). Se sigue aceptando y la
cuenta se vuelve a guardar con el formato actual en el siguiente inicio de sesión correcto (rehash).
Confirma el número de iteraciones con la guía vigente de OWASP antes de fijarlo en producción.
"""
import hashlib
import hmac
import secrets
from typing import Optional

ALGORITMO = "pbkdf2_sha256"
ITERACIONES = 600_000
ITERACIONES_LEGADO = 310_000
LONGITUD_MINIMA = 12
LONGITUD_MAXIMA = 128


def hash_password(password: str, salt: Optional[bytes] = None, iteraciones: int = ITERACIONES) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iteraciones)
    return f"{ALGORITMO}${iteraciones}${salt.hex()}${digest.hex()}"


def _partes(almacenado: str):
    """(iteraciones, sal, digest_hex) del formato actual o del antiguo; ValueError si no se reconoce."""
    if almacenado.startswith(f"{ALGORITMO}$"):
        _, iteraciones, sal_hex, digest_hex = almacenado.split("$")
        return int(iteraciones), bytes.fromhex(sal_hex), digest_hex
    sal_hex, digest_hex = almacenado.split(":", 1)
    return ITERACIONES_LEGADO, bytes.fromhex(sal_hex), digest_hex


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        iteraciones, sal, digest_hex = _partes(almacenado)
        if iteraciones < 1:
            return False
        candidato = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, iteraciones).hex()
        return hmac.compare_digest(candidato, digest_hex)
    except (ValueError, TypeError, AttributeError):
        return False


def necesita_rehash(almacenado: str) -> bool:
    """True si el hash usa el formato antiguo o menos iteraciones que las actuales."""
    try:
        iteraciones, _, _ = _partes(almacenado)
    except (ValueError, TypeError, AttributeError):
        return False
    return not almacenado.startswith(f"{ALGORITMO}$") or iteraciones < ITERACIONES


# Hash de una clave que nadie conoce: se verifica contra él cuando el correo no existe, para que
# "correo inexistente" y "clave incorrecta" tarden lo mismo (no revelar qué cuentas existen).
HASH_FICTICIO = hash_password(secrets.token_urlsafe(24))


def validar_politica(password: str, correo: Optional[str] = None) -> str:
    """Devuelve la contraseña si cumple la política mínima; ValueError con el motivo si no."""
    if not isinstance(password, str):
        raise ValueError("La contraseña debe ser texto.")
    if len(password) < LONGITUD_MINIMA:
        raise ValueError(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres.")
    if len(password) > LONGITUD_MAXIMA:
        raise ValueError(f"La contraseña no puede superar {LONGITUD_MAXIMA} caracteres.")
    if password.strip() != password:
        raise ValueError("La contraseña no puede empezar ni terminar con espacios.")
    if len(set(password)) < 5:
        raise ValueError("La contraseña es demasiado repetitiva.")
    if password.isdigit():
        raise ValueError("La contraseña no puede ser solo números.")
    if correo:
        usuario = correo.split("@")[0].lower()
        if len(usuario) >= 4 and usuario in password.lower():
            raise ValueError("La contraseña no puede contener tu correo.")
    return password


def contrasena_temporal() -> str:
    """Clave temporal legible, de 16 caracteres, que cumple la política."""
    return secrets.token_urlsafe(12)
