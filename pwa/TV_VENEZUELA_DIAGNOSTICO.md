# Checklist de diagnóstico remoto (PWA en Smart TV Venezuela)

## 1) Qué tan seguro es el fix antes de pasarlo a `main`

No se puede **garantizar 100%** sin pruebas en dispositivos reales, pero sí se puede subir mucho la confianza con este criterio:

- La causa reportada (triples aparece en primer ciclo y luego no vuelve) coincide con una transición incompleta de estado entre `animalitos -> triples`.
- El fix actual fuerza el retorno a `triples` al finalizar grupos/días de animalitos.
- Se mantiene compatibilidad de carga clásica (`<script src="./app.js"></script>`) para WebView viejos.
- Se validó sintaxis JS en runtime de Node.

## 2) Plan de verificación desde Chile (sin TV física en Venezuela)

### 2.1 Matriz mínima

- Android WebView 69+ (Android 9)
- Android WebView 80+
- Android WebView 100+
- Chrome Desktop (baseline)

### 2.2 Escenarios que deben pasar

1. Ciclo completo:
   - Triples Hoy (todos los grupos)
   - Triples Ayer (todos los grupos)
   - Animalitos Hoy/Ayer (todos los grupos)
   - **Debe volver a Triples Hoy** automáticamente.

2. Con pocos providers (1 grupo) y con muchos providers (>= 2 grupos).

3. Con datos vacíos en un día (ej. animalitos ayer vacío).

4. Cambio de datos durante ciclo (simular actualización API cada 60s).

### 2.3 Señales de éxito

- Nunca se queda permanente en `animalitos`.
- El título alterna correctamente entre:
  - `RESULTADOS HOY (TRIPLES)`
  - `RESULTADOS AYER (TRIPLES)`
  - `RESULTADOS HOY (ANIMALITOS)`
  - `RESULTADOS AYER (ANIMALITOS)`
- Se observa repetición continua de ciclos (>3 ciclos).

---

## 3) Checklist operativo en campo (Venezuela)

## A. Headers de caché (HTML/JS/SW)

Verificar en respuesta HTTP:

- `index.html`: `Cache-Control: no-cache, must-revalidate` (o max-age bajo + revalidación)
- `app.js`, `deviceManager.js`, `styles.css`: idealmente versionados por hash o `Cache-Control: no-cache`.
- `service-worker.js`: **no-cache** para permitir actualización inmediata del SW.

Si hay CDN (Cloudflare/Nginx), validar que no fuerce caché largo en `service-worker.js`.

## B. Versión de WebView / motor en TV

Registrar:

- Marca/modelo TV
- Android version
- Android System WebView version (o Chrome version si WebView provider)

Objetivo: confirmar que casos fallidos estén en una versión concreta.

## C. Estrategia de actualización Service Worker

En cada despliegue:

1. Cambiar `CACHE_NAME` en `service-worker.js`.
2. Confirmar que `install` ejecute `skipWaiting()`.
3. Confirmar que `activate` ejecute `clients.claim()`.
4. Validar que limpia cachés viejos.

Resultado esperado: SW nuevo toma control sin esperar cierre manual de app.

## D. Logs mínimos a solicitar en sitio

Pedir evidencia (foto/video o log remoto) de:

1. Hora local TV.
2. Código de activación visible en pantalla.
3. Secuencia de títulos durante al menos 2 ciclos completos.
4. Si se congela, indicar el último título visible.
5. Si se puede inspeccionar:
   - errores en consola
   - estado de SW (activated/waiting)
   - requests a `/api/results/` y `/api/animalitos/` con status 200.

---

## 4) Playbook de incidente rápido (15 min)

1. Hard reload / cerrar y abrir PWA.
2. Borrar storage del sitio (cache + SW + localStorage) y reabrir.
3. Verificar `activation_code` presente.
4. Revisar requests de API con `date=today` y `date=yesterday`.
5. Confirmar alternancia de título por 1 ciclo completo.

Si falla aún:
- recopilar versión WebView + modelo TV
- exportar headers reales de CDN/origen
- reportar timestamp exacto del congelamiento.

---

## 5) Criterio de salida para publicar en main

Publicar cuando se cumplan:

- [ ] 3 ciclos consecutivos correctos en 2 WebViews distintos.
- [ ] Validación de headers de caché de `index.html` y `service-worker.js`.
- [ ] Prueba de actualización de SW tras redeploy (cambio de `CACHE_NAME`).
- [ ] Confirmación en al menos 1 dispositivo objetivo en Venezuela.

