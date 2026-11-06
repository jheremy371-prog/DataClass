"""Validaciones de datos de entrada, sin dependencias externas.

Se usan tanto en la API (validadores de Pydantic) como en el formulario de Streamlit, de modo que
las reglas sean idénticas en ambos lados. La API es la barrera real: el formulario solo ayuda.
"""
import re
import unicodedata
from typing import Any, Optional

# Solo dígitos ASCII 0-9. Se evita \d y str.isdigit() porque aceptan dígitos Unicode (p. ej. "٣", "²").
_DNI = re.compile(r"[0-9]{8}")
_ID_INSTITUCIONAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,49}")
_SEPARADORES_TELEFONO = re.compile(r"[\s\-().]")
_TELEFONO = re.compile(r"\+?[0-9]{7,15}")
_CARACTERES_NOMBRE_PERMITIDOS = {" ", "'", "’", "-", "."}


def solo_digitos_ascii(texto: str) -> str:
    """Devuelve únicamente los caracteres 0-9 de `texto` (útil para limpiar lo que se escribe en el campo)."""
    return "".join(c for c in (texto or "") if "0" <= c <= "9")


def normalizar_dni(valor: Any) -> Optional[str]:
    """DNI peruano: exactamente 8 dígitos. Vacío o None significa 'sin DNI' (None).

    Rechaza números JSON (12345678 sin comillas) porque perderían los ceros iniciales, y rechaza
    letras, espacios internos, signos y dígitos que no sean 0-9.
    """
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ValueError("El DNI debe enviarse como texto de 8 dígitos.")
    texto = valor.strip()
    if texto == "":
        return None
    if not _DNI.fullmatch(texto):
        raise ValueError("El DNI debe tener exactamente 8 dígitos numéricos (sin letras, espacios ni símbolos).")
    return texto


def normalizar_telefono(valor: Any) -> Optional[str]:
    """Teléfono: 7 a 15 dígitos (norma E.164), con '+' inicial opcional. Quita espacios, guiones y paréntesis."""
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ValueError("El teléfono debe enviarse como texto.")
    texto = _SEPARADORES_TELEFONO.sub("", valor.strip())
    if texto == "":
        return None
    if not _TELEFONO.fullmatch(texto):
        raise ValueError("El teléfono debe tener entre 7 y 15 dígitos (puede iniciar con +).")
    return texto


def normalizar_nombre(valor: Any) -> str:
    """Nombre: letras de cualquier idioma, espacios, apóstrofe, guion y punto. Sin dígitos ni símbolos."""
    if not isinstance(valor, str):
        raise ValueError("El nombre debe ser texto.")
    texto = " ".join(valor.split())  # recorta y colapsa espacios repetidos
    if len(texto) < 2:
        raise ValueError("El nombre debe tener al menos 2 caracteres.")
    if not texto[0].isalpha():  # evita «-», «.» o «'» sueltos al inicio (y nombres sin ninguna letra)
        raise ValueError("El nombre debe empezar con una letra.")
    for caracter in texto:
        if not (caracter.isalpha() or caracter in _CARACTERES_NOMBRE_PERMITIDOS) or unicodedata.category(caracter).startswith("C"):
            raise ValueError("El nombre solo puede contener letras, espacios, apóstrofes, guiones y puntos.")
    return texto


_CORREO = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")


def normalizar_correo(valor: Any) -> str:
    """Correo en minúsculas con forma usuario@dominio.ext (sin espacios ni controles), de hasta 180 caracteres."""
    if not isinstance(valor, str):
        raise ValueError("El correo debe ser texto.")
    texto = valor.strip().lower()
    if len(texto) > 180 or not _CORREO.fullmatch(texto) or any(unicodedata.category(c).startswith("C") for c in texto):
        raise ValueError("Ingresa un correo válido (por ejemplo, nombre@institucion.edu).")
    return texto


def normalizar_id_institucional(valor: Any) -> str:
    """ID institucional: 1 a 50 caracteres entre letras, números, punto, guion y guion bajo."""
    if not isinstance(valor, str):
        raise ValueError("El ID institucional debe ser texto.")
    texto = valor.strip()
    if not _ID_INSTITUCIONAL.fullmatch(texto):
        raise ValueError("El ID solo puede tener letras, números, punto, guion y guion bajo (máximo 50).")
    return texto


# --- Reglas para cargas masivas (CSV / Excel) ---------------------------------------------------------
_ESTADOS_ASISTENCIA = {
    "presente": "presente", "p": "presente", "asistio": "presente", "asistió": "presente",
    "tardanza": "tardanza", "t": "tardanza", "tarde": "tardanza",
    "falta": "falta", "f": "falta", "inasistencia": "falta",
    "justificada": "justificada", "j": "justificada", "justificado": "justificada",
}
_PREFIJOS_FORMULA = ("=", "+", "-", "@")  # una hoja de cálculo los interpreta como fórmula (inyección CSV)
_FECHA_MINIMA = (2000, 1, 1)


