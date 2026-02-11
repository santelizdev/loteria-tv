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
