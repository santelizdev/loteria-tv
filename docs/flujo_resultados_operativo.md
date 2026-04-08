# Flujo operativo de resultados

## Objetivo

Este documento deja descrito el comportamiento correcto y esperado del flujo de resultados en el estado actual del proyecto, sin proponer cambios de codigo.

Cubre:

- quien busca resultados;
- cuando los busca;
- como se normalizan y almacenan;
- como se exponen en admin y API;
- como la PWA arma las tablas dinamicas para HOY y AYER en triples y animalitos.

## Resumen ejecutivo

El flujo actual tiene cuatro capas:

1. Scheduler y bootstrap:
   Celery Beat dispara scrapers cada 3 minutos y el arranque del stack puede hacer warm-up si no hay un OK reciente.
2. Scrapers y persistencia:
   cada scraper consulta su fuente, normaliza provider/horario/campos, guarda en `CurrentResult` o `AnimalitoResult` y limpia cache.
3. Exposicion operacional:
   Django Admin muestra current, archive, salud del scraper, ejecuciones e incidentes.
4. Consumo en TV:
   la PWA consulta `api/results` y `api/animalitos`, refresca HOY cada 60s, AYER cada 30 min y rota tablas por grupos.

## 1. Quien busca resultados

### 1.1 Scheduler principal

El scheduler principal es `Celery Beat`.

Tareas configuradas:

- `core.tasks.scrape_triples`
- `core.tasks.scrape_tuazar_triples`
- `core.tasks.scrape_animalitos`
- `core.tasks.scrape_condor_animalitos`
- `core.tasks.archive_daily`
- `core.tasks.notify_scraper_alerts`
- `core.tasks.scrape_cruz_daily_content`
- `core.tasks.purge_scraper_executions`

Referencia:

- [config/settings.py](/Users/delorean/loteria-tv/config/settings.py)
- [core/tasks.py](/Users/delorean/loteria-tv/core/tasks.py)

### 1.2 Bootstrap al iniciar el stack

Cuando el contenedor `app` arranca con `WARM_SCRAPERS_ON_BOOT=1`, se ejecuta `warm_scraper_data`.

Comportamiento:

- si el scraper no tiene exito previo, corre;
- si el ultimo exito es de otro dia, corre;
- si el ultimo exito supera la antiguedad maxima, corre;
- si el OK es reciente, no corre;
- para cruz diaria, solo intenta desde las 06:00 Venezuela.

Referencia:

- [docker/app/entrypoint.sh](/Users/delorean/loteria-tv/docker/app/entrypoint.sh)
- [core/management/commands/warm_scraper_data.py](/Users/delorean/loteria-tv/core/management/commands/warm_scraper_data.py)

## 2. Cuando se buscan resultados

### 2.1 Cadencia programada por Beat

Horarios actuales:

| Flujo | Tarea | Cadencia | Ventana |
| --- | --- | --- | --- |
| Triples Lotoven | `scrape_triples` | `*/3` | `08:00-22:59` |
| Triples TuAzar | `scrape_tuazar_triples` | `1-59/3` | `08:00-22:59` |
| Animalitos Lotoven | `scrape_animalitos` | `2-59/3` | `08:00-22:59` |
| Animalitos Condor | `scrape_condor_animalitos` | `*/3` | `09:00-22:59` |

Interpretacion practica:

- minuto `00`: Triples Lotoven y Condor;
- minuto `01`: TuAzar triples;
- minuto `02`: Lotoven animalitos;
- minuto `03`: vuelve el ciclo.

Esto deja el scraping repartido en tres offsets para no golpear todo a la vez.

### 2.2 Consulta desde PWA

La PWA no scrappea.

Hace polling a la API:

- resultados de HOY: cada `60s`;
- resultados de AYER: cada `30 min`;
- contexto visual: cada `5 min`;
- cruz diaria: cada `10 min`.

Referencia:

- [pwa/app.js](/Users/delorean/loteria-tv/pwa/app.js)

## 3. Como se buscan y normalizan los resultados

## 3.1 Flujo comun de ejecucion

Todas las tareas de scraper pasan por `ScraperHealthService.run_registered(scraper_key)`.

Secuencia:

1. se crea `ScraperExecution` con estado `running`;
2. se marca `ScraperHealth` como `running`;
3. se ejecuta el management command real;
4. si falla tecnicamente:
   se registra `FAILED` y se puede abrir incidente tecnico;
5. si termina:
   se comparan grupos esperados vs grupos persistidos;
6. se pueden abrir o resolver incidentes;
7. el monitor queda en `SUCCESS` o `FAILED` segun el impacto funcional.

Referencia:

