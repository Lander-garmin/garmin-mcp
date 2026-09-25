# Garmin MCP — conector para claude.ai

Servidor desplegado en **Render.com** (plan Free, región Frankfurt), imagen Docker construida
desde https://github.com/Tyler-Irving/garmin-mcp (v0.5.0). Modo **solo lectura**
(`GARMIN_WRITE_ENABLED` no está definido).

## Dirección del conector (MCP endpoint)

```
https://svc-sync-eu-2609.onrender.com/mcp
```

## Añadirlo en claude.ai

1. Abre claude.ai → **Settings** → **Connectors**.
2. Pulsa **Add custom connector**.
3. Pega la dirección de arriba y confirma.
4. Se abre la página de login del servidor: introduce la **MCP_AUTH_PASSWORD**
   (está en `.deploy.env`, línea `MCP_AUTH_PASSWORD`).
5. El conector pasa a verde. Prueba: "¿cómo he dormido esta noche?".

Los conectores personalizados están disponibles en los planes Pro, Max, Team y Enterprise.

## Dónde están los secretos

Todos en `.deploy.env` (y su copia en formato Render `render.env`), en la raíz de este repo.
Ambos ficheros están en `.gitignore`. No se ha subido ningún secreto a git ni a Render como código:
en Render viven como variables de entorno del servicio.

## Operación en Render

Panel: https://dashboard.render.com → servicio **svc-sync-eu-2609**.

- **Redesplegar** (por ejemplo tras una versión nueva del repo): botón **Manual Deploy → Deploy latest commit**.
- **Ver logs**: pestaña **Logs** del servicio. Eventos útiles: `oauth.login.success`,
  `garmin.login.resumed`, `garmin.auth.expired`.
- **Revocar el acceso de todos los clientes**: pestaña **Environment** → editar `JWT_SECRET`
  con un valor nuevo (`openssl rand -base64 48`) → guardar. Render reinicia el servicio y los
  tokens antiguos dejan de valer al instante. Actualiza también `.deploy.env`.
- **Cambiar la contraseña del conector**: igual, editando `MCP_AUTH_PASSWORD`.
- **Cambiar la contraseña de Garmin**: edita `GARMIN_PASSWORD` en Environment y en `.deploy.env`.

## Comprobaciones rápidas

```bash
curl -s https://svc-sync-eu-2609.onrender.com/health
# → {"status":"ok","auth_enabled":true}

curl -s https://svc-sync-eu-2609.onrender.com/.well-known/oauth-authorization-server
# → "issuer": "https://svc-sync-eu-2609.onrender.com/"
```

## Limitaciones del plan Free de Render

- Se **duerme tras 15 minutos** sin peticiones. La primera petición tras dormirse tarda
  ~1 minuto; claude.ai puede mostrar un error la primera vez y funcionar al reintentar.
- Para mantenerlo despierto gratis: crear un monitor en https://uptimerobot.com (gratis,
  sin tarjeta) que haga GET a `/health` cada 10 minutos. 750 h/mes de Free cubren 24/7.
- 512 MB RAM, 0,1 CPU: suficiente para un único usuario.

## Coste

0 €/mes mientras se use un solo servicio Free en Render.

## Versión ampliada (desplegada el 24/09/2026)

El servicio de Render lee ahora de **https://github.com/Lander-garmin/garmin-mcp** (rama `main`),
que añade `src/garmin_mcp/extra_tools.py`: 35 herramientas de solo lectura más (pulso intradía con
la última lectura del reloj, SpO2, hidratación, pisos, pesajes, tensión, dispositivos y última
sincronización, objetivos, medallas, umbral de lactato, FTP, calendario de entrenos, series
temporales de actividades, totales entre fechas...). En total el servidor expone 63 herramientas;
las 8 de escritura están desactivadas.

### Publicar cambios nuevos

El servicio lee el repositorio como "Public Git Repository" (sin cuenta de GitHub conectada), así que Render **no** redespliega solo. Tras subir cambios a `main`, pulsar en Render **Manual Deploy → Deploy latest commit**:

```bash
cd C:\Users\dis6.AD\GARMIN\garmin-mcp
git add -A && git commit -m "descripcion del cambio"
git push github extended-tools:main
```

Comprobar tras el despliegue: `curl -s https://svc-sync-eu-2609.onrender.com/health`.

## Descanso con cuenta atrás en pesas (25/09/2026)

`preview_strength_workout` / `create_strength_workout` aceptan `rest_seconds` por bloque. Con valor,
el descanso del reloj es una cuenta atrás que vibra al acabar; sin él, el descanso termina con Lap.
La tarea "Plan de la semana" usa 120 s en básicos y 75 s en accesorios. Requiere un reloj con perfil
de Fuerza (el Forerunner 55 no lo tiene; el 165 sí).
