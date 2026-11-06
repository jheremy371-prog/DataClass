from pathlib import Path
import pickle
import sqlite3
import os
import hashlib
import ipaddress
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from contextlib import asynccontextmanager, closing
from typing import Literal, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
import jwt
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool

load_dotenv()

from api import __version__, auditoria, catalogo, importacion, reniec, riesgo, seguridad, validaciones
from api.database import DB_PATH, inicializar_esquema, obtener_conexion
from api.limitador import LimitadorIntentos

# Intentos fallidos de login: 5 por correo y 30 por IP cada 5 minutos; luego 5 minutos de bloqueo.
# El límite por IP es mayor porque varias personas de una misma institución pueden compartir la IP.
limitador_correo = LimitadorIntentos(max_intentos=int(os.getenv("DATACLASS_LOGIN_MAX_INTENTOS", "5")))
limitador_ip = LimitadorIntentos(max_intentos=int(os.getenv("DATACLASS_LOGIN_MAX_INTENTOS_IP", "30")))


def _ip_limitable(ip: str) -> bool:
    """True si la IP identifica de verdad a un cliente y se le puede aplicar el límite por IP.

    Si la API solo ve una IP de loopback es porque Streamlit (o el proxy) llama desde el mismo servidor y no
    reenvió la IP real (X-Forwarded-For con uvicorn --proxy-headers). Contar esos fallos juntos permitiría que
    cualquiera bloquee el login de toda la institución; en ese caso solo actúa el límite por correo.
    """
    try:
        return not ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False  # "desconocida" u otro valor no atribuible

SECRET_KEY = os.getenv("DATACLASS_JWT_SECRET", "")
SECRET_MIN_LENGTH = 32
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def validar_configuracion() -> None:
    """Impide arrancar la API sin un secreto JWT real (nunca se genera uno al azar)."""
    secreto = SECRET_KEY or ""
    if len(secreto) < SECRET_MIN_LENGTH or "REEMPLAZA" in secreto.upper():
        raise RuntimeError(
            "DATACLASS_JWT_SECRET falta, es un texto de ejemplo o tiene menos de "
            f"{SECRET_MIN_LENGTH} caracteres. Genera uno con: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))" y guárdalo en .env'
        )
    if os.getenv("DATACLASS_SYNC_AUTO") == "1":
        from api import sync  # con la nube activada, sin clave de seudónimo no se arranca (H-03)

        sync._clave_seudonimo()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    auditoria.configurar_logging()
    validar_configuracion()
    inicializar_esquema()
    _iniciar_modelo()
    # Sincronización automática con Firebase: desactivada salvo que DATACLASS_SYNC_AUTO=1.
    worker = None
    if os.getenv("DATACLASS_SYNC_AUTO") == "1":
        from api.sync import SyncWorker

        worker = SyncWorker(intervalo=float(os.getenv("DATACLASS_SYNC_INTERVALO", "30")))
        worker.start()
    try:
        yield
    finally:
        if worker is not None:
            worker.detener()

# /docs, /redoc y /openapi.json solo con DATACLASS_DOCS=1 (útil en desarrollo; apágalos en producción).
_DOCS_ACTIVAS = os.getenv("DATACLASS_DOCS", "0").strip() == "1"

app = FastAPI(
    docs_url="/docs" if _DOCS_ACTIVAS else None,
    redoc_url="/redoc" if _DOCS_ACTIVAS else None,
    openapi_url="/openapi.json" if _DOCS_ACTIVAS else None,
    title="API DataClass",
    description="API inicial para gestionar datos académicos, evaluar indicadores experimentales de riesgo y control de acceso RBAC.",
    version=__version__,
    lifespan=lifespan,
)

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "modelos" / "modelo_riesgo.pkl"

def _cargar_modelo():
    """Carga el modelo solo si su huella SHA-256 coincide con la registrada (pickle ejecuta código al abrirse).

    Cualquier fallo (archivo ausente, huella distinta, versión incompatible de scikit-learn...) deja la API
    funcionando sin modelo, con el motivo en el log: nunca tumba el arranque ni carga un archivo dudoso.
    """
    logger = logging.getLogger("dataclass.modelo")
    if not MODEL_PATH.exists():
        return None
    correcto, motivo = riesgo.verificar_integridad_modelo(MODEL_PATH, MODEL_PATH.with_suffix(".json"))
    if not correcto:
        logger.error("Modelo NO cargado: %s. Vuelve a entrenarlo o ejecuta «python modelos/entrenamiento.py --sellar».", motivo)
        return None
    try:
        with MODEL_PATH.open("rb") as file:
            return pickle.load(file)
    except Exception:  # noqa: BLE001 - pickle puede fallar con AttributeError, ImportError, ModuleNotFoundError, etc.
        logger.exception("Modelo NO cargado: no se pudo leer el archivo.")
        return None


# El modelo se carga al arrancar el servidor (en `lifespan`), no al importar el módulo.
_SIN_CARGAR = object()
motor_predictivo = _SIN_CARGAR


def modelo_activo():
    """El modelo cargado, o None si no hay (o si todavía no se cargó)."""
    return None if motor_predictivo is _SIN_CARGAR else motor_predictivo


def _iniciar_modelo() -> None:
    global motor_predictivo
    if motor_predictivo is not _SIN_CARGAR:  # ya cargado (o sustituido en una prueba)
        return
    motor_predictivo = _cargar_modelo()
    if motor_predictivo is not None:
        import sklearn

        riesgo.aplicar_metadatos_modelo(MODEL_PATH.with_suffix(".json"), sklearn.__version__)


class EstudianteCrear(BaseModel):
    id_estudiante: Optional[str] = Field(default=None, max_length=50)  # vacío -> la API lo genera (AAAA-0001...)
    dni: Optional[str] = None
    nombre_completo: str = Field(min_length=2, max_length=150)
    aula: Optional[str] = Field(default=None, max_length=50)
    telefono_apoderado: Optional[str] = Field(default=None, max_length=20)

    @field_validator("id_estudiante", mode="before")
    @classmethod
    def _validar_id(cls, valor):
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return None
        return validaciones.normalizar_id_institucional(valor)

    @field_validator("aula", mode="before")
    @classmethod
    def _validar_aula(cls, valor):
        return validaciones.normalizar_aula(valor)

    @field_validator("dni", mode="before")
    @classmethod
    def _validar_dni(cls, valor):
        return validaciones.normalizar_dni(valor)

    @field_validator("nombre_completo", mode="before")
    @classmethod
    def _validar_nombre(cls, valor):
        return validaciones.normalizar_nombre(valor)

    @field_validator("telefono_apoderado", mode="before")
    @classmethod
    def _validar_telefono(cls, valor):
        return validaciones.normalizar_telefono(valor)


class EstudianteActualizar(BaseModel):
    nombre_completo: Optional[str] = Field(default=None, min_length=2, max_length=150)
    aula: Optional[str] = Field(default=None, max_length=50)
    telefono_apoderado: Optional[str] = Field(default=None, max_length=20)

    @field_validator("aula", mode="before")
    @classmethod
    def _validar_aula(cls, valor):
        return validaciones.normalizar_aula(valor)

    @field_validator("nombre_completo", mode="before")
    @classmethod
    def _validar_nombre(cls, valor):
        return None if valor is None else validaciones.normalizar_nombre(valor)

    @field_validator("telefono_apoderado", mode="before")
    @classmethod
    def _validar_telefono(cls, valor):
        return validaciones.normalizar_telefono(valor)


class CalificacionCrear(BaseModel):
    id_estudiante: str = Field(min_length=1, max_length=50)
    curso_modulo: str = Field(min_length=1, max_length=120)
    nota_obtenida: float = Field(ge=0, le=20)
    periodo_evaluacion: str = Field(min_length=1, max_length=80)

    # Mismas reglas que la importación masiva: espacios colapsados, sin prefijos de fórmula, nota de 0 a 20.
    @field_validator("curso_modulo", mode="before")
    @classmethod
    def _validar_curso(cls, valor):
        return validaciones.normalizar_texto_libre(valor, 120)

    @field_validator("periodo_evaluacion", mode="before")
    @classmethod
    def _validar_periodo(cls, valor):
        return validaciones.normalizar_texto_libre(valor, 80)

    @field_validator("nota_obtenida", mode="before")
    @classmethod
    def _validar_nota(cls, valor):
        return validaciones.normalizar_nota(valor)


class AsistenciaCrear(BaseModel):
    id_estudiante: str = Field(min_length=1, max_length=50)
    fecha: date
    estado_asistencia: Literal["presente", "tardanza", "falta", "justificada"]

    @field_validator("fecha", mode="before")
    @classmethod
    def _validar_fecha(cls, valor):
        return validaciones.normalizar_fecha_asistencia(valor)  # rechaza fechas futuras o anteriores al 2000, como la importación


