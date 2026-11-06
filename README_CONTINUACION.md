# DataClass — versión 1.10.0

DataClass es un prototipo de seguimiento académico con FastAPI, SQLite y una interfaz Streamlit. Esta versión mejora la autenticación, las operaciones del frontend y la presentación visual con una identidad corporativa azul.

## Funcionalidades incluidas

- Gestión de estudiantes, calificaciones y asistencias.
- Registro y seguimiento de alertas e intervenciones.
- Inicio de sesión JWT con contraseñas almacenadas mediante PBKDF2-HMAC-SHA256.
- Protección de los endpoints de datos mediante token.
- Restricción de algunas operaciones administrativas al rol `directivo`.
- Interfaz Streamlit en azul corporativo, con dashboard, búsqueda, formularios e historial.
- El frontend envía el token y ya no sustituye los fallos de la API por estudiantes ficticios.
- Sincronización Firebase desactivada hasta configurar credenciales externas seguras.
- Semáforo de riesgo de deserción con alertas automáticas y perfil individual del estudiante (v1.6). **Hoy está apagado**: el modelo incluido es sintético (`sintetico: true`) y solo se activa con `DATACLASS_MODO_DEMO=1` (datos inventados) o al entrenar con datos reales.
- **ID automático** de estudiantes (`AAAA-0001`), que nunca se reutiliza aunque se borre a alguien.
- **Aulas por año y malla de materias** (Estudiantes → Aulas y materias), con carga masiva desde plantilla (`grado,secciones,materias`). Si ya existe el catálogo, un estudiante o un docente solo puede asignarse a un aula creada.
- **Sesión persistente** al recargar la página (cookie `dc_token`, 8 h) y página recordada en la URL (`?p=`, solo el nombre de la sección). Al cerrar sesión el token se invalida en el servidor; la sesión se cierra sola tras 30 min sin uso (`DATACLASS_INACTIVIDAD_MIN`).

## Novedades de la versión 1.6

> **Estado actual:** el semáforo descrito aquí está desactivado mientras el modelo sea sintético. Ver «Modelo de riesgo» más abajo y `CHANGELOG.md`.

**Semáforo de riesgo de deserción** (`api/riesgo.py`). A partir de la probabilidad P del modelo (0.0 a 1.0):

| Nivel | Condición | Acción |
|---|---|---|
| Bajo | P < 0.30 | Seguimiento habitual. |
| Medio | 0.30 ≤ P < 0.70 | Crea una alerta preventiva y sugiere tutoría breve. |
| Alto | P ≥ 0.70 | Crea una alerta de riesgo alto y sugiere revisar el caso con el tutor y contactar al apoderado. |

- El promedio de notas y el porcentaje de asistencia se calculan desde la base de datos. Asistió = presente + tardanza; las faltas justificadas no penalizan.
- Se evalúa automáticamente al registrar una nota o una asistencia, siempre que haya al menos 1 calificación y 5 registros de asistencia. Con menos datos el registro se guarda y el estudiante queda sin evaluar.
- No se duplican alertas: si ya existe una alerta abierta (pendiente o en seguimiento) del mismo nivel, no se crea otra.
- Endpoints nuevos: `POST /api/v1/estudiantes/{id}/evaluar-riesgo` (cualquier usuario autenticado) y `POST /api/v1/analitica/evaluar-todos` (solo directivos).
- Los avisos a apoderados (SMS, WhatsApp, correo) **todavía no se envían**: la alerta sugiere contactarlos, pero el contacto es manual.

**Perfil del estudiante** (menú lateral): búsqueda por nombre, ID o DNI; datos de contacto del apoderado; semáforo; promedio por curso, asistencia y alertas/intervenciones. Aún no admite fotografía.

**Dashboard:** botón *Recalcular semáforo* (directivos) y nuevo diseño visual (`.streamlit/config.toml` fuerza el tema claro; reinicia Streamlit tras copiarlo).

