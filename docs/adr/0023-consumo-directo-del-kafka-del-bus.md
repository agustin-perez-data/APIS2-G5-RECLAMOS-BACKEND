# ADR 0023 — Los eventos de otros módulos se leen del Kafka del bus

- **Estado:** Aceptada
- **Fecha:** 2026-11-15
- **Contexto:** Caso de uso de alerta climática (ADR 0014) · Grupo 5
- **Relación con otros ADR:** complementa al [0009](0009-integracion-por-el-gateway.md).
  La publicación sigue saliendo por el gateway HTTP y el webhook sigue en pie;
  lo que cambia es por dónde entran los eventos listados acá.

## Contexto

El ADR 0009 dejó la entrada de eventos en un webhook: el gateway del Grupo 1
llama a `POST /api/v1/webhooks/citypass` por cada evento suscripto. Dos cosas
cambiaron desde entonces.

**El webhook pierde eventos, y no por nosotros.** El gateway convierte cada
evento a JSON antes de entregarlo, y esa conversión falla con cualquier evento
cuyo esquema Avro tenga un `enum`. `CriticidadClimaticaConfirmada` tiene dos
(`nivelCriticidad` y `fenomeno`): todas sus entregas terminaron en la cola de
muertos del gateway sin un solo intento contra nuestro servicio. En el bus hay
alertas reales de Espacios Públicos del 6, el 13 y el 14 de noviembre que nunca
recibimos. `CriticidadClimaticaFinalizada`, que no tiene enums, sí llegaba: el
módulo recibía el cierre de alertas que no conocía.

**El Grupo 1 pide leer de Kafka.** Entregó broker, registro de esquemas y
credenciales, y dejó el webhook como alternativa de emergencia. Cada evento se
escribe en un tópico con el nombre de su tipo, en el formato de Confluent (un
byte en cero, el id del esquema en cuatro bytes y el registro en Avro), con el
mismo sobre `metadata` + `data` que entrega el webhook.

Lo verificamos contra el bus de test el 15/11/2026 antes de decidir: los 19
eventos del tópico se leen y decodifican, incluidos los que el webhook perdió.

## Opciones consideradas

**A. Esperar a que el Grupo 1 despliegue el arreglo del webhook.** ❌
No cuesta nada, pero el arreglo está mergeado y sin desplegar, sin fecha, y el
webhook pasó a ser el camino secundario del bus. Seguiríamos dependiendo de una
conversión que ya falló una vez sin que nadie de nuestro lado pudiera verlo.

**B. `confluent-kafka` con su deserializador de Avro.** ❌
Es la librería que usa la documentación del bus, pero es síncrona: habría que
correrla en un hilo aparte, en un repositorio que es asíncrono de punta a punta.

**C. `aiokafka`, que ya es dependencia, más `fastavro` para decodificar.** ✅
`aiokafka` soporta `SASL_SSL` con `OAUTHBEARER`. El formato de Confluent son
cinco bytes de cabecera: leerlos a mano y pedir el esquema al registro son unas
pocas líneas, y evitan una segunda librería de Kafka.

Sobre dónde corre:

**D. Un proceso `worker` aparte en Render.** ❌
Es el diseño original (`app/worker.py`) y el correcto a otra escala, pero en
Render es un segundo servicio y es pago.

**E. Una tarea dentro del proceso de la API.** ✅
El consumidor arranca con la aplicación. Un tópico con un puñado de eventos por
semana no compite con el tráfico HTTP.

## Decisión

`app/events/bus.py` lee los tópicos de `BUS_KAFKA_TOPICS` y ejecuta **los mismos
`HANDLERS`** que el webhook, pasando por la misma traducción
(`app/events/entrada.py`). Un evento se comporta igual venga por donde venga.

Está **apagado por defecto** (`BUS_KAFKA_ENABLED=false`) y lee solo los dos
eventos de clima, que son los que el webhook pierde. El resto sigue entrando por
webhook hasta que se decida moverlo.

| Decisión | Por qué |
| --- | --- |
| El offset se commitea después de procesar, siempre | *At-least-once*. Un mensaje sin commitear se releería para siempre |
| Un mensaje que no decodifica o rompe el contrato se registra, se cuenta y se saltea | No hay reintento que lo arregle, y no puede frenar el tópico |
| Un fallo del handler se reintenta tres veces y después se saltea | Lo pasajero (la base) se recupera solo; lo demás no puede frenar el tópico |
| Si el registro de esquemas no responde, se corta la conexión sin commitear | El mensaje se vuelve a leer cuando el registro vuelva |
| Cualquier falla del broker termina en una espera y un reintento | El bus caído no puede tirar la API |
| Un grupo sin posición arranca desde el final (`BUS_KAFKA_DESDE=latest`) | El historial tiene eventos de prueba; aplicarlos sobre reclamos reales tiene que ser una decisión |
| La posición del grupo se fija en la primera conexión | Sin eso, un grupo que todavía no procesó nada volvería a arrancar desde el final en cada reinicio y perdería lo que llegó mientras el servicio dormía |
| No hay cola de muertos propia | En producción el publisher es el gateway, que no transporta la nuestra. Lo salteado queda en el log y en `reclamos_eventos_bus_total` |

### Una alerta vencida no hace nada

Leer de un tópico trae algo que el webhook no traía: eventos viejos. Una alerta
puede leerse horas después de emitida, o repetirse entera si alguna vez se lee
el tópico desde el principio. Hasta acá `vigencia_hasta` se guardaba y no se
usaba.

Desde este ADR, una alerta cuya vigencia terminó **se guarda pero no marca
reclamos, no avisa a nadie y no publica `CriticidadClimaticaAplicada`**. Tampoco
cubre a los reclamos nuevos, aunque su `Finalizada` no haya llegado nunca. La
regla vive en un solo lugar: `esta_vencida` en `app/services/clima_service.py`.

### Convivencia con el webhook

Mientras el Grupo 1 no dé de baja la suscripción, un mismo evento puede llegar
por los dos caminos. Trae el mismo `eventId`, y la tabla `eventos_procesados`
(ADR 0014) descarta el segundo.

## Consecuencias

**Positivas**

- Las alertas climáticas llegan. El caso de uso funciona de punta a punta.
- Un evento que llega con el servicio dormido no se pierde: se lee al despertar.
  Con el webhook, tres reintentos fallidos lo mandaban a la cola de muertos.
- El contador `reclamos_eventos_bus_total` muestra en `/metrics` qué se leyó y
  qué fue de cada evento, sin entrar a los logs de Render.
- El worker local dejó de caerse con un mensaje ilegible: decodificaba fuera del
  manejo por mensaje, y un solo mensaje roto lo frenaba en cada reinicio.

**Negativas**

- Una dependencia nueva, `fastavro`.
- El consumidor comparte proceso con la API, contra lo que dice
  `app/events/consumer.py` para el worker local: un evento lento compite con el
  tráfico HTTP. A este volumen no se nota.
- Con el servicio dormido los eventos llegan tarde, lo que tarde en despertar.
- Si el proceso muere entre que el handler termina y el commit del offset, el
  evento se procesa dos veces. Los handlers son idempotentes.
- Un evento salteado tras tres fallos no se recupera solo: hay que releer el
  tópico a mano.

**Queda por revisar**

- Mover a Kafka el resto de los eventos entrantes y pedir la baja del webhook.
- Si el volumen crece, sacar el consumidor a un proceso propio.
- `Finalizada` y `Confirmada` viajan en tópicos distintos, sin orden entre sí.
  Un cierre leído antes que su confirmación se ignora, como ya pasaba.
