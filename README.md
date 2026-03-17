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
