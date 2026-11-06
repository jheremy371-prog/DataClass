# DataClass y la Ley 29733: guía práctica de cumplimiento

> **Aviso.** Esta guía organiza el trabajo y traduce las obligaciones a tareas concretas. **No es asesoría legal.** Antes de poner DataClass a funcionar con datos reales, haz revisar los textos (aviso de privacidad, consentimientos, contratos) por un abogado o por el responsable de datos personales de tu institución. Los plazos y requisitos exactos deben confirmarse en el texto oficial de la norma.

## 1. Marco aplicable

- **Ley 29733**, Ley de Protección de Datos Personales (2011).
- **Reglamento aprobado por D.S. 016-2024-JUS**, publicado el 30 de noviembre de 2024 y vigente desde fines de marzo de 2025 (120 días después de su publicación). Derogó el reglamento de 2013 (D.S. 003-2013-JUS).
- Autoridad: **Autoridad Nacional de Protección de Datos Personales (ANPD)**, del Ministerio de Justicia y Derechos Humanos.

Puntos del nuevo reglamento que pegan directo con DataClass:

- Todo tratamiento requiere consentimiento previo, libre, expreso e inequívoco, salvo otra base legal aplicable.
- Al recoger datos del titular hay que informar, entre otras cosas, **la existencia de decisiones automatizadas y de perfiles**. El semáforo de riesgo es un perfilado.
- **Menores**: para menores de 14 años consienten padres o tutores; entre 14 y 17 se admite el consentimiento informado del propio menor (art. 22). Hay protección reforzada para datos de menores, y se prohíbe recoger de ellos información sobre su grupo familiar sin consentimiento de los titulares (art. 23).
- La inscripción, modificación y cancelación de bancos de datos en el registro de la ANPD es **gratuita** y se tramita en línea.
- Si el titular revoca el consentimiento, el tratamiento debe adecuarse en un máximo de 10 días hábiles.
- Se exigen medidas técnicas y organizativas de seguridad y trazabilidad, y existe un régimen de notificación de incidentes de seguridad.

> Nota para CETPRO: parte de tu alumnado puede ser mayor de edad. Registra la **fecha de nacimiento** (o al menos "mayor/menor de edad") para saber quién consiente: el propio estudiante o sus padres/tutores. Hoy DataClass no guarda ese dato.

## 2. Quién es quién

| Rol | Quién | Consecuencia |
|---|---|---|
| **Titular del banco de datos** (decide para qué y cómo se tratan los datos) | La institución educativa (CETPRO) | Es la responsable legal: registra el banco, informa, atiende derechos. |
| **Titulares de datos personales** | Estudiantes (y apoderados, cuyo teléfono se guarda) | Tienen derechos de acceso, rectificación, cancelación, oposición, etc. |
| **Encargado del tratamiento** | Google (Firebase/Firestore) y quien aloje el servidor | Se necesita un **contrato o cláusulas de encargo** con confidencialidad, seguridad y devolución/destrucción de datos. |
| **Transferencia transfronteriza** | Firestore almacena en la región que elijas, probablemente fuera de Perú | Debe declararse al inscribir el banco de datos y figurar en el aviso de privacidad. Elige una región y documéntala. |

## 3. Lista de tareas (en orden de prioridad)

### A. Antes de usar datos reales
- [ ] **Inscribir el banco de datos** "Estudiantes y seguimiento académico" ante la ANPD (en línea, gratuito). Datos a declarar: finalidad, categorías de datos, titulares, encargados, transferencia al extranjero, medidas de seguridad, plazo de conservación.
- [ ] **Aviso de privacidad y consentimiento** (plantillas en la sección 5), entregados antes de recoger los datos. Debe mencionar el perfilado/semáforo y que **una persona revisa siempre** el resultado.
- [ ] **Base legal para el perfilado.** Si te apoyas en el consentimiento, que sea específico para el análisis de riesgo, separado del consentimiento general de matrícula. Que decidan con tu asesor legal si el tratamiento educativo cuenta con otra base.
- [ ] **Contrato de encargo con Google/Firebase** y el proveedor de hosting. Guarda copia.
- [ ] **Sacar el modelo de la fase "sintética"**: no se puede basar una decisión sobre un estudiante en un modelo con 10 filas inventadas. Ver `README_CONTINUACION.md`.
- [x] **Minimizar lo que va a la nube** (ver sección 4): hecho en la v1.10. A Firestore solo salen un seudónimo, el aula, los niveles de riesgo y los datos académicos de cada nota o asistencia.

