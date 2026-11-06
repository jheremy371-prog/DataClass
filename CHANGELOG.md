# Cambios

Formato: lo más reciente arriba. Las versiones siguen la auditoría técnica del proyecto (H = alto, M = medio, N = nuevo, L = bajo).

## 1.10.2 — 6 de noviembre de 2026 (cierre de pendientes del informe v1.1)

### Seguridad y despliegue
- `.streamlit/config.toml`: Streamlit escucha solo en `127.0.0.1` (el único punto público debe ser Caddy).
- Nuevo `api/respaldo.py`: copia de seguridad **cifrada** (`python -m api.respaldo crear|verificar|restaurar`), con clave `DATACLASS_RESPALDO_CLAVE`. No sobrescribe una base existente. Las conexiones SQLite se cierran con `closing()`: en Windows `with sqlite3.connect()` no cierra el archivo y el directorio temporal quedaba bloqueado.
- Nuevo `.github/workflows/ci.yml`: pytest con cobertura, `pip-audit` y escaneo de secretos (gitleaks) en cada push y PR.
- `.gitignore`: se añaden `.ruff_cache/`, `.mypy_cache/`, `respaldos/` y `*.dcbak`. `empaquetar.py` los excluye y aplica los patrones de claves a cualquier extensión.

### Dependencias (resultado de `pip-audit`)
- `pillow` 12.3.0 → 13.0.0, `certifi` 2026.7.22 → 2026.10.18, `python-dotenv` 1.1.1 → 1.2.2.
- Pillow 13 exige `streamlit` 1.67.0 (la 1.66.0 pedía `pillow<13`), que también se actualiza. `pip check` sin conflictos y 337 pruebas pasan.

### Pruebas
- `tests/test_cobertura_endpoints.py`: recorre todas las rutas; ninguna responde sin sesión (salvo login y `/estado`) y un docente recibe 403 en todo lo reservado a directivos.
- `tests/test_valores_por_defecto_seguros.py`: fija modo demo, cookie persistente y `/docs` apagados por defecto.
- `tests/test_respaldo.py`: cifrado, restauración, clave incorrecta.

## 1.10.1 — 6 de noviembre de 2026 (H-01 del informe v1.1)

### Seguridad
- **H-01 · El token de sesión ya no se guarda en una cookie legible por JavaScript.** Por defecto la sesión vive solo en `st.session_state`; al recargar la página hay que iniciar sesión de nuevo. Una cookie escrita con JavaScript nunca puede ser `HttpOnly`, así que ante un XSS el token se podía robar. Si en el navegador queda la cookie `dc_token` de una versión anterior, se borra y no se usa. Quien acepte el riesgo puede volver al comportamiento anterior con `DATACLASS_SESION_PERSISTENTE=1`.
- Sin cambios en la API: la revocación por `jti`, el `token_version` y la expiración a las 8 h siguen igual.
- **Aviso:** `app.py` no tiene pruebas automáticas; verifica a mano en el navegador (inicia sesión, recarga la página y comprueba que `document.cookie` no incluye `dc_token`) y corre `python -m pytest` para confirmar que la suite sigue en verde.

## 1.10.0 — 30 de octubre de 2026 (Fases 1 y 2 del plan)

### Datos personales (H-03, M-08, H-02)
- **H-03 · Firestore minimizado.** A la nube solo salen un seudónimo del estudiante (HMAC-SHA256 con `DATACLASS_SEUDONIMO_CLAVE`), el aula, los niveles de riesgo y los datos académicos de notas y asistencias. **Ya no salen** el nombre, el DNI, el teléfono ni el ID real. Sin la clave no se envía nada; con `DATACLASS_SYNC_AUTO=1` y sin clave la API no arranca. Los borrados en la nube usan el mismo seudónimo. Ver `docs/CUMPLIMIENTO_LEY_29733.md`.
- **M-08 · El listado de estudiantes ya no devuelve el DNI a los docentes** (los directivos lo siguen viendo). La bitácora anota «con DNI» o «sin DNI».
- **M-08 · El dashboard ya no muestra «Sincronizados»** (lo reemplaza «Aulas») y las tablas ocultan la columna `is_synced`: con la nube apagada confundía con un modo sin conexión que aún no existe.
- **H-02 · Exportar el listado a CSV queda en la bitácora.** Es solo para directivos y se hace en dos pasos: «Preparar exportación» llama a `POST /api/v1/exportaciones` (registra recurso y cantidad de filas) y luego aparece «Descargar».

### Robustez (M-03)
- **El modelo se carga al arrancar el servidor (`lifespan`), no al importar el módulo.** Si no pasa la verificación SHA-256, la API arranca sin modelo.