class CalificacionActualizar(BaseModel):
    curso_modulo: Optional[str] = None
    nota_obtenida: Optional[float] = None
    periodo_evaluacion: Optional[str] = None

    @field_validator("curso_modulo", mode="before")
    @classmethod
    def _validar_curso(cls, valor):
        return None if valor is None else validaciones.normalizar_texto_libre(valor, 120)

    @field_validator("periodo_evaluacion", mode="before")
    @classmethod
    def _validar_periodo(cls, valor):
        return None if valor is None else validaciones.normalizar_texto_libre(valor, 80)

    @field_validator("nota_obtenida", mode="before")
    @classmethod
    def _validar_nota(cls, valor):
        return None if valor is None else validaciones.normalizar_nota(valor)


class AsistenciaActualizar(BaseModel):
    fecha: Optional[date] = None
    estado_asistencia: Optional[Literal["presente", "tardanza", "falta", "justificada"]] = None

    @field_validator("fecha", mode="before")
    @classmethod
    def _validar_fecha(cls, valor):
        return None if valor is None else validaciones.normalizar_fecha_asistencia(valor)


class EstudianteData(BaseModel):
    notas_promedio: float = Field(ge=0, le=20)
    porcentaje_asistencia: int = Field(ge=0, le=100)


class AlertaCrear(BaseModel):
    id_estudiante: str = Field(min_length=1, max_length=50)
    tipo_alerta: Literal["desercion", "bajo_rendimiento"]
    nivel_riesgo: Literal["bajo", "medio", "alto"]
    descripcion: str = Field(min_length=5, max_length=1000)
    # Una alerta creada por una persona siempre queda como «manual» y sin probabilidad: así no se puede hacer pasar
    # por una alerta del modelo. Si el cliente envía version_modelo o probabilidad, se ignoran.


class AlertaActualizar(BaseModel):
    estado: Literal["pendiente", "en_seguimiento", "resuelta", "descartada"]


class IntervencionCrear(BaseModel):
    id_estudiante: str = Field(min_length=1, max_length=50)
    id_alerta: Optional[int] = Field(default=None, ge=1)
    tutor: Optional[str] = Field(default=None, max_length=120)  # se ignora: el tutor es la cuenta que registra
    tipo_intervencion: str = Field(min_length=2, max_length=100)
    descripcion: str = Field(min_length=5, max_length=1000)
    fecha_intervencion: date
    resultado: Optional[str] = Field(default=None, max_length=1000)
    proxima_revision: Optional[date] = None


class IntervencionActualizar(BaseModel):
    resultado: str = Field(min_length=2, max_length=1000)
    proxima_revision: Optional[date] = None


class Token(BaseModel):
    access_token: str
    token_type: str
    rol: str
    nombre_completo: str
    debe_cambiar: bool = False


class CambioPassword(BaseModel):
    password_actual: str = Field(min_length=1, max_length=128)
    password_nueva: str = Field(min_length=1, max_length=128)


class UsuarioCrear(BaseModel):
    correo: str = Field(min_length=6, max_length=180)
    nombre_completo: str = Field(min_length=2, max_length=150)
    rol: Literal["docente", "directivo"] = "docente"
    aula: Optional[str] = Field(default=None, max_length=50)
    password: str = Field(min_length=12, max_length=128)
    debe_cambiar: bool = False  # True: la cuenta debe elegir su propia clave antes de usar el sistema

    @field_validator("aula", mode="before")
    @classmethod
    def _validar_aula(cls, valor):
        return validaciones.normalizar_aula(valor)


class UsuarioActualizar(BaseModel):
    nombre_completo: Optional[str] = Field(default=None, min_length=2, max_length=150)
    rol: Optional[Literal["docente", "directivo"]] = None
    aula: Optional[str] = Field(default=None, max_length=50)
    activo: Optional[int] = Field(default=None, ge=0, le=1)

    @field_validator("aula", mode="before")
    @classmethod
    def _validar_aula(cls, valor):
        return validaciones.normalizar_aula(valor)


def _reevaluar_riesgo(conexion, id_estudiante: str) -> None:
    try:
        riesgo.evaluar_estudiante(conexion, id_estudiante, modelo_activo())
    except riesgo.RiesgoError:
        pass


def fila_a_dict(fila):
    return dict(fila) if fila is not None else None