### B. Operación continua
- [ ] **Procedimiento para atender solicitudes de los titulares** (acceso, rectificación, supresión, oposición, revocación). Plantilla en la sección 5; nombra a una persona responsable y un plazo interno.
- [ ] **Política de retención** (sección 5) y su aplicación periódica.
- [ ] **Registro y revisión de accesos**: revisar la bitácora (`GET /api/v1/auditoria`) con una periodicidad fija, por ejemplo mensual, y ante cualquier sospecha.
- [ ] **Plan de respuesta a incidentes**: quién decide, a quién se avisa (ANPD y afectados) y en qué plazo. Confirma el plazo vigente en el reglamento.
- [ ] **Capacitación** breve a docentes y directivos: uso de contraseñas, no compartir cuentas, no sacar datos fuera del sistema.
- [ ] Evaluar si corresponde designar un **oficial de datos personales** y si conviene hacer una **evaluación de impacto** previa, dada la combinación de menores y perfilado.

## 4. Qué cubre el código y qué falta

| Obligación o riesgo | Estado en DataClass v1.8 |
|---|---|
| Control de acceso por rol y aula | ✅ Ya existía (RBAC, aislamiento por aula). |
| **Trazabilidad**: quién accedió o modificó qué | ✅ **Nuevo.** Tabla `auditoria` de solo anexado, middleware que registra cada acceso a `/api/` (incluidos 401/403/404), inicio de sesión correcto/fallido/bloqueado, y `GET /api/v1/auditoria` solo para directivos. No guarda cuerpos de peticiones ni datos personales. |
| **Supresión en la nube** | ✅ **Nuevo.** `DELETE /estudiantes/{id}` deja el id en `eliminaciones_nube`; `SyncWorker` / `python -m api.sync` borra el documento **y sus subcolecciones** en Firestore y reintenta si no hay red. |
| Cifrado en tránsito | ⚙️ Configuración lista (`deploy/Caddyfile`, `docs/HTTPS_Y_DESPLIEGUE.md`); hay que aplicarla en el servidor. |
| Retención de la bitácora | ✅ `auditoria.depurar()` y variable `DATACLASS_AUDITORIA_RETENCION_DIAS`. Falta **programarla** (tarea mensual). |
| Retención de datos académicos | ❌ No hay depuración automática de estudiantes egresados. Definir política y script. |
| Minimización en la nube | ✅ **Hecho (v1.10).** Firestore recibe un **seudónimo** (HMAC-SHA256 del ID con `DATACLASS_SEUDONIMO_CLAVE`), el aula y los niveles de riesgo; de notas y asistencias, solo los datos académicos. **No salen** el nombre, el DNI, el teléfono ni el ID real. Sin la clave no se envía nada. Aula y fechas siguen siendo datos que, combinados, podrían volver a identificar a alguien en un grupo pequeño: es seudonimización, no anonimización. |
| Consentimientos registrados | ❌ No hay tabla de consentimientos (fecha, versión del aviso, quién consintió, revocación). |
| Fecha de nacimiento / menor de edad | ❌ No se guarda. |
| Derechos ARCO desde la aplicación | ❌ Solo hay `GET/PATCH/DELETE` generales. Falta exportar el expediente de un estudiante (acceso/portabilidad). |
| Cifrado en reposo de `dataclass.db` | ❌ Usa cifrado de disco del sistema (BitLocker/LUKS) o SQLCipher. |
| Copias de seguridad y su retención | ❌ No definidas. |

