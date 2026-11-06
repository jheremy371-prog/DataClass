# HTTPS y despliegue seguro de DataClass

Objetivo: que ningún dato personal viaje sin cifrar y que la API no quede expuesta directamente a internet.

## Arquitectura recomendada

```
Navegador ──HTTPS──> Caddy (443) ──> Streamlit (127.0.0.1:8501) ──HTTP local──> API FastAPI (127.0.0.1:8000) ──> SQLite
```

- **Solo Caddy escucha en la red pública.** Streamlit y la API se enlazan a `127.0.0.1`.
- Streamlit llama a la API **desde el servidor**, así que `DATACLASS_API_URL=http://127.0.0.1:8000/api/v1` puede seguir siendo HTTP: ese tramo no sale de la máquina.
- Si en el futuro un cliente externo (app móvil) debe llegar a la API, publícala detrás de Caddy con su propio dominio (bloque comentado en `deploy/Caddyfile`).

## Pasos (servidor Windows o Linux)

1. **Dominio**: crea un registro DNS `dataclass.tu-institucion.edu.pe` hacia la IP del servidor. Abre los puertos 80 y 443 (80 lo necesita Let's Encrypt para validar y redirigir).
2. **Instala Caddy** (https://caddyserver.com/docs/install) y copia `deploy/Caddyfile` cambiando el dominio. Arranca con `caddy run --config Caddyfile`. Caddy obtiene y renueva el certificado solo.
3. **Arranca la API solo en local**:
   ```powershell
   python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
   ```
   Sin `--reload` en producción.
4. **Arranca Streamlit solo en local**:
   ```powershell
   python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
   ```
   Deja activada la protección XSRF (es el valor por defecto; no la desactives).
5. **Activa HSTS en la API** poniendo `DATACLASS_FORZAR_HTTPS=1` en `.env` (solo cuando el sitio ya responde por HTTPS; HSTS le dice al navegador que nunca vuelva a usar HTTP).
6. **Verifica**: abre `http://tu-dominio` (debe redirigir a `https://`), y revisa el candado. Después pasa el dominio por https://www.ssllabs.com/ssltest/ y busca la calificación A.

## Prueba local con HTTPS

Para ensayar sin dominio: `caddy run` con un bloque `localhost { reverse_proxy 127.0.0.1:8501 }` (Caddy genera un certificado local y te pide confiar en él), o `mkcert` para un certificado de desarrollo.

## La IP del cliente en la bitácora y en el limitador

Como Streamlit es quien llama a la API, sin configuración adicional la API vería **siempre la IP 127.0.0.1**. Para evitarlo:

- `app.py` reenvía a la API la IP real del navegador (primera dirección válida de `X-Forwarded-For`, que pone Caddy) en el login y en cada llamada.
- Arranca uvicorn con `--proxy-headers --forwarded-allow-ips 127.0.0.1`, para que la API confíe en esa cabecera **solo** cuando viene del propio servidor.
- Si la API solo ve una IP de loopback (no se reenvió la IP real), el límite de login **por IP no se aplica**, porque bloquearía a toda la institución a la vez. En ese caso solo actúa el límite por correo (5 intentos). Por eso conviene dejar bien configurado el proxy.
- Streamlit debe quedar detrás de Caddy y no expuesto directamente: Caddy sustituye cualquier `X-Forwarded-For` que mande el cliente, y un Streamlit abierto permitiría falsear la IP.

## Otras medidas mínimas del servidor

- Cifrado del disco (BitLocker en Windows / LUKS en Linux): protege `dataclass.db` si roban el equipo.
- Copias de seguridad cifradas de `database/dataclass.db` y de la bitácora, con plazo de retención (ver `CUMPLIMIENTO_LEY_29733.md`). Una copia de seguridad también contiene datos personales.
- Actualizaciones del sistema y de las dependencias; el archivo `.env` con permisos restringidos.
- En producción, desactiva la documentación pública de la API (`/docs`) o déjala accesible solo desde el propio servidor.
