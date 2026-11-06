import pandas as pd
import numpy as np

def preparar_datos_ia():
    # 1. Simulación de extracción de datos históricos (Normalmente vendría de un .csv)
    # Contiene las columnas exigidas: ID_Anónimo, Notas, Asistencia y Estado histórico
    datos_crudos = {
        'ID_Anónimo': ['ALU-001', 'ALU-002', 'ALU-003', 'ALU-004'],
        'Notas_Detalladas': [10.5, 15.0, np.nan, 8.0], # np.nan simula un registro vacío o perdido
        'Registro_Asistencia': [75, 95, 80, 50], # Porcentaje histórico de asistencia
        'Estado_Abandono': ['Sí', 'No', 'No', 'Sí']
    }
    
    df = pd.DataFrame(datos_crudos)
    print("--- Datos Originales (Crudos) ---")
    print(df)
    print("\n")

    # 2. Limpieza de Datos (Data Cleaning)
    # Las inteligencias artificiales no procesan bien los vacíos. Rellenamos con el promedio.
    promedio_notas = df['Notas_Detalladas'].mean()
    df['Notas_Detalladas'] = df['Notas_Detalladas'].fillna(promedio_notas)

    # 3. Normalización (Data Normalization)
    # Convertimos la columna de texto 'Estado_Abandono' a valores binarios (0 y 1) para el algoritmo
    df['Estado_Abandono'] = df['Estado_Abandono'].map({'Sí': 1, 'No': 0})
    
    # Redondeamos las notas para mantener consistencia matemática
    df['Notas_Detalladas'] = df['Notas_Detalladas'].round(1)

    print("--- Datos Limpios y Normalizados (Listos para Fase 2) ---")
    print(df)
    
    return df

if __name__ == '__main__':
    dataset_limpio = preparar_datos_ia()