Cuando quieras, el siguiente paso con mejor relación valor/esfuerzo es **minimizar lo que va a Firestore** y agregar la **tabla de consentimientos**.

## 5. Plantillas (adáptalas con tu asesor)

### 5.1 Aviso de privacidad (resumen)

> **[Nombre de la institución]**, con RUC [___] y domicilio en [___], es titular del banco de datos personales "Estudiantes y seguimiento académico", inscrito [o en trámite de inscripción] ante la Autoridad Nacional de Protección de Datos Personales.
>
> **Datos que tratamos:** identificación (nombre, DNI), aula, calificaciones, asistencia, y teléfono del apoderado.
> **Finalidad:** gestionar la formación académica y **detectar a tiempo riesgo de abandono o bajo rendimiento** para ofrecer apoyo (tutorías, contacto con la familia).
> **Decisiones automatizadas y perfiles:** el sistema calcula un nivel de riesgo (bajo, medio, alto) con un modelo estadístico a partir de notas y asistencia. **Ese resultado es solo una señal de apoyo**; ninguna decisión sobre el estudiante se toma de forma exclusiva por el sistema y siempre la revisa una persona.
> **Destinatarios y encargados:** personal autorizado de la institución; Google LLC (Firebase) como proveedor de almacenamiento en la nube, ubicado en [región/país], lo que implica transferencia de datos fuera del Perú.
> **Plazo de conservación:** [ver política de retención].
> **Derechos:** puede ejercer sus derechos de acceso, rectificación, cancelación, oposición y revocación del consentimiento escribiendo a [correo] o en [oficina]. También puede acudir a la Autoridad Nacional de Protección de Datos Personales.

### 5.2 Consentimiento (dos versiones)

- **Estudiante mayor de edad / de 14 a 17 años:** "Declaro haber leído el aviso de privacidad y **autorizo** el tratamiento de mis datos para las finalidades indicadas, incluido el análisis de riesgo académico. ☐ Sí ☐ No. Puedo revocarlo en cualquier momento."
- **Menor de 14 años (padre, madre o tutor):** "Como [padre/madre/tutor] de [nombre del estudiante], declaro haber leído el aviso y **autorizo** el tratamiento de sus datos… ☐ Sí ☐ No."

Guarda la fecha, la versión del aviso y quién consintió. Revisa con tu asesor si el consentimiento del perfilado debe ir separado del de matrícula.

### 5.3 Procedimiento de supresión (cancelación) de un estudiante

1. Recibir la solicitud por escrito y **verificar la identidad** de quien la presenta (el titular, o el padre/tutor si es menor).
2. Registrar la fecha de recepción y la persona responsable.
3. Comprobar si existe una **obligación de conservar** los datos (por ejemplo, registros de matrícula y notas exigidos por normativa educativa). Si la hay, informar al solicitante por qué no se borra todo.
4. Un **directivo** ejecuta `DELETE /api/v1/estudiantes/{id}` (elimina notas, asistencias, alertas e intervenciones locales y encola el borrado en Firestore).
5. Ejecutar `python -m api.sync` (o esperar al `SyncWorker`) y **verificar** que `eliminaciones_nube` queda vacía y que el documento ya no está en la consola de Firebase.
6. Recordar las **copias de seguridad**: indicar cuándo caducarán las que aún contengan al estudiante.
7. Responder al solicitante confirmando la supresión. Guardar la constancia (sin datos innecesarios).

La bitácora conserva el id del estudiante y la acción para poder demostrar que se atendió la solicitud; no conserva sus datos personales.

### 5.4 Política de retención (ejemplo; los plazos los fija la institución)