- [core/services/scraper_health_service.py](/Users/delorean/loteria-tv/core/services/scraper_health_service.py)
- [core/services/scraper_execution_service.py](/Users/delorean/loteria-tv/core/services/scraper_execution_service.py)

## 3.2 Normalizacion de triples

### Fuentes

- Lotoven:
  `scrape_lotoven_tables`
- TuAzar:
  `scrape_tuazar_tables`

### Modelo destino

- `CurrentResult`

### Clave funcional

- `provider + draw_date + draw_time`

### Reglas relevantes

- los horarios futuros del mismo dia se filtran por cutoff local;
- providers agrupados se guardan separados por grupo:
  `Triple Caracas A`, `Triple Caracas B`, `Triple Caracas C`, etc;
- signos zodiacales se guardan en `extra.signo`;
- se actualiza o inserta por `update_or_create`;
- al final se invalida cache de triples.

Referencia:

- [core/management/commands/scrape_lotoven_tables.py](/Users/delorean/loteria-tv/core/management/commands/scrape_lotoven_tables.py)
- [core/management/commands/scrape_tuazar_tables.py](/Users/delorean/loteria-tv/core/management/commands/scrape_tuazar_tables.py)
- [core/models/current_result.py](/Users/delorean/loteria-tv/core/models/current_result.py)

## 3.3 Normalizacion de animalitos

### Fuentes

- Lotoven:
  `scrape_lotoven_animalitos`
- Condor:
  `scrape_condor_animalitos`

### Modelo destino

- `AnimalitoResult`

### Clave funcional

- `provider + draw_date + draw_time`

### Reglas relevantes

- nombre del provider se canonicaliza;
- se preserva el numero como string para no romper `0` vs `00`;
- ahora la captura de imagen soporta `data-src`, `data-lazy-src`, `data-original`, `srcset` y `src`;
- provider logo y animal image se guardan como URL completa;
- se filtran filas futuras por cutoff para el dia actual;
- al final se invalida cache de animalitos.

Referencia:

- [core/management/commands/scrape_lotoven_animalitos.py](/Users/delorean/loteria-tv/core/management/commands/scrape_lotoven_animalitos.py)
- [core/management/commands/scrape_condor_animalitos.py](/Users/delorean/loteria-tv/core/management/commands/scrape_condor_animalitos.py)
- [core/models/animalito_result.py](/Users/delorean/loteria-tv/core/models/animalito_result.py)
- [core/services/provider_catalog_service.py](/Users/delorean/loteria-tv/core/services/provider_catalog_service.py)

## 4. Como se almacenan

## 4.1 Tablas current

Uso esperado:

- `CurrentResult`:
  triples del dia operativo;
- `AnimalitoResult`:
  animalitos del dia operativo.

Ambas tablas:

- permiten solo una fila por provider, fecha y hora;
- guardan timestamps de creacion/actualizacion;
- pueden marcar el origen:
  `automatic_valid`, `automatic_fallback`, `manual_contingency`.

## 4.2 Tablas archive

Uso esperado:

- `ResultArchive`:
  historial de triples;
- `AnimalitoArchive`:
  historial de animalitos.

La tarea nocturna:

1. archiva AYER;
2. limpia current de AYER;
3. aplica retencion sobre archive.

Referencia:

- [core/management/commands/archive_daily_triples.py](/Users/delorean/loteria-tv/core/management/commands/archive_daily_triples.py)
- [core/management/commands/archive_daily_animalitos.py](/Users/delorean/loteria-tv/core/management/commands/archive_daily_animalitos.py)
- [core/management/commands/run_daily_retention.py](/Users/delorean/loteria-tv/core/management/commands/run_daily_retention.py)
- [core/models/result_archive.py](/Users/delorean/loteria-tv/core/models/result_archive.py)
- [core/models/animalito_archive.py](/Users/delorean/loteria-tv/core/models/animalito_archive.py)

## 5. Como se muestran en admin

## 5.1 Current visibles

Admin de lectura:

- `CurrentResult`
- `AnimalitoResult`

Comportamiento esperado:

- permiten buscar por provider y fecha;
- muestran el dato actual persistido;
- no permiten alta manual directa desde ese admin;
- si hubo contingencia manual, el `result_origin` y `source_incident` lo reflejan.

Referencia:

- [core/admin_configs/current_result.py](/Users/delorean/loteria-tv/core/admin_configs/current_result.py)
- [core/admin_configs/animalito_result.py](/Users/delorean/loteria-tv/core/admin_configs/animalito_result.py)

## 5.2 Historial visible

Admin de lectura:

- `ResultArchive`
- `AnimalitoArchive`

Uso:

- consulta del dia anterior y dias retenidos;
- respaldo historico operativo.

Referencia:

- [core/admin_configs/result_archive.py](/Users/delorean/loteria-tv/core/admin_configs/result_archive.py)
- [core/admin_configs/animalito_archive.py](/Users/delorean/loteria-tv/core/admin_configs/animalito_archive.py)

## 5.3 Salud y auditoria operativa

Admins relevantes:

- `ScraperHealth`
- `ScraperExecution`
- `ScraperIncident`

Uso esperado:

- `ScraperHealth`:
  estado agregado del scraper;
- `ScraperExecution`:
  corrida por corrida;
- `ScraperIncident`:
  faltantes funcionales o fallos tecnicos por scraper/provider/horario.

Referencia:

- [core/admin_configs/scraper_health.py](/Users/delorean/loteria-tv/core/admin_configs/scraper_health.py)
- [core/admin_configs/scraper_execution.py](/Users/delorean/loteria-tv/core/admin_configs/scraper_execution.py)
- [core/admin_configs/scraper_incident.py](/Users/delorean/loteria-tv/core/admin_configs/scraper_incident.py)

## 6. Como se exponen por API

## 6.1 Triples

Endpoint:

- `/api/results/`

Comportamiento esperado:

- requiere `code`;
- si no se pasa `date`, intenta HOY;
- si HOY no existe, usa la ultima fecha disponible;
- si se pide fecha historica, puede devolver la ultima fecha operativa `<= requested_date`;
- usa `CurrentResult` para HOY;
- usa `ResultArchive` para historico;
- serializa:
  `provider`, `time`, `number`, `image`.

## 6.2 Animalitos

Endpoint:

- `/api/animalitos/`

Comportamiento esperado:

- requiere `code`;
- mismo criterio de fecha de triples;
- usa `AnimalitoResult` para HOY;
- usa `AnimalitoArchive` para historico;
- serializa:
  `provider`, `time`, `number`, `animal`, `image`, `provider_logo_url`.

## 6.3 Cache HTTP/logica

Comportamiento esperado actual:

- la API responde con `Cache-Control: no-store`;
- la PWA agrega `nocache=1` al consultar fechas;
- los scrapers invalidan el keyspace de resultados al persistir.

Referencia:

- [core/api/views.py](/Users/delorean/loteria-tv/core/api/views.py)

## 7. Comportamiento correcto de la PWA

## 7.1 Boot

Secuencia esperada:

1. registra service worker;
2. inicia reloj;
3. asegura activation code;
4. conecta websocket de device;
5. trae contexto de sucursal y rotacion;
6. refresca resultados;
7. refresca cruz diaria;
8. arranca la rotacion visual.

Importante:

- el websocket actual sirve para eventos del device;
- la actualizacion de resultados en la practica depende del polling;
- `resultsUpdated` se usa como trigger de refresco, no como payload canonico final.

Referencia:

- [pwa/deviceManager.js](/Users/delorean/loteria-tv/pwa/deviceManager.js)
- [pwa/app.js](/Users/delorean/loteria-tv/pwa/app.js)

## 7.2 Frecuencia de refresco en TV

Cadencias:

- HOY triples y animalitos:
  `60s`
- AYER triples y animalitos:
  `30 min`
- contexto:
  `5 min`
- cruz diaria:
  `10 min`

## 7.3 Comportamiento correcto de tablas dinamicas de triples

### Datos usados

La vista de triples consume:

- `state.triplesTodayRows`
- `state.triplesYesterdayRows`

### Como se arma la grilla

- la PWA construye cards con `buildTripleCards`;
- providers agrupados usan tarjetas especiales:
  `Triple Caliente`, `Triple Caracas`, `Triple Tachira`, `Triple Zamorano`, `Triple Zulia`;
- `Triple Gana` y `Super Gana` se combinan en una sola card;
- la grilla muestra `3` cards por pagina visual.

### Como se ve cada card

#### Card grouped

Muestra dentro de una misma card:

- seccion HOY;
- seccion AYER;
- columnas A/B/C o A/C segun provider;
- filas por horario esperado.

#### Card single o paired

Muestra por fila:

- hora;
- columna HOY;
- columna AYER.

### Rotacion correcta de triples

Comportamiento esperado:

- la TV permanece en modo `triples`;
- avanza por grupos de 3 cards;
- al terminar todos los grupos de triples pasa a `animalitos`;
- si entra un cambio nuevo de HOY, la PWA enfoca el grupo del provider afectado para reducir latencia visual.

### Diagrama de triples

```text
TRIPLES
  datos:
    HOY  -> /api/results?date=hoy
    AYER -> /api/results?date=ayer

  buildTripleCards()
    -> grouped cards:
       Triple Caliente
       Triple Caracas
       Triple Tachira
       Triple Zamorano
       Triple Zulia
    -> single cards:
       Chance Astral
       Trio Activo
       Triple Facil
       Triple Centena
    -> paired card:
       Triple Gana / Super Gana

  renderTriplesPage()
    -> chunk(cards, 3)
    -> grupo 1
    -> grupo 2
    -> ...
    -> fin triples
    -> cambia a modo animalitos
```

