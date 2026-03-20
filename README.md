# Lotería TV (Django + Channels + PWA)

Sistema para **mostrar resultados de lotería en pantallas tipo TV** mediante una **PWA** (frontend liviano) y un backend **Django** que expone APIs y comunicación en tiempo real por **WebSockets (Django Channels + Redis)**.

Incluye:
- Resultados **Triples** (CurrentResult) por proveedor.
- Resultados **Animalitos** por proveedor.
- Registro de dispositivos (TVs) con `activation_code`.
- Activación/asignación a sucursal (branch) y validación de suscripción.
- Cache en Redis para reducir carga de base de datos.
- PWA con rotación/paginación automática de vistas (Triples / Animalitos).

---

## Stack

**Backend**
- Python / Django
- Django REST Framework
- Django Channels (ASGI)
- Redis (cache + channel layer)
- Daphne (servidor ASGI)

**Frontend**
- PWA (HTML/CSS/JS)
- Polling controlado + WebSocket para eventos
- UI estilo TV (4 columnas por página)

---

## Estructura (alto nivel)


---

## Requisitos

- Python 3.11+ (recomendado)
- Redis
- Virtualenv recomendado

---

## Setup Backend (local)

### 1) Crear entorno e instalar dependencias
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2) Separar entorno local de Docker
El proyecto ahora carga variables en este orden:

- Variables reales del sistema o del proceso.
- `.env.local` para tu host local.
- `.env` como base compartida.

Docker sigue usando `.env.docker` vía `docker compose`, así que tu `.env.local` no interfiere con los contenedores.

Ejemplo rápido para correr comandos Django desde tu host:

```bash
python manage.py check_ops_health --strict
```

## Diagnóstico remoto Smart TV

Se añadió un checklist operativo para validar incidencias de ciclo/tránsito de pantallas en PWA (Venezuela): `pwa/TV_VENEZUELA_DIAGNOSTICO.md`.



## Seguridad y QA

Checklist operativo documentado en `docs/security_qa_checklist.md`.

## Monitoreo interno de scrapers

El backend incluye control interno de salud para scrapers en Django Admin.

Variables opcionales:

- `SCRAPER_ALERT_EMAILS=ops1@dominio.com,ops2@dominio.com`
- `SCRAPER_ALERT_USERNAMES=admin1,operaciones1`
- `SCRAPER_ALERT_GROUPS=Administradores,Operadores`
- `SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES=180`
- `DEFAULT_FROM_EMAIL=noreply@ssganador.lat`

Comandos útiles:

```bash
python manage.py run_scraper_suite
python manage.py run_scraper_suite --notify
python manage.py run_daily_retention
python manage.py notify_scraper_alerts --dry-run
python manage.py notify_scraper_alerts
python manage.py check_ops_health --strict
```

Notas:

- Todo este monitoreo es interno y solo vive en Django Admin / comandos de operación.
- El admin de `Scraper health` resume `OK / fallo hoy / sin OK hoy / stale` y permite forzar aviso interno o resetear cooldown.
- Si producción usa `systemd timer` en vez de Celery, el timer debe ejecutar `python manage.py run_scraper_suite` para que el monitor se actualice correctamente.
- El timer de retention en producción debe apuntar a `scripts/daily_retention.sh`, archivo versionado dentro del repo.