def normalizar_texto_libre(valor: Any, max_largo: int, obligatorio: bool = True) -> Optional[str]:
    """Texto corto (curso, periodo, aula). Colapsa espacios y rechaza caracteres de control y prefijos de fórmula."""
    if valor is None or (isinstance(valor, str) and valor.strip() == ""):
        if obligatorio:
            raise ValueError("El valor es obligatorio.")
        return None
    if not isinstance(valor, str):
        raise ValueError("Debe ser texto.")
    texto = " ".join(valor.split())
    if len(texto) > max_largo:
        raise ValueError(f"Máximo {max_largo} caracteres.")
    if texto.startswith(_PREFIJOS_FORMULA):
        raise ValueError("No puede empezar con =, +, - ni @ (se confundiría con una fórmula de Excel).")
    if any(unicodedata.category(c).startswith("C") for c in texto):
        raise ValueError("Contiene caracteres no permitidos.")
    return texto


def normalizar_nota(valor: Any) -> float:
    """Nota de 0 a 20. Acepta coma o punto decimal. Rechaza vacío, NaN, infinito y valores fuera de rango."""
    import math

    if isinstance(valor, bool) or valor is None:
        raise ValueError("La nota es obligatoria y debe ser un número.")
    if isinstance(valor, (int, float)):
        numero = float(valor)
    elif isinstance(valor, str):
        texto = valor.strip().replace(",", ".")
        if not re.fullmatch(r"[0-9]{1,2}(\.[0-9]{1,4})?", texto):
            raise ValueError("La nota debe ser un número entre 0 y 20 (por ejemplo 14 o 14,5).")
        numero = float(texto)
    else:
        raise ValueError("La nota debe ser un número entre 0 y 20.")
    if not math.isfinite(numero) or not 0 <= numero <= 20:
        raise ValueError("La nota debe estar entre 0 y 20.")
    return round(numero, 2)


def normalizar_fecha_asistencia(valor: Any, hoy=None) -> str:
    """Fecha en formato AAAA-MM-DD. Acepta también DD/MM/AAAA. Rechaza fechas futuras o anteriores al 2000."""
    from datetime import date, datetime

    hoy = hoy or date.today()
    if isinstance(valor, datetime):
        fecha = valor.date()
    elif isinstance(valor, date):
        fecha = valor
    elif isinstance(valor, str):
        texto = valor.strip()
        try:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", texto):
                fecha = date.fromisoformat(texto)
            elif re.fullmatch(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}", texto):
                dia, mes, anio = (int(p) for p in texto.split("/"))
                fecha = date(anio, mes, dia)
            else:
                raise ValueError
        except ValueError:
            raise ValueError("Fecha inválida. Usa AAAA-MM-DD o DD/MM/AAAA.") from None
    else:
        raise ValueError("Fecha inválida. Usa AAAA-MM-DD o DD/MM/AAAA.")
    if fecha > hoy:
        raise ValueError("La fecha no puede ser futura.")
    if fecha < date(*_FECHA_MINIMA):
        raise ValueError("La fecha es demasiado antigua.")
    return fecha.isoformat()


def normalizar_estado_asistencia(valor: Any) -> str:
    """presente / tardanza / falta / justificada (acepta las iniciales P, T, F, J)."""
    if not isinstance(valor, str) or valor.strip() == "":
        raise ValueError("El estado es obligatorio (presente, tardanza, falta o justificada).")
    estado = _ESTADOS_ASISTENCIA.get(valor.strip().lower())
    if estado is None:
        raise ValueError("Estado no válido. Usa presente, tardanza, falta o justificada (o P, T, F, J).")
    return estado


def normalizar_aula(valor: Any) -> Optional[str]:
    """Aula en una sola forma canónica: sin espacios sobrantes, en mayúsculas y con compatibilidad Unicode (NFKC).

    «a-302», «A-302 » y « A-302» son la misma aula. Se usa en la API (estudiantes y usuarios), en la importación y
    en el filtro por aula, porque el acceso de un docente se decide comparando textos de aula. Vacío -> None.
    """
    if isinstance(valor, str):
        valor = unicodedata.normalize("NFKC", valor)
    texto = normalizar_texto_libre(valor, 50, obligatorio=False)
    return texto.upper() if texto else None


def clave_curso(nombre: str) -> str:
    """Clave para reconocer el mismo curso escrito distinto: ignora mayúsculas, tildes, espacios y signos."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", str(nombre)) if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "_" for c in sin_tildes.lower()).strip("_")


def unificar_curso(conexion, curso: str) -> str:
    """Si ya existe una nota con el mismo curso escrito de otra forma, devuelve esa grafía; si no, `curso`.

    La grafía ya guardada tiene prioridad (la primera por orden alfabético si hay varias), igual que en la importación.
    """
    clave = clave_curso(curso)
    for (existente,) in conexion.execute("SELECT DISTINCT curso_modulo FROM calificaciones ORDER BY curso_modulo"):
        if clave_curso(existente) == clave:
            return existente
    return curso


def primera_ip_valida(cabecera: Optional[str]) -> Optional[str]:
    """Primera dirección IP válida de una cabecera X-Forwarded-For, o None si no hay ninguna.

    Sirve para reenviar a la API la IP real del navegador. Se valida el formato para no pasar texto
    arbitrario a la bitácora ni al limitador.
    """
    import ipaddress

    if not cabecera or not isinstance(cabecera, str):
        return None
    primera = cabecera.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(primera))
    except ValueError:
        return None