def crear_token_acceso(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    to_encode.setdefault("jti", secrets.token_urlsafe(16))  # identifica este token para poder revocarlo al cerrar sesión
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _hash_password(password: str) -> str:
    return seguridad.hash_password(password)


def _verificar_password(password: str, stored: str) -> bool:
    return seguridad.verificar_password(password, stored)


def _bootstrap_admin(conexion):
    correo = os.getenv("DATACLASS_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("DATACLASS_ADMIN_PASSWORD", "")
    nombre = os.getenv("DATACLASS_ADMIN_NAME", "Administrador DataClass").strip()
    if correo and password and len(password) >= 12 and "CAMBIA" not in password.upper() and "REEMPLAZA" not in password.upper():
        # Solo crea al primer directivo. Con una cuenta directiva ya existente la clave de .env deja de usarse
        # (para crear o restablecer sin dejar la clave en .env: python -m api.crear_admin).
        existe = conexion.execute("SELECT 1 FROM usuarios WHERE rol = 'directivo' LIMIT 1").fetchone()
        if not existe:
            conexion.execute(
                "INSERT INTO usuarios (correo, nombre_completo, rol, password_hash, activo) VALUES (?, ?, 'directivo', ?, 1)",
                (correo, nombre, _hash_password(password)),
            )


@app.post("/api/v1/auth/login", response_model=Token, summary="Autenticación de usuarios y emisión de Token JWT")
def login_usuario(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    correo = form_data.username.strip().lower()
    ip = request.client.host if request.client else "desconocida"
    # El bloqueo se aplica igual exista o no la cuenta, para no revelar qué correos están registrados.
    ip_limitable = _ip_limitable(ip)
    espera = max(limitador_correo.segundos_bloqueado(correo), limitador_ip.segundos_bloqueado(ip) if ip_limitable else 0)
    if espera:
        with closing(obtener_conexion()) as conexion_auditoria:
            auditoria.registrar(
                conexion_auditoria, "login_bloqueado", ip=ip, metodo="POST", ruta="/api/v1/auth/login",
                estado_http=429,
            )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Espera {espera} segundos antes de volver a intentar.",
            headers={"Retry-After": str(espera)},
        )
    with obtener_conexion() as conexion:
        _bootstrap_admin(conexion)
        usuario = conexion.execute(
            "SELECT id_usuario, correo, nombre_completo, rol, aula, password_hash, activo, token_version, debe_cambiar "
            "FROM usuarios WHERE correo = ?",
            (correo,),
        ).fetchone()
        # Se verifica siempre contra un hash (el ficticio si el correo no existe): misma duración en ambos casos.
        clave_correcta = seguridad.verificar_password(
            form_data.password, usuario["password_hash"] if usuario else seguridad.HASH_FICTICIO
        )
        if not usuario or not usuario["activo"] or not clave_correcta:
            limitador_correo.registrar_fallo(correo)
            if ip_limitable:
                limitador_ip.registrar_fallo(ip)
            auditoria.registrar(
                conexion, "login_fallido", id_usuario=usuario["id_usuario"] if usuario else None, ip=ip,
                metodo="POST", ruta="/api/v1/auth/login", estado_http=401,
            )  # sin el texto escrito: a veces es una contraseña tecleada en el campo equivocado
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales incorrectas o cuenta inactiva.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        limitador_correo.limpiar(correo)
        if seguridad.necesita_rehash(usuario["password_hash"]):
            conexion.execute(
                "UPDATE usuarios SET password_hash = ? WHERE id_usuario = ?",
                (seguridad.hash_password(form_data.password), usuario["id_usuario"]),
            )
        auditoria.registrar(
            conexion, "login_ok", id_usuario=usuario["id_usuario"], rol=usuario["rol"], ip=ip,
            metodo="POST", ruta="/api/v1/auth/login", estado_http=200,
        )
        access_token = crear_token_acceso(
            data={
                "sub": str(usuario["id_usuario"]),
                "rol": usuario["rol"],
                "nombre": usuario["nombre_completo"],
                "aula": usuario["aula"],
                "tv": usuario["token_version"],
            },
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "rol": usuario["rol"],
            "nombre_completo": usuario["nombre_completo"],
            "debe_cambiar": bool(usuario["debe_cambiar"]),
        }


def _decodificar_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub") or payload.get("rol") not in {"docente", "directivo"}:
            raise jwt.InvalidTokenError("Token sin identidad o rol válido")
        return payload
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado. Inicia sesión nuevamente.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def verificar_token_sin_cambio(token: str = Depends(oauth2_scheme)):
    """Token válido y cuenta vigente (activa y con la misma token_version), aunque deba cambiar su clave."""
    payload = _decodificar_token(token)
    with closing(obtener_conexion()) as conexion:
        fila = _usuario_vigente(conexion, payload)
    payload["_debe_cambiar"] = bool(fila["debe_cambiar"])
    return payload


def verificar_token(payload: dict = Depends(verificar_token_sin_cambio)):
    """Como verificar_token_sin_cambio, pero exige que la cuenta no tenga un cambio de clave pendiente."""
    if payload.get("_debe_cambiar"):
        raise HTTPException(status_code=403, detail="Debes cambiar tu contraseña antes de continuar.")
    return payload


@app.get("/api/v1/auth/sesion", summary="Datos de la sesión actual (para restaurarla tras recargar)")
def sesion_actual(payload: dict = Depends(verificar_token_sin_cambio)):
    """Valida el token contra la base y devuelve rol y nombre vigentes."""
    with closing(obtener_conexion()) as conexion:
        fila = _usuario_vigente(conexion, payload)
    return {"rol": fila["rol"], "nombre_completo": payload.get("nombre") or "Usuario", "debe_cambiar": bool(payload.get("_debe_cambiar"))}


@app.post("/api/v1/auth/cerrar-sesion", status_code=status.HTTP_204_NO_CONTENT, summary="Cerrar sesión e invalidar el token en el servidor")
def cerrar_sesion(request: Request, payload: dict = Depends(verificar_token_sin_cambio)):
    """Revoca el token actual: quien lo haya copiado ya no puede usarlo, aunque no haya vencido.

    Solo se cierra esta sesión (otros dispositivos de la misma cuenta siguen abiertos). Un token anterior a este
    cambio, que no trae `jti`, no se puede revocar uno a uno: se suben las `token_version` de la cuenta.
    """
    _marcar_auditoria(request, detalle="cierre de sesión")
    jti = payload.get("jti")
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with obtener_conexion() as conexion:
        conexion.execute("DELETE FROM tokens_revocados WHERE expira_utc < ?", (ahora,))  # limpieza de los ya vencidos
        if jti:
            expira = datetime.fromtimestamp(int(payload.get("exp", 0)), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conexion.execute(
                "INSERT OR IGNORE INTO tokens_revocados (jti, id_usuario, expira_utc) VALUES (?, ?, ?)",
                (jti, int(payload["sub"]), expira),
            )
        else:
            conexion.execute("UPDATE usuarios SET token_version = token_version + 1 WHERE id_usuario = ?", (int(payload["sub"]),))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/auth/cambiar-password", response_model=Token, summary="Cambiar la propia contraseña")
def cambiar_password(datos: CambioPassword, payload: dict = Depends(verificar_token_sin_cambio)):
    """Exige la clave actual, aplica la política y devuelve un token nuevo (los anteriores dejan de valer)."""
    id_usuario = int(payload["sub"])
    with obtener_conexion() as conexion:
        usuario = conexion.execute(
            "SELECT id_usuario, correo, nombre_completo, rol, aula, password_hash, token_version FROM usuarios WHERE id_usuario = ?",
            (id_usuario,),
        ).fetchone()
        correo = usuario["correo"]
        espera = limitador_correo.segundos_bloqueado(correo)
        if espera:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiados intentos fallidos. Espera {espera} segundos antes de volver a intentar.",
                headers={"Retry-After": str(espera)},
            )
        if not seguridad.verificar_password(datos.password_actual, usuario["password_hash"]):
            limitador_correo.registrar_fallo(correo)
            raise HTTPException(status_code=400, detail="La contraseña actual no es correcta.")
        if datos.password_nueva == datos.password_actual:
            raise HTTPException(status_code=422, detail="La contraseña nueva debe ser distinta de la actual.")
        try:
            seguridad.validar_politica(datos.password_nueva, correo)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        limitador_correo.limpiar(correo)
        nueva_version = usuario["token_version"] + 1
        conexion.execute(
            "UPDATE usuarios SET password_hash = ?, token_version = ?, debe_cambiar = 0 WHERE id_usuario = ?",
            (seguridad.hash_password(datos.password_nueva), nueva_version, id_usuario),
        )
    token = crear_token_acceso(
        data={"sub": str(id_usuario), "rol": usuario["rol"], "nombre": usuario["nombre_completo"], "aula": usuario["aula"], "tv": nueva_version},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer", "rol": usuario["rol"], "nombre_completo": usuario["nombre_completo"], "debe_cambiar": False}


def verificar_directivo(usuario: dict = Depends(verificar_token)):
    """Exige rol directivo según la base de datos, no según el token.

    El token dura hasta 8 horas; si la cuenta se desactiva o se le quita el rol durante ese tiempo,
    el token no debe seguir sirviendo. Se usa la misma consulta que el resto de rutas protegidas.
    """
    with obtener_conexion() as conexion:
        vigente = _usuario_vigente(conexion, usuario)
    if vigente["rol"] != "directivo":
        raise HTTPException(status_code=403, detail="Esta operación requiere el rol directivo.")
    return usuario


def _usuario_vigente(conexion, payload: dict):
    """Lee rol, aula y estado actuales desde la base (el token puede estar desactualizado).

    Un cambio de clave, un restablecimiento, un cambio de rol o la desactivación suben token_version
    y dejan sin efecto los tokens anteriores.
    """
    try:
        id_usuario = int(payload.get("sub"))
    except (TypeError, ValueError):
        id_usuario = None
    fila = None
    if id_usuario is not None:
        fila = conexion.execute(
            "SELECT id_usuario, correo, nombre_completo, rol, aula, activo, token_version, debe_cambiar FROM usuarios WHERE id_usuario = ?",
            (id_usuario,),
        ).fetchone()
    # Un token cerrado con «Cerrar sesión» deja de servir aunque no haya vencido.
    jti = payload.get("jti")
    if fila is not None and jti and conexion.execute("SELECT 1 FROM tokens_revocados WHERE jti = ?", (jti,)).fetchone():
        fila = None
    # tv ausente = token emitido antes de la v1.8.1 (equivale a la versión 0).
    if fila is None or not fila["activo"] or int(payload.get("tv", 0)) != fila["token_version"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La cuenta ya no está activa. Inicia sesión nuevamente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return fila


def _asegurar_acceso_estudiante(conexion, id_estudiante: str, payload: dict):
    """Directivos acceden a todo; un docente solo a estudiantes de su aula.

    Un docente sin aula asignada no accede a ningún estudiante. Si el estudiante no existe o es de
    otra aula se responde igual (404) para no revelar qué identificadores existen.
    """
    usuario = _usuario_vigente(conexion, payload)
    if usuario["rol"] == "directivo":
        return usuario
    estudiante = conexion.execute(
        "SELECT aula FROM estudiantes WHERE id_estudiante = ?", (id_estudiante,)
    ).fetchone()
    if estudiante is None or not usuario["aula"] or estudiante["aula"] != usuario["aula"]:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
    return usuario


def acceso_estudiante(id_estudiante: str, payload: dict = Depends(verificar_token)) -> dict:
    """Dependencia para rutas con {id_estudiante} en la URL."""
    with closing(obtener_conexion()) as conexion:
        _asegurar_acceso_estudiante(conexion, id_estudiante, payload)
    return payload


def _identidad_de_cabecera(request: Request):
    """(id_usuario, rol) si la petición trae un JWT válido; (None, None) en otro caso. No lanza."""
    esquema, _, token = request.headers.get("authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not token:
        return None, None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"]), payload.get("rol")
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None, None


def _marcar_auditoria(request: Request, id_estudiante: Optional[str] = None, detalle: Optional[str] = None) -> None:
    """Las rutas indican a qué estudiante afectaron y qué cambió; el middleware lo anota en la bitácora (H-02)."""
    datos = getattr(request.state, "auditoria", None) or {}
    if id_estudiante:
        datos["id_estudiante"] = str(id_estudiante)[:50]
    if detalle:
        datos["detalle"] = detalle
    request.state.auditoria = datos


def _iguales(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _cambios_antes_despues(actual, cambios: dict) -> str:
    """«campo: antes->después» solo de los campos que cambian de verdad."""
    partes = []
    for campo, nuevo in cambios.items():
        if not _iguales(actual[campo], nuevo):
            partes.append(f"{campo}: {actual[campo]}->{nuevo}")
    return "; ".join(partes) or "sin cambios"


def _auditar_peticion(id_usuario, rol, ip, metodo, ruta, parametros, estado, extra=None) -> None:
    extra = extra or {}
    with closing(obtener_conexion()) as conexion:
        auditoria.registrar(
            conexion, auditoria.clasificar_metodo(metodo), id_usuario=id_usuario, rol=rol, ip=ip, metodo=metodo,
            ruta=ruta, id_estudiante=extra.get("id_estudiante") or auditoria.estudiante_de_ruta(ruta, parametros),
            estado_http=estado, detalle=extra.get("detalle"),
        )


@app.middleware("http")
async def seguridad_y_bitacora(request: Request, call_next):
    """Cabeceras de seguridad y bitácora de cada acceso a /api/ (también los rechazados)."""
    ruta = request.url.path
    estado = 500
    try:
        respuesta = await call_next(request)
        estado = respuesta.status_code
    finally:
        if not auditoria.omitir_ruta(ruta):
            id_usuario, rol = _identidad_de_cabecera(request)
            ip = request.client.host if request.client else None
            await run_in_threadpool(
                _auditar_peticion, id_usuario, rol, ip, request.method, ruta, dict(request.query_params), estado,
                dict(getattr(request.state, "auditoria", None) or {}),
            )
    if ruta.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-store"  # nada con datos personales en cachés intermedias
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
    if os.getenv("DATACLASS_FORZAR_HTTPS") == "1":
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return respuesta


@app.get("/api/v1/auditoria", dependencies=[Depends(verificar_directivo)], summary="Bitácora de accesos y cambios (solo directivos)")
def listar_auditoria(
    id_estudiante: Optional[str] = Query(default=None, max_length=50),
    id_usuario: Optional[int] = Query(default=None, ge=1),
    accion: Optional[Literal["lectura", "escritura", "eliminacion", "login_ok", "login_fallido", "login_bloqueado"]] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    limite: int = Query(default=100, ge=1, le=500),
    desplazamiento: int = Query(default=0, ge=0),
):
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha 'desde' no puede ser posterior a 'hasta'.")
    with closing(obtener_conexion()) as conexion:
        items = auditoria.consultar(
            conexion, id_estudiante=id_estudiante, id_usuario=id_usuario, accion=accion,
            desde=desde.isoformat() if desde else None, hasta=hasta.isoformat() if hasta else None,
            limite=limite, desplazamiento=desplazamiento,
        )
    return {"items": items, "limite": limite, "desplazamiento": desplazamiento}


@app.get("/api/v1/estado")
def estado_api():
    return {
        "api": "operativa",
        "base_datos": DB_PATH.exists(),
        "modelo_disponible": modelo_activo() is not None,
        "modelo": riesgo.estado_modelo(),
        "modo": "experimental con seguridad RBAC",
    }


@app.get("/api/v1/usuarios", dependencies=[Depends(verificar_directivo)])
def listar_usuarios():
    with obtener_conexion() as conexion:
        filas = conexion.execute(
            "SELECT id_usuario, correo, nombre_completo, rol, aula, activo FROM usuarios ORDER BY nombre_completo"
        ).fetchall()
        return [fila_a_dict(fila) for fila in filas]


@app.post("/api/v1/usuarios", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verificar_directivo)])
def crear_usuario(datos: UsuarioCrear):
    try:
        correo = validaciones.normalizar_correo(datos.correo)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with closing(obtener_conexion()) as conexion_aula:
        _exigir_aula_del_catalogo(conexion_aula, datos.aula)  # un aula escrita distinta dejaría al docente sin estudiantes
    try:
        seguridad.validar_politica(datos.password, correo)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                "INSERT INTO usuarios (correo, nombre_completo, rol, aula, password_hash, activo, debe_cambiar) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (correo, datos.nombre_completo.strip(), datos.rol, datos.aula, _hash_password(datos.password), int(datos.debe_cambiar)),
            )
            fila = conexion.execute(
                "SELECT id_usuario, correo, nombre_completo, rol, aula, activo FROM usuarios WHERE id_usuario = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return fila_a_dict(fila)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo.") from exc


@app.patch("/api/v1/usuarios/{id_usuario}", dependencies=[Depends(verificar_directivo)])
def actualizar_usuario(id_usuario: int, datos: UsuarioActualizar, request: Request):
    cambios = datos.model_dump(exclude_unset=True) if hasattr(datos, "model_dump") else datos.dict(exclude_unset=True)
    if not cambios:
        raise HTTPException(status_code=400, detail="Envía al menos un campo para actualizar.")
    with obtener_conexion() as conexion:
        actual = conexion.execute("SELECT rol, activo, aula, nombre_completo FROM usuarios WHERE id_usuario = ?", (id_usuario,)).fetchone()
        if actual is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        if cambios.get("aula"):
            _exigir_aula_del_catalogo(conexion, cambios["aula"])
        _marcar_auditoria(request, detalle=f"usuario={id_usuario} {_cambios_antes_despues(actual, cambios)}")
        quita_directivo = actual["rol"] == "directivo" and actual["activo"] == 1 and (
            cambios.get("rol", "directivo") != "directivo" or cambios.get("activo", 1) == 0
        )
        if quita_directivo:
            otros = conexion.execute(
                "SELECT COUNT(*) FROM usuarios WHERE rol = 'directivo' AND activo = 1 AND id_usuario != ?", (id_usuario,)
            ).fetchone()[0]
            if otros == 0:
                raise HTTPException(status_code=409, detail="No se puede quitar o desactivar al último directivo activo.")
        asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
        if "rol" in cambios or "activo" in cambios:
            asignaciones += ", token_version = token_version + 1"  # cierra las sesiones abiertas de esa cuenta
        valores = list(cambios.values()) + [id_usuario]
        conexion.execute(f"UPDATE usuarios SET {asignaciones} WHERE id_usuario = ?", valores)
        fila = conexion.execute(
            "SELECT id_usuario, correo, nombre_completo, rol, aula, activo FROM usuarios WHERE id_usuario = ?",
            (id_usuario,),
        ).fetchone()
        return fila_a_dict(fila)


@app.post("/api/v1/usuarios/{id_usuario}/restablecer-password")
def restablecer_password(id_usuario: int, request: Request, directivo: dict = Depends(verificar_directivo)):
    _marcar_auditoria(request, detalle=f"usuario={id_usuario} restablecimiento de contraseña")
    """Genera una clave temporal (se muestra una sola vez), cierra las sesiones de esa cuenta y exige cambiarla."""
    if int(directivo["sub"]) == id_usuario:
        raise HTTPException(status_code=400, detail="Para cambiar tu propia contraseña usa «Cambiar contraseña».")
    temporal = seguridad.contrasena_temporal()
    with obtener_conexion() as conexion:
        cursor = conexion.execute(
            "UPDATE usuarios SET password_hash = ?, debe_cambiar = 1, token_version = token_version + 1 WHERE id_usuario = ?",
            (seguridad.hash_password(temporal), id_usuario),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    return {"id_usuario": id_usuario, "password_temporal": temporal, "debe_cambiar": True}


class ConsultaDni(BaseModel):
    dni: str = Field(min_length=1, max_length=20)


_HTTP_RENIEC = {
    "ok": 200, "no_existe": 404, "formato": 422, "limite": 429,
    "no_configurado": 503, "clave_invalida": 502, "inalcanzable": 502, "error": 502,
}


@app.post("/api/v1/personas/validar-dni")
def validar_dni_reniec(consulta: ConsultaDni, request: Request, directivo: dict = Depends(verificar_directivo)):
    """Consulta RENIEC (vía Scrall) para comprobar un DNI y devolver nombres y apellidos. Solo directivos.

    La bitácora anota que se hizo la consulta, pero NO el número consultado.
    """
    _marcar_auditoria(request, detalle="verificación de DNI en RENIEC")
    resultado = reniec.consultar_dni(consulta.dni)
    codigo = _HTTP_RENIEC.get(resultado.estado, 502)
    if resultado.estado == "ok":
        return {"valido": True, "mensaje": resultado.mensaje, "datos": resultado.datos}
    cabeceras = {"Retry-After": str(resultado.reintentar_en)} if resultado.reintentar_en else None
    raise HTTPException(status_code=codigo, detail=resultado.mensaje, headers=cabeceras)


def _exigir_aula_del_catalogo(conexion, aula: Optional[str]) -> None:
    """Si la institución ya creó sus aulas, un estudiante solo puede asignarse a una de ellas (sin catálogo, texto libre)."""
    if aula and catalogo.hay_catalogo(conexion) and not catalogo.aula_existe(conexion, aula):
        raise HTTPException(status_code=422, detail=f"El aula «{aula}» no existe. Créala primero en «Estudiantes → Aulas y materias» o elige una de la lista.")


@app.post("/api/v1/estudiantes", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verificar_directivo)])
def crear_estudiante(datos: EstudianteCrear):
    try:
        with obtener_conexion() as conexion:
            if datos.dni and conexion.execute("SELECT 1 FROM estudiantes WHERE dni = ?", (datos.dni,)).fetchone():
                raise HTTPException(status_code=409, detail="El DNI ya está registrado.")
            _exigir_aula_del_catalogo(conexion, datos.aula)
            id_nuevo = None
            for _ in range(5):  # el ID automático puede chocar si dos directivos registran a la vez: se recalcula
                id_nuevo = datos.id_estudiante or catalogo.siguiente_id_estudiante(conexion)
                try:
                    conexion.execute(
                        """INSERT INTO estudiantes
                        (id_estudiante, dni, nombre_completo, aula, telefono_apoderado)
                        VALUES (?, ?, ?, ?, ?)""",
                        (id_nuevo, datos.dni, datos.nombre_completo.strip(), datos.aula, datos.telefono_apoderado),
                    )
                    break
                except sqlite3.IntegrityError:
                    if datos.id_estudiante:
                        raise
            else:
                raise HTTPException(status_code=409, detail="No se pudo asignar un ID automático. Vuelve a intentarlo.")
            fila = conexion.execute(
                "SELECT id_estudiante, dni, nombre_completo, aula, riesgo_desercion, riesgo_reprobacion, is_synced FROM estudiantes WHERE id_estudiante = ?",
                (id_nuevo,),
            ).fetchone()
            return fila_a_dict(fila)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="El ID del estudiante o el DNI ya existe.") from exc


# ----------------------------------------------------------------------------- aulas, grados y mallas
class AulasCrear(BaseModel):
    grado: str
    secciones: list[str] = Field(min_length=1, max_length=catalogo.MAX_SECCIONES_POR_GRADO)

    @field_validator("grado", mode="before")
    @classmethod
    def _validar_grado(cls, valor):
        return catalogo.normalizar_grado(valor)

    @field_validator("secciones", mode="before")
    @classmethod
    def _validar_secciones(cls, valor):
        if not isinstance(valor, list):
            raise ValueError("Envía una lista de secciones.")
        vistas = list(dict.fromkeys(catalogo.normalizar_seccion(s) for s in valor))
        return vistas


class MateriaGrado(BaseModel):
    grado: str
    materia: str

    @field_validator("grado", mode="before")
    @classmethod
    def _validar_grado(cls, valor):
        return catalogo.normalizar_grado(valor)

    @field_validator("materia", mode="before")
    @classmethod
    def _validar_materia(cls, valor):
        return catalogo.normalizar_materia(valor)


@app.get("/api/v1/aulas", summary="Aulas con sus materias (un docente solo ve la suya)")
def listar_aulas(usuario_actual: dict = Depends(verificar_token)):
    with closing(obtener_conexion()) as conexion:
        usuario = _usuario_vigente(conexion, usuario_actual)
        if usuario["rol"] == "docente":
            if not usuario["aula"]:
                return []
            return catalogo.listar_aulas(conexion, solo_aula=usuario["aula"])
        return catalogo.listar_aulas(conexion)


@app.get("/api/v1/grados", summary="Grados con sus secciones y su malla curricular", dependencies=[Depends(verificar_directivo)])
def listar_grados():
    with closing(obtener_conexion()) as conexion:
        return catalogo.listar_grados(conexion)


@app.post("/api/v1/aulas", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verificar_directivo)])
def crear_aulas(datos: AulasCrear):
    """Crea una aula por cada sección del grado. Las materias del grado las heredan todas sus secciones."""
    with obtener_conexion() as conexion:
        try:
            creadas, existentes = catalogo.crear_aulas(conexion, datos.grado, datos.secciones)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"creadas": creadas, "ya_existentes": existentes}


