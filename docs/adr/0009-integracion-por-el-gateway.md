# ADR 0009 — Integración con los otros módulos por el gateway de CityPass+

- **Estado:** Aceptada (con deuda técnica registrada)
- **Fecha:** 2026-10-22
- **Contexto:** Caso de uso integrado CU-INT-01 · Grupo 5

## Contexto

El caso de uso CU-INT-01, "Ruta urbana inteligente con incidentes en tiempo
real", conecta seis módulos: un bache o un árbol caído cambian por dónde conviene
llegar a un evento cultural. Reclamos aporta los incidentes que cortan la
circulación y, a cambio, reordena su bandeja cuando otro módulo avisa de algo que
pasa en la zona.

El problema es que ese tráfico no va por nuestro Kafka. El Grupo 1 expone un
**gateway HTTP**: los eventos se publican por POST contra su API —autenticando
con un token de servicio `client_credentials` del Grupo 2— y se reciben por
**webhook**. Los tipos de evento viven en un catálogo propio
(`event-types.json`), con nombres y campos que no son los nuestros: el gateway
usa `com.citypass.reclamos.ReclamoCreado`, camelCase y fechas en milisegundos
desde epoch, mientras que nuestro contrato interno usa
`reclamos.reclamo.creado`, snake_case y fechas ISO.

Ya teníamos un contrato de eventos propio (ADR 0003), un puerto `EventPublisher`
(ADR 0001) y un worker de Kafka funcionando. La pregunta es cómo entra el gateway
sin tirar abajo nada de eso.

## Opciones consideradas

### A. Renombrar nuestros eventos a los del gateway

Adoptar `com.citypass.reclamos.ReclamoCreado` como nombre interno y camelCase en
los payloads.

- ❌ Rompe el contrato que ya publicamos en `docs/eventos.md` y que otros
  equipos leyeron.
- ❌ Nos deja atados al catálogo del Grupo 1: cada cambio suyo es un cambio en
  nuestro dominio.
- ❌ Perdemos la convención `<módulo>.<agregado>.<hecho>` acordada con el
  Grupo 1 para el bus.

### B. Publicar en los dos lados desde el servicio

Que `ReclamoService` llame a Kafka y al gateway.

- ❌ El servicio pasa a conocer dos tecnologías de transporte. Es exactamente lo
  que el puerto `EventPublisher` existe para evitar (ADR 0001).
- ❌ Duplica el manejo de errores y reintentos en cada caso de uso.

### C. Un publisher que traduce en el borde *(elegida)*

`GatewayEventPublisher` implementa el mismo puerto `EventPublisher` que el
publisher de Kafka. El servicio sigue publicando `reclamos.reclamo.creado` sin
enterarse de nada; la traducción al nombre y la forma del gateway ocurre en el
borde. La recepción es simétrica: `POST /api/v1/webhooks/citypass` traduce el
sobre del gateway al nuestro y ejecuta **los mismos `HANDLERS`** que el worker de
Kafka, así un evento se comporta igual venga por donde venga.

- ✅ El dominio y el contrato interno quedan intactos.
- ✅ Un solo lugar que conoce el formato ajeno, fácil de cambiar si el Grupo 1
  cambia el suyo.
- ✅ Los tests siguen corriendo sin broker ni red.
- ❌ Hay que mantener la tabla de traducción cuando aparezca un evento nuevo.

## Decisión

Adoptamos **C**. Con `GATEWAY_ENABLED=true` el servicio publica por el gateway;
con `false` sigue usando Kafka, que es lo que se usa en desarrollo local.

### Qué sale y qué no

Al gateway salen **sólo dos** eventos:

| Interno | Gateway |
| --- | --- |
| `reclamos.reclamo.creado` | `com.citypass.reclamos.ReclamoCreado` |
| `reclamos.reclamo.estado-cambiado` | `com.citypass.reclamos.ReclamoActualizado` |