## 7.4 Comportamiento correcto de tablas dinamicas de animalitos

### Datos usados

La vista de animalitos consume:

- `state.animalitosTodayRows`
- `state.animalitosYesterdayRows`
- `state.animalitosProviders`

### Como se arma la grilla

- se muestran `3` providers por pagina visual;
- cada provider ocupa una columna;
- las filas se pintan por horario esperado del provider;
- el horario ya no se redondea a la hora exacta:
  se conserva `HH:MM`.

### Regla de slots por provider

Ejemplos:

- `Guacharito`:
  `08:30` a `19:30`
- `Guacharo`:
  `08:00` a `19:00`
- `Lotto Rey`:
  `08:30` a `19:30`
- `Mega Animal 40`:
  `09:00` a `20:00`
- `Condor Gana`:
  `09:00` a `19:00`

### Como se ve cada columna

Cada fila muestra:

- hora;
- numero;
- nombre del animal;
- imagen del animal si existe;
- si la imagen falla, puede usar logo del provider como fallback visual.

### Rotacion correcta de animalitos

Comportamiento esperado:

- entra desde triples;
- grupo actual arranca en `today`;
- si existe `yesterday`, muestra ese mismo grupo despues;
- luego avanza al siguiente grupo de providers;
- al terminar todos los grupos vuelve a triples.

### Diagrama de animalitos

```text
ANIMALITOS
  datos:
    HOY  -> /api/animalitos?date=hoy
    AYER -> /api/animalitos?date=ayer

  computeProviders()
    -> providers ordenados

  renderAnimalitosGroup()
    -> chunk(providers, 3)
    -> grupo actual
       -> day=today
       -> day=yesterday si existe
    -> siguiente grupo
    -> ...
    -> fin animalitos
    -> vuelve a triples
```

## 7.5 Diagrama de secuencia end-to-end

```text
Celery Beat / warm_scraper_data
    |
    v
ScraperHealthService.run_registered()
    |
    v
Management command real
    |
    +--> fetch fuente HTML
    +--> parse y normalizacion
    +--> upsert Provider
    +--> upsert CurrentResult / AnimalitoResult
    +--> invalidate cache
    |
    v
ScraperExecutionService
    |
    +--> persisted_groups
    +--> expected_groups
    +--> missing_groups
    +--> incidentes si aplica
    |
    v
Admin / API
    |
    +--> Admin current/archive/salud/incidentes
    +--> /api/results
    +--> /api/animalitos
    |
    v
PWA
    |
    +--> refresh HOY cada 60s
    +--> refresh AYER cada 30 min
    +--> render triples
    +--> render animalitos
    +--> rotacion continua
```

## 8. Checklist del comportamiento correcto

## 8.1 Scraping

Debe cumplirse:

- cada scraper corre en su offset de 3 minutos;
- no guarda filas futuras del mismo dia;
- persiste por provider + fecha + hora;
- invalida cache al terminar.

## 8.2 Persistencia

Debe cumplirse:

- HOY vive en tablas current;
- AYER e historico viven en archive;
- la tarea nocturna mueve AYER desde current a archive.

## 8.3 Admin

Debe cumplirse:

- `CurrentResult` y `AnimalitoResult` muestran el dia operativo;
- `ResultArchive` y `AnimalitoArchive` muestran historico;
- `ScraperHealth`, `ScraperExecution` y `ScraperIncident` dan auditoria operacional.

## 8.4 PWA

Debe cumplirse:

- triples se muestran HOY y AYER dentro de la misma card;
- animalitos se muestran por dia y por grupos de providers;
- los slots de animalitos respetan minutos reales, incluyendo `:30`;
- si entra un dato nuevo de HOY, la TV prioriza visualmente el grupo afectado;
- terminado animalitos, siempre vuelve a triples.

## 9. Notas operativas importantes

- En Docker local, el puerto publicado al host es `8080` via `gateway`, no `8000`.
- El contenedor `app` escucha `8000` solo dentro de la red Docker.
- El acceso correcto local es:
  `http://localhost:8080/`
- El websocket actual no entrega el dataset final de resultados; la fuente canonica de refresco es el polling de API.

## 10. Alcance real del documento

Este documento describe el comportamiento correcto del flujo actual.

No afirma que las fuentes externas sean estables para siempre.

Si una web cambia:

- nombre de provider,
- estructura HTML,
- horarios reales publicados,
- o estrategia de lazy-load de imagenes,

entonces habra que revisar el scraper o el catalogo correspondiente.
