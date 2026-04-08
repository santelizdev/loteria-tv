# Checklist de verificacion operativa en vivo

## Objetivo

Este documento sirve para auditar en vivo, sin cambiar codigo, que el flujo de resultados este operando correctamente para:

- scrapers;
- persistencia en current;
- visibilidad en admin;
- exposicion en API;
- visualizacion en PWA.

Aplica a:

- triples;
- animalitos;
- HOY;
- AYER;
- todos los providers visibles actualmente.

## Regla operativa base

Cada verificacion en vivo debe responder estas cinco preguntas:

1. La fuente ya publico el resultado esperado para ese provider y horario.
2. El scraper correcto corrio dentro de la ventana esperada.
3. El resultado quedo persistido en la tabla correcta.
4. El resultado se ve en admin y sale por la API correcta.
5. La PWA lo muestra en la card, grupo y franja horaria correctos.

## Ventanas de verificacion recomendadas

Usar esta escala para cada horario objetivo:

- `T0`: hora oficial esperada de publicacion.
- `T+3m`: primera ventana realista de llegada al scraper.
- `T+6m`: segunda verificacion operativa.
- `T+12m`: umbral de gracia funcional ya relevante para incidente operativo.
- `T+15m`: ya hay desvio visible serio para TV aunque la fuente publique tarde.
- `T+20m`: tratar como atraso fuerte y abrir investigacion operativa.

## Preparacion antes de iniciar la auditoria

Debe estar disponible:

- acceso a Django Admin;
- acceso a la PWA;
- acceso a logs de `worker`, `beat`, `app` y `gateway`;
- al menos una forma de consultar la fuente externa del provider;
- reloj operativo alineado a hora Venezuela.

## Donde mirar en cada capa

### Fuente externa

Validar:

- si el provider publico o no;
- la hora exacta publicada;
- el valor visible;
- si la imagen visible existe o es lazy-load;
- si el provider cambio nombre o layout.

### Scraper

Validar:

- que `beat` haya despachado la tarea;
- que `worker` la haya recibido;
- que el management command termine en `succeeded`;
- que no haya excepciones de parseo o HTTP;
- que el total guardado tenga sentido para esa franja.

### Persistencia

Validar:

- `CurrentResult` para triples de HOY;
- `AnimalitoResult` para animalitos de HOY;
- `ResultArchive` y `AnimalitoArchive` para AYER;
- unicidad por provider + fecha + hora;
- `result_origin` correcto;
- imagen/logo persistidos cuando aplique.

### Admin

Validar:

- fila visible con provider correcto;
- horario correcto;
- numero correcto;
- `result_origin=automatic_valid` si vino por scraper normal;
- `source_incident` vacio si no hubo contingencia.

### PWA

Validar:

- card correcta;
- grupo correcto;
- franja horaria correcta;
- dato visible en HOY;
- dato historico visible en AYER cuando ya fue archivado;
- para animalitos, nombre, numero e imagen o fallback visual.

## Checklist rapido por corrida

Usar esta secuencia para cualquier provider/horario:

- Confirmar la hora objetivo.
- Esperar `T+3m`.
- Revisar que el task fue enviado por `beat`.
- Revisar que el `worker` recibio y ejecuto la tarea correcta.
- Confirmar en admin que la fila existe en current.
- Confirmar por API que el provider/hora sale en el payload.
- Confirmar en PWA que el resultado aparece en la tabla correcta.
- Si no aparece, repetir en `T+6m`.
- Si a `T+12m` no aparece pero la fuente ya publico, marcar falla funcional.
- Si a `T+20m` no aparece, escalar como atraso severo.

## Comandos sugeridos para verificacion en vivo

### Logs

```bash
docker compose logs --tail=200 beat
docker compose logs --tail=200 worker
docker compose logs --tail=200 app
docker compose logs --tail=200 gateway
```

### API local

Reemplazar `CODIGO_VALIDO`.

```bash
curl -s "http://localhost:8080/api/results/?code=CODIGO_VALIDO&date=YYYY-MM-DD&nocache=1"
curl -s "http://localhost:8080/api/animalitos/?code=CODIGO_VALIDO&date=YYYY-MM-DD&nocache=1"
```

### Inspeccion operativa en admin

Revisar:

- `CurrentResult`
- `AnimalitoResult`
- `ResultArchive`
- `AnimalitoArchive`
- `ScraperHealth`
- `ScraperExecution`
- `ScraperIncident`

## Matriz operativa de triples

## A. Triples Lotoven

Scraper:

- `lotoven_triples`

Cadencia:

- cada 3 minutos, offset `*/3`

### A.1 Trio Activo

Horarios esperados:

- `08:00` a `19:00`

Checklist por horario:

- fuente visible;
- fila en `CurrentResult`;
- card `Trio Activo` en PWA;
- visible en HOY;
- al archivarse, visible en AYER.

### A.2 Triple Facil

Horarios esperados:

- `08:00` a `19:00`

Checklist por horario:

- fuente visible;
- fila en `CurrentResult`;
- card `Triple Facil`;
- visible en HOY;
- al archivarse, visible en AYER.

### A.3 Triple Centena

Horarios esperados:

- `08:00` a `20:00`

Checklist por horario:

- fuente visible;
- fila en `CurrentResult`;
- card `Triple Centena`;
- visible en HOY;
- al archivarse, visible en AYER.

### A.4 Triple Caracas

Providers persistidos:

- `Triple Caracas A`
- `Triple Caracas B`
- `Triple Caracas C`

Horarios esperados:

- `13:00`
- `16:30`
- `19:10`

Checklist por horario:

- confirmar A, B y C en current;
- confirmar que no falte un grupo;
- confirmar que la PWA use una sola card `Triple Caracas`;
- confirmar que cada columna A/B/C muestre el valor correcto;
- confirmar seccion HOY y AYER dentro de la misma card.

### A.5 Triple Caliente

Providers persistidos:

- `Triple Caliente A`
- `Triple Caliente B`
- `Triple Caliente C`

Horarios esperados:

- `13:00`
- `16:30`
- `19:10`

Checklist por horario:

- confirmar A, B y C en current;
- confirmar card agrupada correcta;
- confirmar visibilidad en HOY y AYER.

### A.6 Triple Tachira

Providers persistidos:

- `Triple Tachira A`
- `Triple Tachira B`
- `Triple Tachira C`

Horarios esperados:

- `13:15`
- `16:45`
- `22:00`

Checklist por horario:

- confirmar A, B y C en current;
- confirmar card agrupada correcta;
- confirmar visibilidad del horario exacto en la tabla.

### A.7 Triple Zamorano

Providers persistidos:

- `Triple Zamorano A`
- `Triple Zamorano C`

Horarios esperados:

- `10:00`
- `12:00`
- `14:00`

Checklist por horario:

- confirmar solo A y C;
- confirmar que no se espere columna B en PWA;
- confirmar card `Triple Zamorano` con columnas correctas.

### A.8 Triple Zulia

Providers persistidos:

- `Triple Zulia A`
- `Triple Zulia B`
- `Triple Zulia C`

Horarios esperados:

- `12:45`
- `16:45`
- `19:05`

Checklist por horario:

- confirmar A, B y C;
- confirmar card agrupada correcta;
- confirmar seccion HOY y AYER.

## B. Triples TuAzar

Scraper:

- `tuazar_triples`

Cadencia:

- cada 3 minutos, offset `1-59/3`

### B.1 Chance Astral

Horarios esperados:

- `09:00` a `19:00`

Checklist por horario:

- fila en `CurrentResult`;
- card `Chance Astral`;
- si trae signo, validar que el signo salga concatenado en `number` por API/PWA.

### B.2 Triple Gana

Horarios esperados:

- `13:00`
- `16:00`
- `22:00`

Checklist por horario:

- fila en `CurrentResult`;
- seccion correcta dentro de la card combinada `Triple Gana / Super Gana`;
- HOY y AYER correctos.

### B.3 Super Gana

Horarios esperados:

- `13:00`
- `16:00`
- `22:00`

Checklist por horario:

- fila en `CurrentResult`;
- seccion correcta dentro de la card combinada `Triple Gana / Super Gana`;
- HOY y AYER correctos.

## Matriz operativa de animalitos

## C. Animalitos Lotoven

Scraper:

- `lotoven_animalitos`

Cadencia:

- cada 3 minutos, offset `2-59/3`

### C.1 Guacharito

Horarios esperados:

- `08:30` a `19:30`

Checklist por horario:

- fila en `AnimalitoResult`;
- hora exacta `:30`, no redondeada;
- columna `Guacharito` en PWA;
- numero, nombre e imagen visibles.

### C.2 Guacharo

Horarios esperados:

- `08:00` a `19:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- hora exacta visible;
- numero, nombre e imagen o fallback.

### C.3 Cazaloton

Horarios esperados:

- `09:00` a `19:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- columna correcta en PWA;
- imagen de animalito cargando.

### C.4 La Granjita

Horarios esperados:

- `08:00` a `19:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- nombre canonical `La Granjita`;
- visible en PWA y API.

### C.5 Loto Chaima

Horarios esperados:

- `08:00` a `19:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- nombre canonical correcto;
- visible en PWA.

### C.6 Lotto Activo

Horarios esperados:

- `08:00` a `19:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- visible en card correcta;
- imagen o fallback visual.

### C.7 Lotto Activo Interl

Horarios esperados:

- `08:30` a `19:30`

Checklist por horario:

- validar `:30` exacto;
- fila en `AnimalitoResult`;
- visible en PWA sin correrse a `:00`.

### C.8 Lotto Rey

Horarios esperados:

- `08:30` a `19:30`

Checklist por horario:

- validar `:30` exacto;
- fila en `AnimalitoResult`;
- si hubo contingencia, revisar `result_origin`;
- si no hubo contingencia, esperar `automatic_valid`.

### C.9 Mega Animal 40

Horarios esperados:

- `09:00` a `20:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- visible en card correcta;
- hora exacta en PWA.

### C.10 SelvaPlus

Horarios esperados:

- `08:00` a `19:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- provider canonical `SelvaPlus`;
- imagen/logo funcional.

## D. Animalitos Condor

Scraper:

- `condor_animalitos`

Cadencia:

- cada 3 minutos, offset `*/3`

### D.1 Condor Gana

Horarios esperados:

- `09:00` a `19:00`

Checklist por horario:

- fila en `AnimalitoResult`;
- provider `Condor Gana`;
- imagen generada o publicada correctamente;
- visible en PWA en card correcta.

## Checklist de HOY

Para cada provider y horario esperado de HOY:

- la fuente ya publico;
- el scraper correcto corrio entre `T0` y `T+3m` o `T+6m`;
- la fila existe en current;
- la API la devuelve con `date=hoy`;
- la PWA la muestra en la vista HOY;
- si es animalitos, la hora exacta coincide;
- si es grouped triple, la columna correcta coincide;
- si es single/paired triple, la fila correcta coincide.

## Checklist de AYER

Para cada provider y horario esperado de AYER:

- confirmar que la fila ya fue archivada;
- confirmar que la fila no siga solo en current si ya corrio retencion;
- la API la devuelve con `date=ayer`;
- la PWA la muestra en la seccion AYER correspondiente.

## Checklist visual especifico de PWA

## Triples

Validar:

- cada card grouped muestra HOY y AYER en una misma card;
- `Triple Gana / Super Gana` aparece combinada;
- la rotacion vuelve de animalitos a triples;
- si entra un dato nuevo de HOY, la TV termina enfocando el grupo afectado.

## Animalitos

Validar:

- 3 providers por grupo visual;
- cada provider usa sus horas esperadas reales;
- `:30` sigue siendo `:30`;
- el numero y el nombre coinciden;
- la imagen principal aparece o cae a fallback visual razonable;
- AYER solo aparece cuando realmente hay datos.

## Criterios de clasificacion de hallazgos

## Hallazgo leve

- la fuente publico tarde pero el sistema luego converge;
- la imagen falla pero numero y nombre estan bien;
- la PWA lo muestra con pequeño atraso dentro de la ventana razonable.

## Hallazgo medio

- la fuente ya publico y a `T+12m` no aparece en current;
- un grouped triple trae A y B pero no C;
- un animalito de `:30` aparece corrido a `:00`;
- el admin lo tiene pero la PWA no lo refleja.

## Hallazgo critico

- el scraper no corre;
- la corrida falla tecnicamente;
- la fuente publico y a `T+20m` no existe persistencia;
- la API devuelve vacio mientras current si tiene datos;
- la PWA omite un grupo completo o dia completo.

## Formato sugerido de registro operativo

Usar una fila por provider y horario:

| Fecha | Tipo | Provider | Hora | Fuente visible | Scraper OK | Current/Archive OK | API OK | PWA OK | Hallazgo | Nota |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-08 | triple | Triple Caracas A | 16:30 | si | si | si | si | si | ninguno | - |

## Secuencia recomendada para una auditoria completa del dia

1. Iniciar a las `07:55` Venezuela y validar stack, admin y PWA.
2. Verificar primer bloque de providers de 08:00 y 08:30.
3. Seguir por ventanas:
   `09:00`, `10:00`, `12:00`, `12:45`, `13:00`, `13:15`, `14:00`, `16:00`, `16:30`, `16:45`, `19:00`, `19:05`, `19:10`, `19:30`, `20:00`, `22:00`.
4. Despues de medianoche, validar archivado de AYER.
5. A primera hora del dia siguiente, validar que AYER se vea correcto en archive, API y PWA.

## Cierre esperado de auditoria

La auditoria del dia se considera sana si:

- no hay providers faltantes fuera de ventana razonable;
- no hay desfases sistematicos de `:30`;
- no hay grouped cards incompletas;
- la PWA refleja HOY y AYER de forma consistente;
- admin, API y PWA coinciden;
- cualquier hallazgo tiene evidencia de fuente, logs y capa afectada.