@app.delete("/api/v1/aulas", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verificar_directivo)])
def eliminar_aula(nombre: str = Query(min_length=1, max_length=50)):
    with obtener_conexion() as conexion:
        resultado = catalogo.eliminar_aula(conexion, nombre)
    if resultado == "no_existe":
        raise HTTPException(status_code=404, detail="El aula no existe.")
    if resultado == "con_estudiantes":
        raise HTTPException(status_code=409, detail="El aula tiene estudiantes. Muévelos a otra aula antes de borrarla.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/grados/materias", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verificar_directivo)])
def agregar_materia_a_grado(datos: MateriaGrado):
    with obtener_conexion() as conexion:
        materia, nueva = catalogo.agregar_materia(conexion, datos.grado, datos.materia)
    return {"grado": datos.grado, "materia": materia, "nueva": nueva}


@app.delete("/api/v1/grados/materias", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verificar_directivo)])
def quitar_materia_de_grado(grado: str = Query(min_length=1, max_length=40), materia: str = Query(min_length=1, max_length=120)):
    with obtener_conexion() as conexion:
        if not catalogo.quitar_materia(conexion, grado, materia):
            raise HTTPException(status_code=404, detail="Esa materia no está en la malla del grado.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/estudiantes")
def listar_estudiantes(
    request: Request,
    aula: Optional[str] = Query(default=None, max_length=50),
    limite: int = Query(default=100, ge=1, le=500),
    desplazamiento: int = Query(default=0, ge=0),
    usuario_actual: dict = Depends(verificar_token)
):
    consulta = "SELECT id_estudiante, dni, nombre_completo, aula, riesgo_desercion, riesgo_reprobacion, is_synced FROM estudiantes"
    parametros = []
    with obtener_conexion() as conexion:
        usuario = _usuario_vigente(conexion, usuario_actual)
        if usuario["rol"] == "docente":
            if not usuario["aula"]:
                return {"items": [], "limite": limite, "desplazamiento": desplazamiento}
            consulta += " WHERE aula = ?"
            parametros.append(usuario["aula"])
        elif aula:
            try:
                aula = validaciones.normalizar_aula(aula)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            consulta += " WHERE aula = ?"
            parametros.append(aula)
        consulta += " ORDER BY nombre_completo LIMIT ? OFFSET ?"
        parametros.extend([limite, desplazamiento])
        filas = conexion.execute(consulta, parametros).fetchall()
        es_docente = usuario["rol"] == "docente"
        # El docente ve a su aula sin DNI: lo necesita menos que el directivo y es el dato más sensible del listado.
        con_dni = "sin DNI" if es_docente else "con DNI"
        _marcar_auditoria(request, detalle=f"listado de {len(filas)} estudiantes {con_dni}: " + ",".join(f["id_estudiante"] for f in filas)[:230])
        items = [fila_a_dict(fila) for fila in filas]
        if es_docente:
            for item in items:
                item.pop("dni", None)
        return {"items": items, "limite": limite, "desplazamiento": desplazamiento}