**Límites vigentes:** solo existe modelo de deserción; el riesgo de reprobación sigue sin calcularse automáticamente. El modelo se entrenó con 10 filas sintéticas, por lo que las probabilidades son orientativas, no una decisión sobre el estudiante.

> **Límite conocido:** la autorización por rol ya está aplicada a operaciones administrativas, pero todavía falta implementar el aislamiento completo de datos por aula para cada docente. No publiques esta aplicación en internet ni la uses con datos personales reales hasta completar ese control y desplegarla con HTTPS.

## Novedades de la versión 1.7

- **Entrenamiento del modelo** (`modelos/entrenamiento.py`): usa `data/historico_anonimizado.csv` (columnas `Notas_Detalladas`, `Registro_Asistencia`, `Estado_Abandono`), valida con validación cruzada y guarda `modelo_riesgo.json` con versión, métricas y versión de scikit-learn. Sin ese CSV, `python modelos/entrenamiento.py --sintetico` entrena con datos de demostración. La API usa la versión del JSON en las alertas y avisa si cambió la versión de scikit-learn.
- **Sincronización** (`api/sync.py`): además de estudiantes, envía calificaciones y asistencias por lotes. `python -m api.sync` hace una pasada; con `DATACLASS_SYNC_AUTO=1` la API lanza un `SyncWorker` que repite cada `DATACLASS_SYNC_INTERVALO` segundos y espera más tiempo tras cada fallo de red.
- **Login**: tras 5 intentos fallidos por correo (30 por IP real) en 5 minutos, responde 429 con `Retry-After` durante 5 minutos. El estado vive en la memoria del proceso. El límite por IP solo se aplica si la API recibe la IP real del cliente (`X-Forwarded-For`); desde loopback se ignora para que nadie pueda bloquear a toda la institución (ver `docs/HTTPS_Y_DESPLIEGUE.md`).
- **Aislamiento por aula**: ya está implementado (`acceso_estudiante`, probado en `tests/test_acceso_aulas.py`). Sigue pendiente el despliegue con HTTPS antes de usar datos reales.

## 1. Preparar configuración

1. Copia `.env.example` como `.env`.
2. Genera un secreto JWT nuevo en la terminal:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

3. Pega el resultado en `DATACLASS_JWT_SECRET` dentro de `.env`.
4. Configura `DATACLASS_ADMIN_EMAIL`, `DATACLASS_ADMIN_PASSWORD` y `DATACLASS_ADMIN_NAME`. La contraseña debe tener al menos 12 caracteres. No uses los textos de ejemplo.
5. No compartas el archivo `.env`; está excluido mediante `.gitignore`.

Crea al primer directivo sin dejar su clave en `.env`: `python -m api.crear_admin --correo tu@institucion.edu` (pide la clave por teclado; también sirve para restablecerla). La variante antigua con `DATACLASS_ADMIN_PASSWORD` solo crea al primer directivo si todavía no existe ninguno; bórrala de `.env` después. Las demás cuentas se crean desde la interfaz.

## 2. Instalar dependencias

