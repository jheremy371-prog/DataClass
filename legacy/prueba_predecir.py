import requests
import time

# Endpoint de tu servidor local
url = "http://127.0.0.1:8000/api/v1/analitica/predecir"

# Simulamos a un alumno con bajas notas y mala asistencia
datos_estudiante = {
    "notas_promedio": 8.5,
    "porcentaje_asistencia": 55
}

print("Enviando datos al servidor...")
inicio = time.time()

respuesta = requests.post(url, json=datos_estudiante)

fin = time.time()
tiempo_respuesta = fin - inicio

print(f"Respuesta del servidor: {respuesta.json()}")
print(f"Tiempo de respuesta: {tiempo_respuesta:.3f} segundos")