class ExportacionRegistro(BaseModel):
    recurso: str = Field(min_length=1, max_length=40)
    filas: int = Field(ge=0, le=100000)


@app.post("/api/v1/exportaciones", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verificar_directivo)])
def registrar_exportacion(datos: ExportacionRegistro, request: Request):
    """Deja en la bitácora que un directivo exportó un listado (el archivo se genera en el navegador)."""
    recurso = "".join(c for c in datos.recurso if c.isalnum() or c in " _-")[:40]
    _marcar_auditoria(request, detalle=f"exportación de {datos.filas} filas de {recurso}")


@app.get("/api/v1/estudiantes/{id_estudiante}", dependencies=[Depends(acceso_estudiante)])
def obtener_estudiante(id_estudiante: str):
    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT id_estudiante, dni, nombre_completo, aula, telefono_apoderado, riesgo_desercion, riesgo_reprobacion, is_synced FROM estudiantes WHERE id_estudiante = ?",
            (id_estudiante,),
        ).fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
    return fila_a_dict(fila)


@app.patch("/api/v1/estudiantes/{id_estudiante}", dependencies=[Depends(verificar_directivo)])
def actualizar_estudiante(id_estudiante: str, datos: EstudianteActualizar, request: Request):
    """Solo directivos: un docente podría mover a un estudiante fuera de su vista o hacia el aula de otro docente."""
    cambios = datos.model_dump(exclude_unset=True) if hasattr(datos, "model_dump") else datos.dict(exclude_unset=True)
    cambios = {k: v.strip() if isinstance(v, str) else v for k, v in cambios.items()}
    if not cambios:
        raise HTTPException(status_code=400, detail="Envía al menos un campo para actualizar.")
    asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
    valores = list(cambios.values()) + [id_estudiante]
    with obtener_conexion() as conexion:
        if cambios.get("aula"):
            _exigir_aula_del_catalogo(conexion, cambios["aula"])
        actual = conexion.execute("SELECT nombre_completo, aula, telefono_apoderado FROM estudiantes WHERE id_estudiante = ?", (id_estudiante,)).fetchone()
        if actual is not None:  # queda en la bitácora qué cambió (sin el teléfono completo)
            partes = []
            visibles = {k: v for k, v in cambios.items() if k in ("nombre_completo", "aula")}
            if visibles:
                partes.append(_cambios_antes_despues(actual, visibles))
            if "telefono_apoderado" in cambios:
                partes.append("telefono_apoderado actualizado")
            _marcar_auditoria(request, id_estudiante, "; ".join(partes))
        cursor = conexion.execute(f"UPDATE estudiantes SET {asignaciones}, is_synced = 0 WHERE id_estudiante = ?", valores)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
        fila = conexion.execute(
            "SELECT id_estudiante, dni, nombre_completo, aula, riesgo_desercion, riesgo_reprobacion, is_synced FROM estudiantes WHERE id_estudiante = ?",
            (id_estudiante,),
        ).fetchone()
        return fila_a_dict(fila)