Abre PowerShell en la carpeta raíz del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt        # solo para ejecutar
python -m pip install -r requirements-dev.txt    # además, para correr las pruebas
# python -m pip install -r requirements-sync.txt # solo si mantienes la sincronización con Firebase
```

## 3. Iniciar el backend

En una terminal:

```powershell
python -m uvicorn api.main:app --reload
```

Documentación interactiva: <http://127.0.0.1:8000/docs>

## 4. Iniciar el frontend

En otra terminal, con el entorno virtual activado:

```powershell
python -m streamlit run app.py
```

Streamlit abrirá la interfaz en el navegador. Ambos procesos deben permanecer ejecutándose.

## 5. Crear una cuenta docente

1. Inicia sesión como directivo en Streamlit.
2. Ve a **Gestión de docentes → Crear cuenta de docente**, escribe nombre, correo y aula.
3. La pantalla muestra **una sola vez** una contraseña temporal: entrégala por un canal seguro. El docente deberá cambiarla al entrar.
4. Para olvidos de contraseña: **Gestión de docentes → Restablecer contraseña** (genera otra temporal y cierra sus sesiones).

Cada persona cambia su propia clave en **Mi cuenta**. `/docs` queda apagado salvo `DATACLASS_DOCS=1` (solo desarrollo).

## 6. Firebase

La clave privada de Firebase ya no se incluye en el proyecto. Si la clave anterior era real, revócala o rótala desde Google Cloud/Firebase. Para habilitar la sincronización, guarda el nuevo JSON **fuera de esta carpeta** y configura `FIREBASE_CREDENTIALS_PATH` con su ruta. No subas esa clave a Git ni la compartas en ZIP.

## 7. Pruebas

```powershell
python -m pytest -q
```

Las pruebas cubren el flujo académico, las alertas/intervenciones, la autenticación, algunas restricciones por rol y el semáforo de riesgo (`tests/test_riesgo.py` y `tests/test_riesgo_api.py`). No equivalen a una auditoría de seguridad completa.

## Consideraciones del modelo predictivo

El modelo actual es experimental y fue entrenado con datos sintéticos. Sus resultados no deben usarse como decisión automática sobre estudiantes. Antes de producción, se necesita validación con datos autorizados, métricas de desempeño, evaluación de sesgos y revisión humana.

## Novedades de la versión 1.8 (auditoría, supresión en la nube, HTTPS)

- **Bitácora de auditoría** (`api/auditoria.py`, tabla `auditoria`): registra cada acceso a `/api/` con usuario, rol, IP, ruta, estudiante afectado y código de respuesta, incluidos los rechazos (401/403/404) y los inicios de sesión. No guarda cuerpos de peticiones. Es de solo anexado (triggers). Consulta: `GET /api/v1/auditoria` (solo directivos; filtros `id_estudiante`, `id_usuario`, `accion`, `desde`, `hasta`). Retención: `DATACLASS_AUDITORIA_RETENCION_DIAS` y `auditoria.depurar()`.
- **Supresión en Firestore**: `DELETE /api/v1/estudiantes/{id}` encola el borrado en `eliminaciones_nube`; `sincronizar_eliminaciones()` (dentro de `sincronizar_todo`) borra el documento y sus subcolecciones y reintenta si falla la red.
- **Cabeceras de seguridad**: `Cache-Control: no-store` y `X-Content-Type-Options: nosniff` en `/api/`; HSTS con `DATACLASS_FORZAR_HTTPS=1`.
- **HTTPS**: ver `docs/HTTPS_Y_DESPLIEGUE.md` y `deploy/Caddyfile`.
- **Cumplimiento**: ver `docs/CUMPLIMIENTO_LEY_29733.md` (tareas, plantillas y qué falta).
- **Datos de demostración**: `python database/datos_demo.py` (personas inventadas). **Compartir el proyecto**: `python empaquetar.py` crea un ZIP sin bases de datos, `.env` ni claves.


## Carga masiva desde CSV y Excel

Disponible en la interfaz: **Estudiantes → Carga masiva** (solo directivos) y **Registro académico → Carga masiva** (notas y asistencias; los docentes solo para su aula). Cada pestaña ofrece una plantilla descargable.

Endpoint: `POST /api/v1/importaciones/{estudiantes|calificaciones|asistencias}` (archivo en el campo `archivo`, `.csv` o `.xlsx`).

- **Por defecto solo valida** (`simular=true`). Para guardar hay que enviar `simular=false`.
- **Todo o nada:** si una fila tiene errores no se guarda ninguna; el informe indica fila, campo y motivo.
- **Idempotente:** reenviar el mismo archivo no duplica datos; las filas idénticas ya existentes se cuentan como "ya existían".
- **No sobrescribe:** si una fila choca con un dato existente que es distinto (otro nombre para el mismo ID, otro estado de asistencia para la misma fecha) se reporta como error. Para corregir una nota o una asistencia existente se usa «Registro académico → Corregir registros» (API: `PATCH`/`DELETE /api/v1/calificaciones/{id}` y `/asistencias/{id}`), que queda en la bitácora y borra también el documento en Firestore.
- Una nota repetida idéntica (mismo estudiante, curso, periodo y nota) dentro del mismo archivo se considera error. Notas distintas del mismo curso y periodo sí se permiten.
- Los nombres de curso se unifican ignorando mayúsculas, tildes y espacios (`matematica` → `Matemática`); el informe lo avisa. No se unen cursos con nombres realmente distintos (`Matematica` vs `Matemáticas Aplicadas`): para eso hace falta un catálogo de cursos.
- Valores que empiezan con `=`, `+`, `-` o `@` se rechazan en campos de texto libre (inyección de fórmulas).
- Tras importar notas o asistencias se vuelve a evaluar el riesgo de los estudiantes afectados.
- Cada importación queda en la bitácora de auditoría (tipo, filas, nuevas, errores; sin datos personales).
- Límites configurables con `DATACLASS_IMPORT_MAX_MB` y `DATACLASS_IMPORT_MAX_FILAS`.

Columnas (se aceptan alias como `código`, `nombre`, `curso`, `nota`, `periodo`, `estado`; las tildes y mayúsculas no importan):

| Tipo | Obligatorias | Opcionales |
|---|---|---|
| estudiantes | id_estudiante, nombre_completo | dni, aula, telefono_apoderado |
| calificaciones | id_estudiante, curso_modulo, nota_obtenida, periodo_evaluacion | — |
| asistencias | id_estudiante, fecha (AAAA-MM-DD o DD/MM/AAAA), estado_asistencia (presente, tardanza, falta, justificada o P, T, F, J) | — |

En Excel, da formato **Texto** a la columna `dni` para no perder los ceros iniciales.

### Plantillas de Excel

Cada pestaña de carga masiva ofrece una **plantilla Excel con instrucciones** (`api/plantillas.py`) y una plantilla CSV simple. La plantilla Excel trae:

- Hoja **Datos** (la primera, la que se llena y se sube): encabezados exactos, formato Texto en el DNI e IDs, lista desplegable en `estado_asistencia` y validación de nota entre 0 y 20.
- Hoja **Instrucciones**: pasos, tabla de columnas con formato y ejemplo, filas de ejemplo y errores frecuentes. No se importa.
- Los ejemplos no están en la hoja Datos, para que nadie importe filas de ejemplo por error.

El importador lee la hoja llamada `Datos`; si no existe, lee la primera hoja. Los encabezados de la plantilla salen de `api/importacion.py`, y `tests/test_plantillas.py` falla si plantilla e importador se desfasan.

## Normalización y validación compartidas (API e importación)

- **Aula** (`validaciones.normalizar_aula`): sin espacios sobrantes y en mayúsculas («a-302 » -> «A-302»). Se aplica al crear o editar estudiantes y usuarios, en la importación y en el filtro `?aula=`. Al iniciar, `normalizar_aulas_existentes` lleva las aulas ya guardadas a esa forma (idempotente; marca los estudiantes cambiados para volver a sincronizarlos; deja intactas las que no se pueden normalizar).
- **Curso y periodo**: la API usa las mismas reglas que la importación (`normalizar_texto_libre`: espacios colapsados, sin prefijos `=`, `+`, `-`, `@`). Un curso escrito distinto de uno ya guardado («matematica») se unifica con la grafía existente («Matemática»).
- **Asistencias**: la API rechaza fechas futuras o anteriores al 2000, igual que la importación.
- **Exportaciones**: el CSV del listado de estudiantes neutraliza los textos que empiezan con `=`, `+`, `-` o `@` (`df_seguro_csv`), incluso los que ya estaban guardados antes de estas reglas.

## Cambios tras la auditoría técnica (1.8.1)

- **H-01:** si `modelos/modelo_riesgo.json` indica `sintetico: true` (o no lo indica), la API **no calcula el semáforo ni crea alertas automáticas**; `POST /estudiantes/{id}/evaluar-riesgo` y `/analitica/evaluar-todos` responden 503. La interfaz muestra un aviso permanente. Para demostraciones con datos inventados: `DATACLASS_MODO_DEMO=1`. `GET /api/v1/estado` informa el estado del modelo.
- Mejoras rápidas: búsqueda sin regex, estado real de la API en la barra lateral, `maxUploadSize = 5` en Streamlit, sin aulas de ejemplo en el formulario de directivos, versión única en `api/__init__.py`.
- **H-04 (contraseñas):**
  - Hash versionado `pbkdf2_sha256$600000$sal$hash` (los hashes antiguos siguen valiendo y se actualizan al iniciar sesión). Confirma las 600.000 iteraciones con la guía vigente de OWASP.
  - `POST /api/v1/auth/cambiar-password` (clave actual + nueva, política mínima) y `POST /api/v1/usuarios/{id}/restablecer-password` (clave temporal que debe cambiarse; mientras tanto la cuenta solo puede cambiarla).
  - Columnas nuevas `token_version` y `debe_cambiar` (se agregan solas a bases existentes). Cambiar o restablecer la clave, desactivar la cuenta o cambiar su rol cierran todas sus sesiones.
  - No se puede desactivar ni degradar al último directivo activo. Un correo inexistente tarda lo mismo que uno existente al iniciar sesión.
  - Pantallas: **Mi cuenta**, aviso obligatorio de cambio, y en **Gestión de docentes** crear docentes y restablecer claves.
  - Pendiente: segundo factor para directivos y el resto de M-02 (no guardar el correo tipeado en la bitácora).
- **H-05 (seguimiento):** en **Alertas e intervenciones** ya se puede registrar una intervención (alerta asociada, tutor = usuario autenticado, tipo, fecha, próxima revisión), cambiar el estado de las alertas (pendiente, en seguimiento, resuelta, descartada) y editar el resultado de una intervención. Las alertas manuales se marcan con `version_modelo = "manual"` y ya no piden probabilidad.
- **H-02 (bitácora):** altas y cambios de notas, asistencias, alertas e intervenciones ahora registran el estudiante afectado. Las correcciones de notas/asistencias guardan `campo: antes->después`, los borrados guardan el valor eliminado, los cambios de alertas guardan `estado: antes->después` y los de cuentas guardan rol/aula/activo antes y después. Los listados de estudiantes anotan cuántos y cuáles ids se entregaron. Pendiente: la exportación CSV del frontend sigue sin pasar por el servidor (no queda registrada).

## Novedades de la versión 1.9.0

Resumen: cierre de sesión real, permisos más estrictos, base de datos más robusta y modelo verificado. El detalle y los cambios que pueden afectar a una instalación existente están en `CHANGELOG.md`. Lo más importante:

- **Cerrar sesión invalida el token** en el servidor (`POST /api/v1/auth/cerrar-sesion`).
- **Solo directivos modifican estudiantes** (`PATCH /estudiantes/{id}`); las alertas manuales quedan siempre como «manual»; el tutor de una intervención es quien la registra.
- **El modelo solo se carga si su huella SHA-256 coincide** con la de `modelos/modelo_riesgo.json`. Si reentrenas con `python modelos/entrenamiento.py`, la huella se actualiza sola. Si tienes un `.pkl` propio de confianza: `python modelos/entrenamiento.py --sellar`.
- **SQLite en modo WAL** con versión de esquema. Aparecen `*.db-wal` y `*.db-shm`: contienen datos personales, igual que la base.
- Scripts antiguos en `legacy/`; dependencias separadas en `requirements*.txt`.

## Qué falta (resumen de la auditoría)

Decidir qué hacer con Firestore y los datos de menores (H-03); segundo factor para directivos y token corto con renovación (H-04); paginación real y exportaciones auditadas (M-08); año lectivo, periodos y promoción de estudiantes (M-10); dividir `api/main.py` en routers; datos reales para entrenar el modelo (M-07); y una prueba de seguridad externa antes de usar datos reales. No uses el sistema con datos personales reales hasta completar al menos H-03 y el despliegue con HTTPS.
