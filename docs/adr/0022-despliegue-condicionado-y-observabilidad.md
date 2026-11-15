# ADR 0022 — El deploy espera al CI, vuelve atrás solo y avisa cuando falla

- **Estado:** Aceptada
- **Fecha:** 2026-11-15
- **Contexto:** G5D-7 · DevOps · Grupo 5

## Contexto

El pipeline tenía tres huecos que no se veían mientras todo andaba bien:

1. **El deploy no esperaba al CI.** `cd-backend.yml` corría en cada push a
   `main`, en paralelo con `ci-backend.yml`. Un commit con tests rotos, una
   credencial filtrada o una imagen vulnerable se desplegaba igual: los
   chequeos solo frenaban un pull request, y a `main` también se llega con un
   push directo.
2. **Un deploy que arrancaba pero no respondía quedaba en producción.** El
   smoke test ponía el pipeline en rojo y nada más.
3. **Nadie se enteraba de una falla.** El deploy, el cierre automático y los
   keepalive fallaban en la pestaña Actions, que nadie mira. Y del servicio en
   marcha solo había logs: ninguna cifra de cuántos pedidos fallan o de si los
   eventos llegan al bus.

## Opciones consideradas

**Para el deploy**

- **A. Un solo workflow, con el deploy como último job del CI.** ❌ Mezcla en un
  archivo dos cosas con permisos y secretos distintos, y hace correr el job de
  deploy (aunque se saltee) en cada rama y en cada PR.
- **B. Exigir los chequeos con la protección de rama.** ❌ como única medida:
  no alcanza a los administradores, que son quienes hacen push directo.
- **C. Disparar el CD con `workflow_run`, cuando el CI de `main` termina, y
  seguir solo si terminó bien.** ✅ El deploy depende del resultado del CI sin
  importar cómo llegó el commit.

**Para avisar**

- **A. Un servicio externo de monitoreo o de errores.** ❌ Otra cuenta, otro
  secreto y otro plan gratuito que vigilar.
- **B. Notificaciones por mail de GitHub Actions.** ❌ Le llegan solo a quien
  disparó la corrida; una corrida programada no le avisa a nadie útil.
- **C. Un workflow que abre un issue cuando otro falla y lo cierra cuando
  vuelve a pasar.** ✅ Sin nada nuevo que administrar, y le llega a quien siga
  el repositorio.

**Para las métricas**

- **A. Contadores propios, a mano.** ❌ El formato de exposición y los
  histogramas son fáciles de escribir mal.
- **B. `prometheus-client`, en memoria, expuesto en `/metrics`.** ✅ Es el
  cliente oficial, Python puro, y el formato lo lee cualquier herramienta.

## Decisión

**Deploy.** `cd-backend.yml` se dispara cuando termina `CI Backend` sobre
`main` y solo sigue si esa corrida fue de un push y terminó en verde. Despliega
el commit exacto que pasó el CI, no lo último de la rama. Si el smoke test
falla, vuelve al deploy que estaba en vivo antes de empezar, con el endpoint de
rollback de Render. Un deploy que ni siquiera arranca no necesita rollback:
Render deja en vivo el anterior. Queda un disparo manual para redesplegar
`main` sin esperar un CI.

**Alertas.** `alertas.yml` escucha al CD, al cierre automático, a la
verificación de Render y a los dos keepalive. Ante una falla abre un issue con
la etiqueta `alerta`, uno por workflow; mientras siga fallando comenta a lo
sumo cada seis horas; cuando el workflow vuelve a pasar, lo cierra. La caída
del servicio queda cubierta por el keepalive, que consulta `/health` cada diez
minutos.

**Métricas.** `GET /metrics`, solo para administradores, expone en formato
Prometheus:

| Métrica | Qué cuenta |
| --- | --- |
| `reclamos_http_requests_total` | Pedidos por método, plantilla de ruta y status |
| `reclamos_http_request_duration_seconds` | Duración de los pedidos, por método y plantilla de ruta |
| `reclamos_eventos_publicados_total` | Eventos enviados al gateway, por tipo y resultado (`publicado`, `rechazado`, `fallido`) |
| `reclamos_eventos_recibidos_total` | Eventos recibidos por webhook, por tópico y resultado (`procesado`, `ignorado`, `error`) |
| `reclamos_build_info` | Versión y entorno |

Las etiquetas son conjuntos cerrados: la plantilla de la ruta y nunca la URL,
el tipo de evento y nunca un id.

## Consecuencias

**Positivas**

- Un commit que no pasa el CI no llega a producción, haya entrado por pull
  request o por push directo.
- Una versión que arranca pero no responde se revierte sola.
- Una falla del pipeline o una caída del servicio abre un issue.
- Un evento que no salió al bus deja de ser solo una línea en los logs.

**Negativas**

- El deploy tarda lo que tarda el CI, unos minutos más que antes.
- El rollback no deshace migraciones: tienen que seguir siendo compatibles con
  la versión anterior, como hasta ahora.
- Free solo permite volver a los dos deploys anteriores.
- Las métricas viven en memoria: se reinician en cada deploy y cada vez que el
  plan gratuito duerme el servicio. Nadie las recolecta todavía; un scraper
  necesitaría una credencial propia.
- El rollback no se pudo ejercitar sin romper producción a propósito.

**Queda por revisar**

- Recolectar las métricas fuera del proceso para tener historia.
- Una alerta por tasa de errores, hoy imposible sin esa historia.
