# ADR 0025 — El cierre automático corre dentro de la API

- **Estado:** Aceptada
- **Fecha:** 2026-11-16
- **Contexto:** G5D-7 · US-17 · Grupo 5

## Contexto

Un reclamo que queda siete días en `RESUELTO` sin respuesta del vecino se
cierra solo (US-17). La lógica vive en `ReclamoService.cerrar_resueltos_vencidos`
y necesita que algo la llame cada tanto.

En el diseño original la llamaba el proceso `worker`, que en producción no está
desplegado. Para cubrir ese hueco se agregó un workflow programado,
`cierre-automatico.yml`: una vez por día inicia sesión como administrador y
llama a un endpoint de mantenimiento.

El 16/11/2026, día de su primera corrida, el workflow no se ejecutó. No falló:
no arrancó. GitHub descarta la mayoría de los disparos programados de este
repositorio; el keepalive de Render está programado cada 10 minutos y corre, en
los hechos, cada 4 a 8 horas. Había cuatro reclamos resueltos desde septiembre
esperando ese cierre, y hubo que dispararlo a mano.

El workflow de alertas (ADR 0022) no lo detecta, porque reacciona a corridas
que fallan y acá no hay corrida.

## Opciones consideradas

**A. Seguir con el workflow programado.** ❌
No depende de nosotros que corra, y cuando no corre nadie se entera.

**B. Un disparador externo que llame al endpoint.** ❌
Resuelve la confiabilidad del reloj, pero suma un servicio de terceros y deja
una credencial de administrador guardada fuera del sistema.

**C. Una tarea programada en la base (`pg_cron`).** ❌
El cierre no es solo un `UPDATE`: escribe el historial, avisa al vecino y
publica el evento. Hacerlo desde SQL duplicaría esa lógica o saltearía la mitad.

**D. Un ciclo dentro del proceso de la API.** ✅
La API ya corre el consumidor del bus como tarea propia (ADR 0023). El cierre
se suma del mismo modo y no necesita ni reloj ajeno ni credenciales.

## Decisión

Con `CIERRE_AUTOMATICO_EN_API=true`, la API arranca un ciclo
(`app/services/cierre_periodico.py`) que cierra lo vencido un minuto después de
iniciar y después cada hora. Está apagado por defecto y encendido en
`render.yaml`.

- **La primera pasada es al arrancar, no una hora después.** El servicio se
  duerme cuando nadie lo usa: un proceso que rara vez vive una hora entera no
  cerraría nunca.
- **Una pasada que falla se registra y el ciclo sigue.**
- **Repetir no hace daño.** Una pasada que no encuentra nada vencido no hace
  nada, así que un reinicio o un redeploy no cierra nada dos veces.

El worker local usa el mismo ciclo. El endpoint de mantenimiento y el workflow
quedan como disparo manual y de respaldo: ya no son el mecanismo.

## Consecuencias

**Positivas**

- El cierre deja de depender de GitHub y de una cuenta de administrador
  guardada en los secretos del repositorio.
- Cada vez que alguien usa el sistema, el cierre se pone al día.

**Negativas**

- Si nadie usa el sistema durante días, no se cierra nada hasta que alguien
  entre. Un reclamo puede cerrarse más tarde que el día siete, nunca antes.
- Es una segunda tarea en el proceso de la API. Es una consulta por hora.
- Con más de una instancia, las pasadas se repetirían entre ellas. Hoy hay una.

**Queda por revisar**

- Los secretos `IDP_ADMIN_USUARIO` e `IDP_ADMIN_PASSWORD` solo los usa el
  workflow de respaldo. Si se retira el workflow, se pueden borrar.
- Render sigue durmiéndose: el keepalive depende del mismo reloj de GitHub.