| Dato | Conservar | Después |
|---|---|---|
| Estudiante activo (datos, notas, asistencia) | Mientras esté matriculado | Pasa a archivo o se anonimiza |
| Estudiante egresado o retirado | [X años] según normativa educativa aplicable | Supresión o anonimización |
| Alertas e intervenciones | Igual que el estudiante | Supresión junto con el estudiante |
| Bitácora de auditoría | 2 años (`DATACLASS_AUDITORIA_RETENCION_DIAS=730`) | `auditoria.depurar()` |
| Copias de seguridad | [30–90 días] | Se sobrescriben |
| Datos de entrenamiento del modelo | Solo anonimizados (sin DNI, nombre ni teléfono) | Revisar al reentrenar |

### 5.5 Incidente de seguridad (esquema)

1. **Contener**: cambiar el secreto JWT, desactivar cuentas implicadas, desconectar el servidor si hace falta.
2. **Investigar** con la bitácora: qué usuario, qué estudiantes, qué rango de fechas.
3. **Evaluar el riesgo** para los titulares (menores, DNI, teléfonos).
4. **Notificar** a la ANPD y a los afectados dentro del plazo que fije el reglamento (confírmalo).
5. **Documentar** causa, medidas y mejoras.

## 6. Fuentes consultadas

- Perez Llorca, "Se aprueba nuevo Reglamento de la Ley de Protección de Datos Personales" (Perú).
- IAPP, "Se publica el nuevo reglamento de protección de datos personales en Perú".
- Gob.pe (MINJUS), "Ejecutivo aprueba nuevo reglamento de la Ley de Protección de Datos Personales".
- La Cámara (lacamara.pe), "Nuevo reglamento refuerza la protección de datos personales".
- COMEXPERU, opinión legal sobre el Proyecto de Ley 8930/2024-CR (explica el art. 22 sobre menores de 14 a 17 años).
- Payet, Rey, Cauvi, Pérez Abogados, memo sobre el nuevo reglamento (plazo de revocación).

Contrasta siempre con el texto oficial del D.S. 016-2024-JUS en El Peruano / gob.pe.

## Verificación de DNI con RENIEC (Scrall)

- [ ] Al pulsar «Verificar en RENIEC», el DNI del estudiante se envía a un tercero (Scrall) para consultarlo. Inclúyelo como **encargado/destinatario** en la inscripción del banco de datos y confirma con tu asesor legal la base legal, si Scrall almacena las consultas y dónde están sus servidores.
- La clave `SCRALL_API_KEY` vive solo en el servidor. La bitácora anota que se hizo la consulta, pero no el número consultado.
- Solo el personal directivo puede consultar; cada consulta queda registrada con usuario, fecha e IP.


## Qué sale a la nube y qué no (v1.10)

| Dato | ¿Sale a Firestore? |
|---|---|
| Nombre, DNI, teléfono del apoderado, ID real del estudiante | **No** |
| Seudónimo del estudiante (24 caracteres, no reversible sin la clave) | Sí |
| Aula | Sí |
| Niveles de riesgo de deserción y reprobación | Sí |
| Notas (curso, nota, periodo) y asistencias (fecha, estado), bajo el seudónimo | Sí |
| Alertas, intervenciones, usuarios y bitácora | **No** |

Cuidados con la clave `DATACLASS_SEUDONIMO_CLAVE`:
- Guárdala fuera de la nube y del repositorio (como la clave JWT). Quien la tenga y conozca los IDs puede calcular los seudónimos.
- Si se cambia, los documentos ya subidos quedan huérfanos y los borrados dejan de encontrarlos. Planifica una migración antes de rotarla.
- Los borrados (derecho de supresión) usan el mismo seudónimo; por eso la clave debe ser la misma que cuando se subieron.

Pendiente: que un asesor confirme la base legal, el consentimiento de los apoderados y la transferencia fuera del Perú antes de activar `DATACLASS_SYNC_AUTO=1` con datos reales.