@app.delete("/api/v1/estudiantes/{id_estudiante}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verificar_directivo)])
def eliminar_estudiante(id_estudiante: str):
    with obtener_conexion() as conexion:
        existe = conexion.execute("SELECT 1 FROM estudiantes WHERE id_estudiante = ?", (id_estudiante,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
        conexion.execute("DELETE FROM calificaciones WHERE id_estudiante = ?", (id_estudiante,))
        conexion.execute("DELETE FROM asistencias WHERE id_estudiante = ?", (id_estudiante,))
        conexion.execute("DELETE FROM estudiantes WHERE id_estudiante = ?", (id_estudiante,))
        # Pendiente de borrar también en Firestore; el SyncWorker (o `python -m api.sync`) lo completa y lo reintenta.
        conexion.execute("INSERT OR IGNORE INTO eliminaciones_nube (id_estudiante) VALUES (?)", (id_estudiante,))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/calificaciones", status_code=status.HTTP_201_CREATED)
def crear_calificacion(datos: CalificacionCrear, request: Request, usuario_actual: dict = Depends(verificar_token)):
    _marcar_auditoria(request, datos.id_estudiante)
    try:
        with obtener_conexion() as conexion:
            _asegurar_acceso_estudiante(conexion, datos.id_estudiante, usuario_actual)
            curso = validaciones.unificar_curso(conexion, datos.curso_modulo)  # «matematica» -> «Matemática» si ya existe así
            cursor = conexion.execute(
                "INSERT INTO calificaciones (id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion) VALUES (?, ?, ?, ?)",
                (datos.id_estudiante, curso, datos.nota_obtenida, datos.periodo_evaluacion),
            )
            fila = conexion.execute(
                "SELECT id_calificacion, id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion, is_synced FROM calificaciones WHERE id_calificacion = ?",
                (cursor.lastrowid,),
            ).fetchone()
            _reevaluar_riesgo(conexion, datos.id_estudiante)
            return fila_a_dict(fila)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="No existe el estudiante indicado o la nota no es válida.") from exc


@app.get("/api/v1/estudiantes/{id_estudiante}/calificaciones", dependencies=[Depends(acceso_estudiante)])
def listar_calificaciones(id_estudiante: str):
    with obtener_conexion() as conexion:
        existe = conexion.execute("SELECT 1 FROM estudiantes WHERE id_estudiante = ?", (id_estudiante,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
        filas = conexion.execute(
            "SELECT id_calificacion, id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion, is_synced FROM calificaciones WHERE id_estudiante = ? ORDER BY periodo_evaluacion, curso_modulo",
            (id_estudiante,),
        ).fetchall()
        return [fila_a_dict(fila) for fila in filas]


@app.post("/api/v1/asistencias", status_code=status.HTTP_201_CREATED)
def crear_asistencia(datos: AsistenciaCrear, request: Request, usuario_actual: dict = Depends(verificar_token)):
    _marcar_auditoria(request, datos.id_estudiante)
    try:
        with obtener_conexion() as conexion:
            _asegurar_acceso_estudiante(conexion, datos.id_estudiante, usuario_actual)
            existe = conexion.execute("SELECT 1 FROM estudiantes WHERE id_estudiante = ?", (datos.id_estudiante,)).fetchone()
            if existe is None:
                raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
            duplicada = conexion.execute(
                "SELECT 1 FROM asistencias WHERE id_estudiante = ? AND fecha = ?",
                (datos.id_estudiante, datos.fecha.isoformat()),
            ).fetchone()
            if duplicada:
                raise HTTPException(status_code=409, detail="Ya hay una asistencia registrada para esa fecha.")
            cursor = conexion.execute(
                "INSERT INTO asistencias (id_estudiante, fecha, estado_asistencia) VALUES (?, ?, ?)",
                (datos.id_estudiante, datos.fecha.isoformat(), datos.estado_asistencia),
            )
            fila = conexion.execute(
                "SELECT id_asistencia, id_estudiante, fecha, estado_asistencia, is_synced FROM asistencias WHERE id_asistencia = ?",
                (cursor.lastrowid,),
            ).fetchone()
            _reevaluar_riesgo(conexion, datos.id_estudiante)
            return fila_a_dict(fila)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="No existe el estudiante o ya hay una asistencia registrada para esa fecha.") from exc


@app.get("/api/v1/estudiantes/{id_estudiante}/asistencias", dependencies=[Depends(acceso_estudiante)])
def listar_asistencias(id_estudiante: str, desde: Optional[date] = None, hasta: Optional[date] = None):
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha 'desde' no puede ser posterior a 'hasta'.")
    filtros = ["id_estudiante = ?"]
    parametros = [id_estudiante]
    if desde:
        filtros.append("fecha >= ?")
        parametros.append(desde.isoformat())
    if hasta:
        filtros.append("fecha <= ?")
        parametros.append(hasta.isoformat())
    with obtener_conexion() as conexion:
        existe = conexion.execute("SELECT 1 FROM estudiantes WHERE id_estudiante = ?", (id_estudiante,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
        filas = conexion.execute(
            "SELECT id_asistencia, id_estudiante, fecha, estado_asistencia, is_synced FROM asistencias WHERE " + " AND ".join(filtros) + " ORDER BY fecha DESC",
            parametros,
        ).fetchall()
        return [fila_a_dict(fila) for fila in filas]


def _cargar_registro_hijo(conexion, tabla: str, columna_id: str, id_registro: int, payload: dict):
    """Fila de una nota o asistencia, comprobando el acceso por aula.

    Si no existe o es de otra aula la respuesta es la misma (404), para no revelar qué ids existen.
    """
    fila = conexion.execute(f"SELECT * FROM {tabla} WHERE {columna_id} = ?", (id_registro,)).fetchone()
    if fila is not None:
        try:
            _asegurar_acceso_estudiante(conexion, fila["id_estudiante"], payload)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            fila = None
    if fila is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    return fila


def _auditar_correccion(conexion, accion: str, payload: dict, request: Request, estado: int, id_estudiante: str, detalle: str) -> None:
    """Deja en la bitácora qué se corrigió o borró, sobre qué estudiante y los valores antes y después."""
    _marcar_auditoria(request, id_estudiante, detalle)
    usuario = _usuario_vigente(conexion, payload)
    auditoria.registrar(
        conexion, accion, id_usuario=usuario["id_usuario"], rol=usuario["rol"],
        ip=request.client.host if request.client else None, metodo=request.method, ruta=request.url.path,
        id_estudiante=id_estudiante, estado_http=estado, detalle=detalle,
    )


def _pedir_borrado_en_nube(conexion, tabla: str, id_estudiante: str, id_documento: str) -> None:
    conexion.execute(
        "INSERT OR IGNORE INTO eliminaciones_nube_hijas (tabla, id_estudiante, id_documento) VALUES (?, ?, ?)",
        (tabla, id_estudiante, id_documento),
    )


@app.patch("/api/v1/calificaciones/{id_calificacion}")
def actualizar_calificacion(id_calificacion: int, datos: CalificacionActualizar, request: Request, usuario_actual: dict = Depends(verificar_token)):
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios or any(v is None for v in cambios.values()):
        raise HTTPException(status_code=400, detail="Envía al menos un campo con valor para actualizar.")
    with obtener_conexion() as conexion:
        actual = _cargar_registro_hijo(conexion, "calificaciones", "id_calificacion", id_calificacion, usuario_actual)
        if "curso_modulo" in cambios:
            cambios["curso_modulo"] = validaciones.unificar_curso(conexion, cambios["curso_modulo"])
        asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)  # los campos salen del modelo Pydantic, no del cliente
        conexion.execute(
            f"UPDATE calificaciones SET {asignaciones}, is_synced = 0 WHERE id_calificacion = ?",
            list(cambios.values()) + [id_calificacion],
        )
        fila = conexion.execute(
            "SELECT id_calificacion, id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion, is_synced FROM calificaciones WHERE id_calificacion = ?",
            (id_calificacion,),
        ).fetchone()
        _reevaluar_riesgo(conexion, actual["id_estudiante"])
        _auditar_correccion(
            conexion, "correccion_nota", usuario_actual, request, 200, actual["id_estudiante"],
            f"id_calificacion={id_calificacion} {_cambios_antes_despues(actual, cambios)}",
        )
        return fila_a_dict(fila)


@app.delete("/api/v1/calificaciones/{id_calificacion}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_calificacion(id_calificacion: int, request: Request, usuario_actual: dict = Depends(verificar_token)):
    with obtener_conexion() as conexion:
        actual = _cargar_registro_hijo(conexion, "calificaciones", "id_calificacion", id_calificacion, usuario_actual)
        conexion.execute("DELETE FROM calificaciones WHERE id_calificacion = ?", (id_calificacion,))
        _pedir_borrado_en_nube(conexion, "calificaciones", actual["id_estudiante"], str(id_calificacion))
        _reevaluar_riesgo(conexion, actual["id_estudiante"])
        _auditar_correccion(
            conexion, "eliminacion_nota", usuario_actual, request, 204, actual["id_estudiante"],
            f"id_calificacion={id_calificacion} curso={actual['curso_modulo']} periodo={actual['periodo_evaluacion']} nota={actual['nota_obtenida']}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.patch("/api/v1/asistencias/{id_asistencia}")
def actualizar_asistencia(id_asistencia: int, datos: AsistenciaActualizar, request: Request, usuario_actual: dict = Depends(verificar_token)):
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios or any(v is None for v in cambios.values()):
        raise HTTPException(status_code=400, detail="Envía al menos un campo con valor para actualizar.")
    if "fecha" in cambios:
        cambios["fecha"] = cambios["fecha"].isoformat()
    try:
        with obtener_conexion() as conexion:
            actual = _cargar_registro_hijo(conexion, "asistencias", "id_asistencia", id_asistencia, usuario_actual)
            if "fecha" in cambios and cambios["fecha"] != actual["fecha"]:
                duplicada = conexion.execute(
                    "SELECT 1 FROM asistencias WHERE id_estudiante = ? AND fecha = ? AND id_asistencia <> ?",
                    (actual["id_estudiante"], cambios["fecha"], id_asistencia),
                ).fetchone()
                if duplicada:
                    raise HTTPException(status_code=409, detail="Ya hay una asistencia registrada para esa fecha.")
                # En Firestore el documento se llama como la fecha: el de la fecha anterior hay que borrarlo.
                _pedir_borrado_en_nube(conexion, "asistencias", actual["id_estudiante"], actual["fecha"])
            asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
            conexion.execute(
                f"UPDATE asistencias SET {asignaciones}, is_synced = 0 WHERE id_asistencia = ?",
                list(cambios.values()) + [id_asistencia],
            )
            fila = conexion.execute(
                "SELECT id_asistencia, id_estudiante, fecha, estado_asistencia, is_synced FROM asistencias WHERE id_asistencia = ?",
                (id_asistencia,),
            ).fetchone()
            _reevaluar_riesgo(conexion, actual["id_estudiante"])
            _auditar_correccion(
                conexion, "correccion_asistencia", usuario_actual, request, 200, actual["id_estudiante"],
                f"id_asistencia={id_asistencia} {_cambios_antes_despues(actual, cambios)}",
            )
            return fila_a_dict(fila)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Ya hay una asistencia registrada para esa fecha.") from exc


@app.delete("/api/v1/asistencias/{id_asistencia}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_asistencia(id_asistencia: int, request: Request, usuario_actual: dict = Depends(verificar_token)):
    with obtener_conexion() as conexion:
        actual = _cargar_registro_hijo(conexion, "asistencias", "id_asistencia", id_asistencia, usuario_actual)
        conexion.execute("DELETE FROM asistencias WHERE id_asistencia = ?", (id_asistencia,))
        _pedir_borrado_en_nube(conexion, "asistencias", actual["id_estudiante"], actual["fecha"])
        _reevaluar_riesgo(conexion, actual["id_estudiante"])
        _auditar_correccion(
            conexion, "eliminacion_asistencia", usuario_actual, request, 204, actual["id_estudiante"],
            f"id_asistencia={id_asistencia} fecha={actual['fecha']} estado={actual['estado_asistencia']}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ejecutar_importacion(tipo: str, nombre_archivo: str, contenido: bytes, simular: bool, payload: dict, ip: Optional[str]) -> dict:
    """Trabajo síncrono de la carga masiva (se ejecuta en un hilo para no bloquear el servidor)."""
    with closing(obtener_conexion()) as conexion:
        usuario = _usuario_vigente(conexion, payload)
        if tipo in importacion.TIPOS_SOLO_DIRECTIVO and usuario["rol"] != "directivo":
            raise HTTPException(status_code=403, detail="Solo un directivo puede importar estudiantes y aulas.")
        try:
            _, filas = importacion.leer_tabla(contenido, nombre_archivo, tipo)
        except importacion.ErrorArchivo as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            informe = importacion.importar(
                conexion, tipo, filas, {"rol": usuario["rol"], "aula": usuario["aula"]}, simular=simular
            )
        except sqlite3.IntegrityError as exc:
            conexion.rollback()
            raise HTTPException(status_code=409, detail="Los datos cambiaron mientras se importaba. Vuelve a intentarlo.") from exc
        afectados = informe.pop("_afectados", [])
        if informe["aplicado"] and tipo not in importacion.TIPOS_SOLO_DIRECTIVO:
            for id_estudiante in afectados:
                _reevaluar_riesgo(conexion, id_estudiante)
            conexion.commit()  # evaluar_estudiante no confirma por sí mismo
        auditoria.registrar(
            conexion, "escritura", id_usuario=usuario["id_usuario"], rol=usuario["rol"], ip=ip, metodo="POST",
            ruta=f"/api/v1/importaciones/{tipo}", estado_http=200,
            detalle=f"importacion tipo={tipo} simulacion={int(simular)} filas={informe['total_filas']} "
                    f"nuevas={informe['nuevas']} errores={informe['errores_total']} aplicado={int(informe['aplicado'])}",
        )
        return informe


@app.post("/api/v1/importaciones/{tipo}", summary="Carga masiva desde CSV o Excel (por defecto solo valida: simular=true)")
async def importar_archivo(
    tipo: Literal["estudiantes", "calificaciones", "asistencias", "aulas"],
    request: Request,
    archivo: UploadFile = File(...),
    simular: bool = Query(default=True, description="true: solo valida y devuelve el informe. false: guarda si no hay errores."),
    usuario_actual: dict = Depends(verificar_token),
):
    """Todo o nada: si hay algún error no se guarda nada. Los directivos importan estudiantes, notas y asistencias;
    los docentes solo notas y asistencias de su aula."""
    contenido = await archivo.read(importacion.MAX_BYTES + 1)
    if len(contenido) > importacion.MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"El archivo supera el máximo de {importacion.MAX_BYTES // (1024 * 1024)} MB.")
    ip = request.client.host if request.client else None
    return await run_in_threadpool(_ejecutar_importacion, tipo, archivo.filename or "", contenido, simular, usuario_actual, ip)


@app.post("/api/v1/alertas", status_code=status.HTTP_201_CREATED)
def crear_alerta(datos: AlertaCrear, request: Request, usuario_actual: dict = Depends(verificar_token)):
    _marcar_auditoria(request, datos.id_estudiante)
    with obtener_conexion() as conexion:
        _asegurar_acceso_estudiante(conexion, datos.id_estudiante, usuario_actual)
        existe = conexion.execute("SELECT 1 FROM estudiantes WHERE id_estudiante = ?", (datos.id_estudiante,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
        cursor = conexion.execute(
            """INSERT INTO alertas (id_estudiante, tipo_alerta, nivel_riesgo, descripcion, version_modelo, probabilidad)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (datos.id_estudiante, datos.tipo_alerta, datos.nivel_riesgo, datos.descripcion.strip(), "manual", None),
        )
        fila = conexion.execute("SELECT * FROM alertas WHERE id_alerta = ?", (cursor.lastrowid,)).fetchone()
        return fila_a_dict(fila)


@app.get("/api/v1/alertas")
def listar_alertas(
    id_estudiante: Optional[str] = None,
    estado: Optional[Literal["pendiente", "en_seguimiento", "resuelta", "descartada"]] = None,
    nivel_riesgo: Optional[Literal["bajo", "medio", "alto"]] = None,
    limite: int = Query(default=100, ge=1, le=500),
    usuario_actual: dict = Depends(verificar_token),
):
    filtros = []
    parametros = []
    if id_estudiante:
        filtros.append("a.id_estudiante = ?")
        parametros.append(id_estudiante)
    if estado:
        filtros.append("a.estado = ?")
        parametros.append(estado)
    if nivel_riesgo:
        filtros.append("a.nivel_riesgo = ?")
        parametros.append(nivel_riesgo)
    with obtener_conexion() as conexion:
        usuario = _usuario_vigente(conexion, usuario_actual)
        consulta = "SELECT a.* FROM alertas a"
        if usuario["rol"] == "docente":
            if not usuario["aula"]:
                return []
            consulta += " JOIN estudiantes e ON e.id_estudiante = a.id_estudiante"
            filtros.append("e.aula = ?")
            parametros.append(usuario["aula"])
        if filtros:
            consulta += " WHERE " + " AND ".join(filtros)
        consulta += " ORDER BY a.fecha_creacion DESC, a.id_alerta DESC LIMIT ?"
        parametros.append(limite)
        filas = conexion.execute(consulta, parametros).fetchall()
        return [fila_a_dict(fila) for fila in filas]


@app.patch("/api/v1/alertas/{id_alerta}")
def actualizar_alerta(id_alerta: int, datos: AlertaActualizar, request: Request, usuario_actual: dict = Depends(verificar_token)):
    with obtener_conexion() as conexion:
        alerta = conexion.execute("SELECT id_estudiante, estado FROM alertas WHERE id_alerta = ?", (id_alerta,)).fetchone()
        if alerta is None:
            raise HTTPException(status_code=404, detail="Alerta no encontrada.")
        _asegurar_acceso_estudiante(conexion, alerta["id_estudiante"], usuario_actual)
        _marcar_auditoria(request, alerta["id_estudiante"], f"id_alerta={id_alerta} estado: {alerta['estado']}->{datos.estado}")
        conexion.execute("UPDATE alertas SET estado = ? WHERE id_alerta = ?", (datos.estado, id_alerta))
        return fila_a_dict(conexion.execute("SELECT * FROM alertas WHERE id_alerta = ?", (id_alerta,)).fetchone())


@app.post("/api/v1/intervenciones", status_code=status.HTTP_201_CREATED)
def crear_intervencion(datos: IntervencionCrear, request: Request, usuario_actual: dict = Depends(verificar_token)):
    _marcar_auditoria(request, datos.id_estudiante)
    with obtener_conexion() as conexion:
        tutor = _asegurar_acceso_estudiante(conexion, datos.id_estudiante, usuario_actual)["nombre_completo"]
        if conexion.execute("SELECT 1 FROM estudiantes WHERE id_estudiante = ?", (datos.id_estudiante,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
        if datos.id_alerta is not None:
            alerta = conexion.execute("SELECT id_estudiante FROM alertas WHERE id_alerta = ?", (datos.id_alerta,)).fetchone()
            if alerta is None:
                raise HTTPException(status_code=404, detail="Alerta no encontrada.")
            if alerta["id_estudiante"] != datos.id_estudiante:
                raise HTTPException(status_code=409, detail="La alerta no pertenece al estudiante indicado.")
        if datos.proxima_revision and datos.proxima_revision < datos.fecha_intervencion:
            raise HTTPException(status_code=422, detail="La próxima revisión no puede ser anterior a la intervención.")
        cursor = conexion.execute(
            """INSERT INTO intervenciones
            (id_estudiante, id_alerta, tutor, tipo_intervencion, descripcion, fecha_intervencion, resultado, proxima_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datos.id_estudiante, datos.id_alerta, tutor, datos.tipo_intervencion.strip(), datos.descripcion.strip(),
             datos.fecha_intervencion.isoformat(), datos.resultado, datos.proxima_revision.isoformat() if datos.proxima_revision else None),
        )
        fila = conexion.execute("SELECT * FROM intervenciones WHERE id_intervencion = ?", (cursor.lastrowid,)).fetchone()
        return fila_a_dict(fila)


@app.get("/api/v1/intervenciones")
def listar_intervenciones(
    id_estudiante: Optional[str] = None,
    id_alerta: Optional[int] = Query(default=None, ge=1),
    limite: int = Query(default=100, ge=1, le=500),
    usuario_actual: dict = Depends(verificar_token),
):
    filtros = []
    parametros = []
    if id_estudiante:
        filtros.append("i.id_estudiante = ?")
        parametros.append(id_estudiante)
    if id_alerta is not None:
        filtros.append("i.id_alerta = ?")
        parametros.append(id_alerta)
    with obtener_conexion() as conexion:
        usuario = _usuario_vigente(conexion, usuario_actual)
        consulta = "SELECT i.* FROM intervenciones i"
        if usuario["rol"] == "docente":
            if not usuario["aula"]:
                return []
            consulta += " JOIN estudiantes e ON e.id_estudiante = i.id_estudiante"
            filtros.append("e.aula = ?")
            parametros.append(usuario["aula"])
        if filtros:
            consulta += " WHERE " + " AND ".join(filtros)
        consulta += " ORDER BY i.fecha_intervencion DESC, i.id_intervencion DESC LIMIT ?"
        parametros.append(limite)
        filas = conexion.execute(consulta, parametros).fetchall()
        return [fila_a_dict(fila) for fila in filas]


@app.patch("/api/v1/intervenciones/{id_intervencion}")
def actualizar_intervencion(id_intervencion: int, datos: IntervencionActualizar, request: Request, usuario_actual: dict = Depends(verificar_token)):
    siguiente = datos.proxima_revision.isoformat() if datos.proxima_revision else None
    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT id_estudiante, fecha_intervencion FROM intervenciones WHERE id_intervencion = ?", (id_intervencion,)
        ).fetchone()
        if fila is None:
            raise HTTPException(status_code=404, detail="Intervención no encontrada.")
        _asegurar_acceso_estudiante(conexion, fila["id_estudiante"], usuario_actual)
        _marcar_auditoria(request, fila["id_estudiante"], f"id_intervencion={id_intervencion} resultado y proxima_revision actualizados")
        if siguiente and siguiente < fila["fecha_intervencion"]:
            raise HTTPException(status_code=422, detail="La próxima revisión no puede ser anterior a la intervención.")
        conexion.execute("UPDATE intervenciones SET resultado = ?, proxima_revision = ? WHERE id_intervencion = ?",
                         (datos.resultado.strip(), siguiente, id_intervencion))
        return fila_a_dict(conexion.execute("SELECT * FROM intervenciones WHERE id_intervencion = ?", (id_intervencion,)).fetchone())


@app.post("/api/v1/analitica/predecir", dependencies=[Depends(verificar_token)])
def analizar_riesgo_estudiante(datos: EstudianteData):
    modelo = modelo_activo()
    if modelo is None:
        raise HTTPException(status_code=503, detail="El modelo predictivo no está disponible. Ejecuta modelos/entrenamiento.py primero.")
    entrada = pd.DataFrame({"Notas_Detalladas": [datos.notas_promedio], "Registro_Asistencia": [datos.porcentaje_asistencia]})
    try:
        clase = int(modelo.predict(entrada)[0])
        probabilidad = None
        if hasattr(modelo, "predict_proba"):
            probabilidades = modelo.predict_proba(entrada)[0]
            clases = list(modelo.classes_)
            if 1 in clases:
                probabilidad = round(float(probabilidades[clases.index(1)]), 4)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=500, detail="No se pudo procesar la predicción.") from exc
    if clase == 1:
        alerta = "ALERTA_ROJA_DESERCION"
        descripcion = "El modelo experimental identifica señales de riesgo de deserción."
        accion = "Revisar el caso con el tutor y contrastar la predicción con el contexto del estudiante."
    else:
        alerta = "SIN_ALERTA_MODELO"
        descripcion = "El modelo experimental no clasificó el caso como riesgo alto."
        accion = "Mantener el seguimiento académico habitual; la ausencia de alerta no garantiza que no exista riesgo."
    return {
        "estado_analisis": "completado",
        "tipo_modelo": "experimental_no_validado",
        "prediccion_riesgo": alerta,
        "descripcion": descripcion,
        "probabilidad_estimada_riesgo": probabilidad,
        "accion_sugerida": accion,
        "nota_importante": "No usar esta predicción como decisión automática. El modelo actual se entrenó con datos sintéticos y requiere validación con datos reales autorizados.",
    }


def _error_http_riesgo(exc: "riesgo.RiesgoError") -> HTTPException:
    if isinstance(exc, riesgo.EstudianteNoEncontrado):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, riesgo.DatosInsuficientes):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, riesgo.ModeloNoDisponible):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/estudiantes/{id_estudiante}/evaluar-riesgo", dependencies=[Depends(acceso_estudiante)])
def evaluar_riesgo_estudiante(id_estudiante: str):
    try:
        with obtener_conexion() as conexion:
            return riesgo.evaluar_estudiante(conexion, id_estudiante, modelo_activo())
    except riesgo.RiesgoError as exc:
        raise _error_http_riesgo(exc) from exc


@app.post("/api/v1/analitica/evaluar-todos", dependencies=[Depends(verificar_directivo)])
def evaluar_riesgo_todos():
    try:
        with obtener_conexion() as conexion:
            return riesgo.evaluar_todos(conexion, modelo_activo())
    except riesgo.RiesgoError as exc:
        raise _error_http_riesgo(exc) from exc