### Pruebas
- Nuevo: `tests/test_fase1.py`. Actualizados a los IDs seudónimos: `test_sync.py`, `test_sync_lotes.py`, `test_eliminacion_nube.py`; `conftest.py` fija una clave de prueba.
- **Aviso:** estos cambios se escribieron sin poder ejecutar la suite; corre `python -m pytest` antes de darlos por buenos.

## 1.9.0 — 30 de octubre de 2026 (correcciones de la auditoría)

### Seguridad
- **N-01 · Cerrar sesión ahora invalida el token en el servidor.** Cada token lleva un identificador (`jti`); `POST /api/v1/auth/cerrar-sesion` lo agrega a `tokens_revocados` y deja de servir aunque no haya vencido. Solo cierra esa sesión (otros dispositivos de la misma cuenta siguen abiertos). Los vencidos se limpian solos. La interfaz llama a este endpoint desde ambos botones «Cerrar sesión».
- **N-01 · La cookie de sesión lleva `Secure`** cuando la página se sirve por HTTPS.
- **M-01 / N-03 · `PATCH /estudiantes/{id}` es solo para directivos.** Un docente ya no puede sacar a un estudiante de su vista ni pasarlo al aula de otro. El cambio de nombre o aula queda en la bitácora con el antes y el después (el teléfono se anota sin el número).
- **M-01 · Las alertas manuales ya no aceptan `version_modelo` ni `probabilidad`:** siempre quedan como «manual» y sin probabilidad, para que nadie las haga pasar por alertas del modelo. El tutor de una intervención es la cuenta que la registra (el campo `tutor` del cuerpo se ignora).
- **M-02 · El login fallido o bloqueado ya no guarda en la bitácora el texto escrito en el campo de usuario** (a veces es una contraseña tecleada en el campo equivocado).
- **M-03 · El modelo (`.pkl`) solo se carga si su SHA-256 coincide con `sha256_pkl` de `modelo_riesgo.json`.** Cualquier otro caso deja la API sin modelo y escribe el motivo en el log; ya no se capturan solo 4 tipos de error. `modelos/entrenamiento.py` escribe la huella al entrenar y `--sellar` la registra para un modelo existente. El modelo incluido ya viene sellado.
- **N-02 · `GET /auth/sesion` ya no se registra en la bitácora** (se llama en cada recarga).
- **N-04 · El aula de un docente se valida contra el catálogo** al crear o modificar la cuenta (con catálogo creado), y «Gestión de docentes» la elige de una lista.
- **Inactividad (M-08):** la interfaz cierra la sesión tras `DATACLASS_INACTIVIDAD_MIN` minutos (30 por defecto) sin interacción.
- **Correo y nombre más estrictos (L-04):** el correo debe tener forma `usuario@dominio.ext`; el nombre debe empezar con una letra.

### Datos
- **N-05 · Los IDs automáticos no se reutilizan.** Un contador (`secuencias`, actualizado por un trigger en cada alta) recuerda el mayor número usado de cada año, aunque se borre al estudiante.
- **M-04 · SQLite:** modo WAL, `synchronous = NORMAL`, `busy_timeout` de 10 s y versión de esquema en `PRAGMA user_version` con migraciones. Una base de una versión más nueva que el programa se rechaza con un mensaje claro.
- **Aviso:** con WAL aparecen `*.db-wal` y `*.db-shm` junto a la base. Contienen datos personales: ya están en `.gitignore` y fuera del ZIP de `empaquetar.py`. Para volver al modo clásico: `DATACLASS_SQLITE_WAL=0`.

### Despliegue (M-09)
- `deploy/Caddyfile`: tope de 10 MB por petición, `Permissions-Policy` y una política de contenido en modo «solo informar» (revisa la consola del navegador y, si no hay infracciones, pásala a `Content-Security-Policy`). El límite de tasa por IP queda documentado: requiere compilar Caddy con un módulo.

### Pruebas
- Nuevos: `tests/test_catalogo_api.py` (N-06), `tests/test_sesion_api.py`, `tests/test_esquema_y_modelo.py` y casos en `tests/test_validaciones.py`.
- `tests/test_acceso_aulas.py`: un docente que hace PATCH a un estudiante recibe ahora 403 (antes 404).

### Limpieza (L-01, L-02, L-03)
- Scripts antiguos movidos a `legacy/` (con `LEEME.md`); borrado el archivo vacío `python`.
- `requirements.txt` ahora es solo lo necesario para ejecutar; `requirements-dev.txt` (pytest) y `requirements-sync.txt` (Firebase). Python fijado en `.python-version`.

### Sigue pendiente
H-03 (decisión sobre Firestore), segundo factor para directivos, token corto con renovación, división de `api/main.py` en routers (L-05), paginación real (M-08), año lectivo y promoción (M-10) y reentrenar con datos reales (M-07).

## 1.8.1
Contraseñas con hash versionado y política mínima, `token_version`, bitácora de auditoría verificada, seguimiento de alertas e intervenciones. Ver `README_CONTINUACION.md`.
