# Runbook - despliegue de contingencia de scrapers a staging

Fecha de referencia: 2026-03-23

## 1. Objetivo

Desplegar el paquete de contingencia de scrapers en staging con Postgres sin subirlo a ciegas.

Este runbook cubre:

- migraciones,
- grupos operativos,
- configuracion de Telegram,
- smoke test de incidente,
- prueba del flujo manual,
- y validacion de reapertura si la automatizacion sigue rota.

## 2. Variables requeridas

Configurar en staging:

```env
SCRAPER_ALERT_PRIMARY_CHANNEL=telegram
SCRAPER_TELEGRAM_BOT_TOKEN=123456:ABCDEF...
SCRAPER_TELEGRAM_CHAT_IDS=-1001234567890
SCRAPER_TELEGRAM_API_BASE_URL=https://api.telegram.org
SCRAPER_ADMIN_BASE_URL=https://staging-admin.tudominio.com
SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES=180
SCRAPER_INCIDENT_VIEWER_GROUPS=ScraperViewers
SCRAPER_INCIDENT_RESOLVER_GROUPS=ScraperResolvers
```

## 3. Preparacion de Telegram

### 3.1 Bot

1. Crear bot con `@BotFather`.
2. Guardar el token en `SCRAPER_TELEGRAM_BOT_TOKEN`.
3. Agregar el bot al grupo de operaciones.
4. Dar permisos minimos para escribir mensajes.

### 3.2 Grupo o chat destino

`SCRAPER_TELEGRAM_CHAT_IDS` acepta uno o varios `chat_id` separados por coma.

Ejemplos:

- Grupo privado: `-1001234567890`
- Canal o grupo adicional: `-1009999999999`

### 3.3 Mensajes que se envian hoy

Hay dos familias de mensaje:

#### A. Alerta tecnica de salud

Se usa para `failed_today`, `missing_today` o `stale`.

Ejemplo:

```text
LoteriaTV - Alertas activas de scrapers
Fecha: 2026-03-23 20:00:00 -04

* Animalitos Condor Gana
  tipo: failed_today
  estado: failed
  mensaje: simulated scraper failure
  error: simulated scraper failure
  ultimo_ok: -
  fallas_consecutivas: 1
```

#### B. Incidente operativo

Se usa cuando una corrida detecta grupo faltante o fallo que deja el resultado no utilizable.

Ejemplo:

```text
LoteriaTV - Incidente de scraper
Incidente: #42
Scraper: Triples Lotoven
Fecha objetivo: 2026-03-23
Estado: open
Severidad: critical
Motivo: missing_expected_group
Grupo: Triple Chance A @ 16:00
Resumen: Triples Lotoven: falta el grupo esperado Triple Chance A 16:00.
Evidencia: validation_profile=mixed expected=22 persisted=21 missing=1 ...
Admin: https://staging-admin.tudominio.com/admin/core/scraperincident/42/change/
```

## 4. Despliegue a staging

### 4.1 Antes del deploy

```bash
python manage.py makemigrations --check --dry-run core
python manage.py showmigrations core
```

### 4.2 Aplicar migraciones

```bash
python manage.py migrate
```

### 4.3 Crear grupos operativos

```bash
python manage.py bootstrap_scraper_ops
```

Resultado esperado:

- existen grupos viewer y resolver,
- el admin puede asignar usuarios reales de staging.

## 5. Smoke test de staging

### 5.1 Validacion de health y notificaciones

```bash
python manage.py notify_scraper_alerts --dry-run
python manage.py describe_scraper_ops
python manage.py check_ops_health --strict
```

### 5.2 Simular incidente controlado

Sin enviar Telegram real:

```bash
python manage.py simulate_scraper_contingency --scenario missing_group --scraper lotoven_triples --reset-open-incidents
```

Con envio real a Telegram:

```bash
python manage.py simulate_scraper_contingency --scenario missing_group --scraper lotoven_triples --reset-open-incidents --send-telegram
```

Tambien puedes simular fallo tecnico:

```bash
python manage.py simulate_scraper_contingency --scenario technical_failure --scraper condor_animalitos --reset-open-incidents --send-telegram
```

### 5.3 Validaciones esperadas

1. Se crea `ScraperExecution`.
2. Se crea `ScraperIncident`.
3. Telegram recibe mensaje.
4. El incidente aparece en Django Admin.
5. El enlace `Carga manual controlada` funciona.
6. La intervencion crea `ManualResultIntervention`.
7. El resultado queda en `manual_contingency`.
8. El incidente pasa a `RESOLVED`.

### 5.4 Validacion de reapertura

1. Con incidente ya resuelto manualmente, repetir la simulacion del mismo faltante.
2. Confirmar que el incidente se reabre.
3. Confirmar que Telegram vuelve a salir una sola vez.
4. Confirmar que `occurrence_count` aumenta.

## 6. Comandos utiles

```bash
python manage.py bootstrap_scraper_ops
python manage.py describe_scraper_ops
python manage.py notify_scraper_alerts --dry-run
python manage.py notify_scraper_alerts
python manage.py simulate_scraper_contingency --scenario missing_group --scraper lotoven_triples
python manage.py simulate_scraper_contingency --scenario technical_failure --scraper condor_animalitos
```

## 7. Criterio de salida para aprobar staging

Staging queda aprobado si:

1. Las migraciones aplican bien en Postgres.
2. Los grupos viewer/resolver existen.
3. Telegram recibe mensajes validos.
4. Se puede abrir y resolver un incidente desde Django Admin.
5. La carga manual deja trazabilidad completa.
6. El incidente se reabre si la automatizacion sigue sin recuperar el grupo.
7. El incidente se resuelve automaticamente cuando el scraper vuelve a dejar el resultado como `automatic_valid`.
