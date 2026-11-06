# Archivos antiguos (no se usan)

Estos scripts son de las primeras versiones del proyecto. **Nada de la aplicación los importa** y se conservan solo como referencia.
Pueden borrarse cuando ya no los necesites.

| Archivo | Qué era | Por qué no se usa |
|---|---|---|
| `prueba_predecir.py` | Llama a `/analitica/predecir` sin iniciar sesión. | Ese endpoint ahora exige token. |
| `limpieza_ejemplo.py` | Ejemplo de limpieza de datos para entrenar. | Lo reemplaza `modelos/entrenamiento.py`. |
| `setup_sqlite_esquema_antiguo.py` | Creaba la base con el esquema de la v1.0. | Lo reemplaza `api/database.py`. Para pasar una base antigua al esquema actual, usa `database/migrar_esquema.py`. |
| `poblar_alumnos_ejemplo.py` | Insertaba estudiantes `EST-001`… con datos que parecen reales. | **No lo ejecutes** con una base real. Para una demostración usa `python database/datos_demo.py`. |
