# Sprint de contingencia de scrapers - precedente operativo

Fecha de corte: 2026-03-23
Estado: aplicado parcialmente en el backend actual

## 1. Proposito del documento

Este documento deja precedente formal de lo que ya se aplico en el sprint tactico de contingencia sobre scrapers, para que el siguiente tramo de mejoras parta desde la realidad del repo y no desde supuestos.

La idea no es vender una solucion mas grande de la que existe. La idea es dejar claro:

- que problema se ataco en este sprint,
- que capacidades si quedaron implementadas,
- que limites siguen abiertos,
- que mejoras deben construirse encima de esta base y no al margen.

## 2. Problema operativo atacado en este sprint

El riesgo inmediato era quedar ciegos cuando un scraper dejaba de correr correctamente o pasaba demasiado tiempo sin una corrida exitosa visible para operacion.

Este sprint no busco resolver toda la contingencia de punta a punta. En su estado actual, el backend quedo orientado a cubrir principalmente estas necesidades:

- tener una marca persistente de salud por scraper,
- detectar fallos recientes o ausencia de corrida exitosa del dia,
- exponer esa salud en Django Admin,
- enviar alertas internas por email con control de spam basico,
- ejecutar el set de scrapers pasando por una capa comun de monitoreo.

## 3. Alcance real implementado

### 3.1 Modelo de monitoreo persistente

Se agrego el modelo `ScraperHealth` para mantener una fila por scraper registrado.

Campos operativos principales:

- `scraper_key`
- `label`
- `command_name`
- `last_status`
- `last_started_at`
- `last_finished_at`
- `last_success_at`
- `last_error_message`
- `last_error_traceback`
- `consecutive_failures`
- `last_notified_at`
- `last_notified_signature`

Objetivo de este modelo:

- no perder el ultimo estado conocido del scraper,
- poder calcular alertas activas sin depender de logs de consola,
- permitir visibilidad rapida en admin y comandos operativos.

Migraciones involucradas:

- `core/migrations/0022_scraperhealth.py`
- `core/migrations/0023_scraperhealth_notification_fields.py`

### 3.2 Registro unico de scrapers operados por la capa de salud

Se centralizo un registro de scrapers en `ScraperHealthService.REGISTRY`.

Scrapers contemplados hoy:

- `lotoven_triples`
- `tuazar_triples`
- `lotoven_animalitos`
- `condor_animalitos`

Cada definicion incluye:

- clave del scraper,
- nombre visible,
- comando Django asociado,
- ventana de negocio base,
- umbral de staleness.

Esto permite que la operacion trate a los scrapers de forma homogenea aunque internamente sus comandos sigan siendo distintos.

### 3.3 Ejecucion instrumentada

La ejecucion ahora puede pasar por `ScraperHealthService.run_registered(scraper_key)`.

Comportamiento aplicado:

1. marca el scraper como `running`,
2. ejecuta el comando real,
3. si termina bien marca `success`,
4. si falla marca `failed`,
5. persiste mensaje y traceback resumido,
6. incrementa `consecutive_failures` cuando corresponde.

Esto ya no depende de revisar stdout manualmente para entender si la ultima corrida termino bien o mal.

### 3.4 Deteccion de alertas activas

La capa actual calcula alertas activas por scraper con tres clases de problema:

- `failed_today`
- `missing_today`
- `stale`

Reglas hoy vigentes:

- `failed_today`: la ultima corrida de hoy fallo.
- `missing_today`: dentro del horario operativo no existe una corrida exitosa registrada en el dia.
- `stale`: existe ultimo OK, pero quedo viejo respecto al umbral definido.

Importante: esta deteccion es por salud general del scraper, no por grupo funcional persistido.

### 3.5 Notificacion interna por email

Se implemento `ScraperNotificationService` para enviar alertas internas por email.

Capacidades aplicadas:

- destinatarios directos por `SCRAPER_ALERT_EMAILS`,
- destinatarios por usuarios concretos,
- destinatarios por grupos de Django,
- cooldown configurable por minutos,
- firma de notificacion para evitar reenvio repetido del mismo estado,
- envio forzado cuando operacion necesita re-alertar manualmente.

Variables de entorno usadas:

- `SCRAPER_ALERT_EMAILS`
- `SCRAPER_ALERT_USERNAMES`
- `SCRAPER_ALERT_GROUPS`
- `SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES`
- `DEFAULT_FROM_EMAIL`

### 3.6 Comandos operativos agregados

Comandos hoy disponibles para esta capa:

- `python manage.py run_scraper_suite`
- `python manage.py run_scraper_suite --notify`
- `python manage.py notify_scraper_alerts --dry-run`
- `python manage.py notify_scraper_alerts`

Objetivo operativo:

- correr todos los scrapers registrados bajo una misma capa de salud,
- evaluar alertas al finalizar,
- probar destinatarios y alertas sin enviar correo real.

### 3.7 Exposicion en Django Admin

Se agrego admin para `ScraperHealth`.

Lo que ya ofrece:

- resumen visual con total, OK, alertas activas, sin OK hoy, stale y fallo hoy,
- filtros por estado y tipo de alerta,
- detalle por scraper con ultimo error y timestamps relevantes,
- accion para forzar envio inmediato de alerta interna,
- accion para resetear estado de notificacion.

Esto convierte a Django Admin en la consola minima de operacion para salud de scrapers.

### 3.8 Integracion de tareas

La capa de tareas ya puede invocar los scrapers mediante `ScraperHealthService`.

Esto aplica a:

- triples Lotoven,
- triples TuAzar,
- animalitos Lotoven,
- animalitos Condor.

Tambien existe una tarea para disparar `notify_scraper_alerts`.

## 4. Criterio operativo que quedo vigente

Despues de este sprint, la salud operativa del scraper se interpreta asi:

- `SUCCESS` no significa que todo el dominio funcional este perfecto; significa que la corrida controlada termino sin excepcion y quedo registrada como exitosa.
- una alerta activa significa que hay una condicion operativa visible que merece revision del equipo.
- la deduplicacion actual ocurre a nivel de notificacion, no a nivel de incidente de negocio.

En otras palabras: se resolvio monitoreo tactico del scraper, no contingencia funcional completa del resultado.

## 5. Lo que este sprint si resolvio

- Visibilidad centralizada del ultimo estado de cada scraper.
- Persistencia del ultimo error sin depender de logs externos.
- Deteccion de ausencia de OK del dia.
- Deteccion de scrapers stale.
- Alerta interna por email con cooldown.
- Capacidad de re-alertar manualmente desde admin.
- Runner comun para ejecutar scrapers registrados con monitoreo.
- Cobertura de pruebas sobre los casos principales del monitor y la notificacion.

## 6. Lo que este sprint no resolvio

Esto debe quedar explicitamente asentado para no sobredimensionar la solucion actual.

### 6.1 No existe incidente formal por grupo afectado

Hoy no existe un modelo de incidente por:

- proveedor,
- fecha,
- horario,
- grupo funcional esperado.

`ScraperHealth` mantiene estado agregado por scraper. No reemplaza un modulo de incidentes.

### 6.2 No existe trazabilidad por ejecucion individual

Hoy no se persiste una fila por corrida con:

- grupos esperados,
- grupos detectados,
- grupos persistidos,
- evidencia estructurada por corrida.

Se conserva el ultimo estado del scraper, no el historial completo de ejecuciones.

### 6.3 No existe carga manual controlada de contingencia

Todavia no existe en el backend actual:

- bandeja de incidentes,
- detalle del incidente,
- formulario guiado para cargar solo el grupo afectado,
- cierre de incidente con trazabilidad completa.

### 6.4 No existe distincion formal entre resultado automatico y manual

Los modelos `CurrentResult` y `AnimalitoResult` siguen sin una marca nativa de origen como:

- `automatic_valid`
- `manual_contingency`

Esto significa que la auditoria completa automatico/manual todavia no esta cerrada.