El resto (`clasificado`, `resuelto`, `adherido`, `comentario-creado`) no tiene
consumidores fuera del módulo, así que no se publica: un contrato que nadie lee
es superficie que hay que mantener sin beneficio. La resolución viaja dentro de
`ReclamoActualizado` con `estadoNuevo = RESUELTO`, que es lo que Analítica usa
para medir el tiempo de gestión.

`objeto_afectado` (G5D-425) **no se envía** por el gateway: su tipo de evento
está validado contra un esquema Avro registrado en el catálogo del Grupo 1, así
que agregarlo requiere acordarlo con ellos. Queda en el contrato interno hasta
que se decida.

### La regla de `afectaCirculacion`

`ReclamoCreado` viaja con `afectaCirculacion`, verdadero para `TRANSITO`,
`BACHES` y `ARBOLADO` (`CATEGORIAS_QUE_AFECTAN_CIRCULACION` en
`app/domain/enums.py`). Es lo que Movilidad usa para no recomendar estaciones
cerca de un incidente y lo que Espacios Públicos usa para avisar a los inscriptos
de un evento cercano. La misma regla se expone en la API como campo calculado
`afecta_circulacion`, para que el frontend no la reimplemente y las dos
definiciones no se desincronicen.

### La regla del cupo

Un evento cultural con cupo de **100 personas o más** eleva a `MEDIA` los
reclamos abiertos de esa zona (`CUPO_MINIMO_EVENTO_MASIVO` en `handlers.py`). La
idea es que un bache en la zona de una feria de 300 personas se atienda antes de
que llegue la gente. Los eventos `CANCELLED` se ignoran: no concentran a nadie.

### El webhook sin JWT

`POST /api/v1/webhooks/citypass` suma una excepción a la regla del `CLAUDE.md`
de que ningún endpoint va sin `UsuarioDep`, `StaffDep` o `AdminDep`, que hasta
ahora sólo eximía a `/health` y al login de desarrollo.
El dispatcher del gateway no firma las entregas ni emite un JWT, así que no hay
identidad que validar. Se protege con tres capas:

1. **Un secreto compartido**, comparado con `hmac.compare_digest` (tiempo
   constante, no filtra información por el tiempo de respuesta).
2. **Preferencia por la cabecera `X-Webhook-Token`.** El gateway también puede
   mandarlo como `?token=...`, y en ese caso uvicorn loguearía la URL completa:
   el secreto quedaría en texto plano en los logs de la plataforma. El filtro
   `OcultarTokenEnUrl` de `app/core/logging.py` lo enmascara, pero la cabecera es
   la opción correcta y hay que pedirla al suscribir.
3. **Rate limit propio** (`RATE_LIMIT_WEBHOOK`, 120/minuto por IP). Deliberadamente
   holgado: una entrega legítima descartada termina en la cola de muertos del
   gateway, así que el límite está para cortar una inundación de un cliente no
   autenticado, no para regular el tráfico real.

Las entregas son *at-least-once* y los tres handlers son idempotentes, así que
una reentrega no duplica nada.

## Deuda registrada: sin outbox

Si el gateway está caído más allá de los tres reintentos (~1,5 s), el evento se
pierde y queda `evento.no_publicado.gateway` en el log. Es **la misma deuda del
ADR 0004** y por las mismas razones: el reclamo ya está commiteado y el vecino no
puede recibir un 500 por un reclamo que sí se guardó. El criterio de disparo para
implementar el outbox también es el mismo.

## Consecuencias

**Positivas.** El dominio no se enteró del cambio de transporte. El worker de
Kafka y Redpanda dejan de ser necesarios en el despliegue, aunque se mantienen
para desarrollo local. Un evento que llega por webhook ejecuta el mismo código
que uno que llega por Kafka, así que no hay dos caminos que mantener.

**Negativas.** Hay una tabla de traducción más que mantener. Dependemos de que el
Grupo 1 tenga registrados nuestros tipos de evento en su catálogo: si no están,
el gateway rechaza la publicación.

**Qué queda por revisar.** Si Movilidad necesita `objeto_afectado` para filtrar,
hay que pedirle al Grupo 1 que extienda el esquema Avro de `ReclamoCreado`.
