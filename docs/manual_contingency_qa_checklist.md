# QA operativo - contingencia manual de scrapers

Fecha de referencia: 2026-03-23

## 1. Objetivo

Validar en local y staging que el flujo de contingencia manual:

- detecta incidente real,
- notifica por Telegram,
- permite carga manual controlada,
- deja trazabilidad completa,
- restringe la operacion por grupo resolvedor,
- y vuelve a abrir incidente si la automatizacion no se recupera en corridas posteriores.

## 2. Permisos finos

### Grupo viewer

Debe poder:

- ver `Scraper health`,
- ver `Scraper executions`,
- ver `Scraper incidents`,
- ver `Manual result interventions`.

No debe poder:

- resolver incidentes,
- ejecutar la carga manual controlada,
- usar acciones de admin de resolucion.

### Grupo resolver

Debe poder:

- todo lo del viewer,
- abrir la vista `Carga manual controlada`,
- marcar incidente resuelto desde el flujo manual,
- reabrir incidentes si hace falta,
- disparar reenvio Telegram del incidente.

### Superuser

Debe poder operar todo sin restricciones.

## 3. Checklist local

### 3.1 Deteccion tecnica

1. Forzar una excepcion en un scraper.
2. Confirmar que se crea `ScraperExecution` con `status=failed`.
3. Confirmar que se crea `ScraperIncident` abierto.
4. Confirmar que el monitor `ScraperHealth` queda en `FAILED`.
5. Confirmar que Telegram sale una sola vez para ese incidente.

### 3.2 Deteccion funcional por grupo

1. Forzar una corrida con grupo esperado faltante.
2. Confirmar que `ScraperExecution` queda en `status=incident`.
3. Confirmar que `missing_groups` refleja el grupo exacto.
4. Confirmar que existe incidente abierto con `provider_name` y `draw_time`.
5. Confirmar que Telegram sale una sola vez.

### 3.3 Carga manual controlada

1. Entrar al incidente abierto en Django Admin.
2. Abrir `Carga manual controlada`.
3. Confirmar que provider y horario vienen bloqueados cuando el incidente ya los define.
4. Cargar el valor manual.
5. Guardar.
6. Confirmar que el incidente pasa a `RESOLVED`.
7. Confirmar que el resultado queda con:
   - `result_origin=manual_contingency`
   - `source_incident=<id del incidente>`
8. Confirmar que se crea `ManualResultIntervention`.
9. Confirmar que `previous_snapshot` y `new_snapshot` reflejan el cambio.

### 3.4 Reapertura por falta de recuperacion automatica

1. Resolver manualmente un incidente de grupo.
2. Esperar la siguiente corrida programada o forzar una corrida del mismo scraper.
3. Hacer que el scraper siga sin recuperar automaticamente ese grupo.
4. Confirmar que el incidente se reabre.
5. Confirmar que Telegram vuelve a salir una vez al reabrirse.
6. Confirmar que no spamea en cada corrida posterior mientras siga abierto.

### 3.5 Recuperacion automatica real

1. Con el incidente abierto o reabierto, ejecutar una corrida donde el scraper ya reponga el grupo automaticamente.
2. Confirmar que el incidente pasa a `RESOLVED`.
3. Confirmar que el resultado visible vuelve a `result_origin=automatic_valid`.
4. Confirmar que `source_incident` vuelve a `NULL`.

## 4. Semantica operativa recomendada

### 4.1 Por cuanto tiempo queda habilitada la carga manual

La carga manual debe estar habilitada solo mientras el incidente este `OPEN`.

Cuando se guarda la intervencion:

- el incidente se resuelve formalmente,
- el valor queda marcado como `manual_contingency`,
- la intervencion queda auditada,
- y la vista deja de ser el camino principal para seguir editando.

Si la automatizacion no se recupera en la siguiente corrida relevante, el sistema reabre el incidente y el flujo vuelve a estar disponible.

### 4.2 Que pasa con el scraper despues de la contingencia

El scraper no se detiene por una carga manual.

Debe seguir corriendo con su scheduler normal.

La contingencia manual sirve para continuidad operativa, no para apagar la recuperacion automatica.

### 4.3 Debe volver a notificar en la proxima corrida

Si el scraper sigue fallando o sigue sin recuperar automaticamente el grupo, si: debe volver a generar una notificacion al reabrirse el incidente.

Pero no debe spamear en cada corrida.

Regla operativa correcta:

- primera deteccion: alerta,
- carga manual: contiene el impacto,
- siguiente corrida sin recuperacion automatica: reabre y alerta otra vez una vez,
- corridas posteriores del mismo incidente ya abierto: actualizan ocurrencia, sin spam repetido.

Eso es mejor que “silenciar” el problema solo porque existe un dato manual cargado.

## 5. Validacion en staging con Postgres

## 5.1 Migraciones

```bash
python manage.py showmigrations core
python manage.py migrate
python manage.py makemigrations --check --dry-run core
```

Criterio:

- todas las migraciones aplican,
- no hay drift de modelos,
- no aparece una migracion nueva inesperada.

## 5.2 Suite minima recomendada

```bash
python manage.py test core.test_manual_incident_resolution core.test_scraper_execution_flow core.test_scraper_phase0 core.tests.ScraperNotificationServiceTestCase
```

## 5.3 Smoke test funcional en staging

1. Configurar `SCRAPER_TELEGRAM_BOT_TOKEN`.
2. Configurar `SCRAPER_TELEGRAM_CHAT_IDS`.
3. Configurar `SCRAPER_ADMIN_BASE_URL`.
4. Forzar incidente controlado.
5. Confirmar recepcion por Telegram.
6. Resolver por carga manual.
7. Confirmar trazabilidad en admin.
8. Reforzar una corrida posterior para verificar reapertura si no hay recuperacion automatica.

## 6. Riesgos a vigilar en staging

- Usuarios staff sin grupo correcto pudiendo resolver.
- Resultados editables por fuera del flujo manual.
- Incidentes manuales que no reabren cuando la automatizacion sigue rota.
- Telegram duplicando mensajes del mismo incidente.
- Resultados manuales que no vuelven a `automatic_valid` cuando el scraper se recupera.