### 6.5 El canal principal implementado es email, no Telegram

La capa actual de alerta opera por email. No hay integracion nativa con Telegram o Discord en el estado revisado del repo.

### 6.6 La validacion actual es tecnica, no funcional por grupo persistido

La salud actual responde a:

- ultima corrida fallida,
- falta de corrida exitosa del dia,
- staleness del ultimo OK.

Todavia no responde de manera estricta a:

- si el grupo esperado quedo usable en la base,
- si hubo persistencia parcial,
- si un horario concreto quedo faltante aunque el comando haya terminado sin excepcion.

## 7. Decisiones tacticas que quedan como precedente

Estas decisiones ya deben considerarse base del siguiente tramo:

1. La salud del scraper se monitorea dentro de Django, no en una plataforma externa.
2. La visibilidad operativa minima vive en Django Admin.
3. Las alertas se deduplican con firma y cooldown para evitar spam.
4. La ejecucion de scrapers debe pasar por una capa comun cuando sea posible.
5. El siguiente sprint debe construir incidente y carga manual encima de esta base, no en paralelo ni por fuera.

## 8. Riesgos que siguen abiertos

Los siguientes riesgos siguen vigentes aun con lo ya aplicado:

- Un scraper puede marcar `SUCCESS` aunque funcionalmente falte un grupo esperado.
- Operacion puede enterarse de que un scraper esta mal, pero no tener aun una via formal para resolver desde Django.
- No existe auditoria completa de intervencion manual en resultados.
- El seguimiento historico de ejecuciones sigue limitado.
- La alerta por email mejora tiempo de respuesta, pero no necesariamente es el canal mas rapido para contingencia critica.

## 9. Uso operativo actual

### 9.1 Ejecucion recomendada

Para correr scrapers bajo monitoreo:

```bash
python manage.py run_scraper_suite
python manage.py run_scraper_suite --notify
```

### 9.2 Validacion de alertas

Para revisar sin enviar correo:

```bash
python manage.py notify_scraper_alerts --dry-run
```

Para enviar alertas activas:

```bash
python manage.py notify_scraper_alerts
```

### 9.3 Operacion desde admin

El equipo operativo puede entrar a `Scraper health` en Django Admin para:

- ver el resumen de salud,
- inspeccionar el ultimo error,
- identificar scrapers sin OK hoy,
- forzar notificacion,
- limpiar el estado de notificacion si hace falta repetir aviso.

## 10. Base recomendada para el siguiente tramo

El siguiente bloque de trabajo debe construirse sobre esta secuencia:

### Fase A - instrumentacion por ejecucion

Agregar un registro por corrida individual que permita saber:

- que grupos se esperaban,
- cuales se detectaron,
- cuales se persistieron,
- por que se considero fallo real.

### Fase B - incidente formal

Crear entidad de incidente con clave funcional minima:

- scraper,
- proveedor o grupo,
- fecha,
- horario,
- estado,
- alertado,
- resuelto por,
- resuelto en.

### Fase C - carga manual controlada

Incorporar formulario restringido por incidente para:

- cargar solo el grupo afectado,
- validar formato,
- guardar con origen manual,
- cerrar incidente.

### Fase D - trazabilidad fuerte

Agregar al resultado o a un registro de intervencion:

- origen,
- usuario,
- timestamp,
- incidente origen,
- valor anterior,
- valor nuevo.

### Fase E - canal tactico de alerta mas rapido

Evaluar incorporar Telegram como canal primario de contingencia, manteniendo email como respaldo si hace falta.

## 11. Criterio de lectura correcta de este sprint

Si alguien pregunta "que ya tenemos hoy", la respuesta correcta es esta:

- ya existe monitoreo interno de salud por scraper,
- ya existe alerta interna por email con deduplicacion basica,
- ya existe visibilidad operativa en admin,
- todavia no existe contingencia funcional completa por incidente y carga manual controlada.

Ese es el punto exacto del proyecto al cierre de este tramo.
