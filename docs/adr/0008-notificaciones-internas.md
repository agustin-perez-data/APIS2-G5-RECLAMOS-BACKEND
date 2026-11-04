# ADR 0008 — Notificaciones internas, escritas en la misma transacción

- **Estado:** Aceptada
- **Fecha:** 2026-09-24
- **Contexto:** Pedido del frontend (campana de notificaciones) · Grupo 5

## Contexto

El frontend tiene la campana y la pantalla `/notificaciones`, pero son
placeholders. Pidió que el backend avise al dueño de un reclamo cuando este
**cambia de estado** o **recibe un comentario** de otra persona. También pidió
que el backend guarde el estado de lectura: el punto rojo tiene que ser el mismo
en el celular y en la computadora, así que no puede vivir en `localStorage`.

Ya publicamos `reclamos.reclamo.estado-cambiado`. Pero el bus **no está
desplegado**: en Railway corre `KAFKA_ENABLED=false`, y el worker termina apenas
arranca. Además, los eventos salen después del commit (ADR 0004), así que si el
proceso muere entre el commit y el envío, el evento se pierde.

## Opciones consideradas

### A. Un consumidor de `estado-cambiado` que crea las notificaciones

- ✅ Es lo más "event-driven": el módulo reacciona a sus propios eventos.
- ❌ Hoy no funcionaría: sin bus y sin worker en el deploy, nunca se crearía
  una notificación.
- ❌ Hereda la ventana de pérdida entre el commit y la publicación.
- ❌ Obliga a deduplicar por `event_id`, porque Kafka puede reentregar.

### B. Outbox transaccional con un relay que publica y entrega

- ✅ Es la solución completa: nada se pierde y el bus recibe todo.
- ❌ Es la deuda del ADR 0004, con el mismo costo: una tabla de outbox, un
  proceso relay y su despliegue. Tampoco hoy hay dónde correrlo.

### C. Escribir la notificación en la misma transacción que el cambio *(elegida)*

`ReclamoService` crea la notificación junto con la fila de historial o el
comentario, antes del `commit()`. El evento se sigue publicando después, para
los demás módulos.

- ✅ Funciona con el deploy actual, sin bus.
- ✅ Se guarda el cambio y su notificación, o ninguno de los dos: no hay ventana
  de pérdida.
- ✅ No agrega ninguna llamada de red dentro de la transacción: es un `INSERT`
  más en la misma base.
- ⚠️ El servicio de reclamos conoce al de notificaciones. Lo aceptamos: es un
  solo módulo, y el acoplamiento es una línea por caso de uso.

## Decisión

Adoptamos la opción **C**. Es la "opción mínima" que proponía el propio pedido
del frontend.

**Quién recibe qué.** Siempre el dueño del reclamo (`reclamo.ciudadano_id`):

| Qué pasó | Tipo | Excepción |
| --- | --- | --- |
| Cambio de estado, incluido el cierre automático | `ESTADO` | El alta no notifica |
| Comentario de un operador, de otro vecino o del sistema | `COMENTARIO` | — |

Nadie recibe notificaciones de algo que hizo él mismo. Tampoco se notifica a
`sistema`, el dueño de los reclamos que abren los eventos de otros módulos.

**Idempotencia.** Cada notificación apunta a la fila que la originó
(`referencia_id`: el historial o el comentario). La clave única
`(destinatario_id, tipo, referencia_id)` impide duplicarla. Como
`referencia_id` nunca es nulo, la clave funciona sin trucos para los `NULL`.
Antes de insertar, el servicio verifica si ya existe, para que un reintento no
haga fallar la transacción entera.

**Texto.** El título y el mensaje se arman en el backend, con las etiquetas de
los estados ("En revisión", "Tu reclamo fue resuelto"). El mensaje incluye el
motivo y, al resolver, la resolución. En los comentarios va un resumen de hasta
140 caracteres en una línea. Los comentarios oficiales van firmados como "El
municipio" y no con el nombre del operador, que es un dato interno.

**Lectura.** Siempre por el usuario del token; ningún endpoint recibe un id de
usuario. Marcar como leída es idempotente, y conserva la fecha de la primera
lectura. La notificación de otro usuario responde `404`, igual que una que no
existe, para no revelar que existe.

**Canal.** Polling REST: `GET /notificaciones/conteo` es liviano, pensado para
consultarlo cada 15 a 30 segundos. SSE o WebSocket se pueden agregar después
como un canal más, sin reemplazar esta API.

**Evento nuevo.** Se agrega `reclamos.reclamo.comentario-creado`, v1.0, para
los otros módulos. No lleva el texto del comentario: es contenido libre del
vecino, y quien lo necesite lo pide por id.

## Consecuencias

**Positivas.** El vecino se entera de lo que pasa con su reclamo sin entrar a
buscarlo. El contador y la lectura son iguales en todos sus dispositivos. Y
funciona hoy, con el deploy como está.

**Negativas.**
- Solo notificamos dentro de la app. Email, push, SMS y WhatsApp quedan afuera.
- Las notificaciones no se borran nunca. Con el volumen del cuatrimestre no
  importa; más adelante haría falta una purga de las leídas más viejas.
- Los vecinos que se sumaron a un reclamo no reciben avisos: solo el dueño.

**A revisar.**
1. Cuando el bus esté desplegado, los canales externos (email, push) pueden
   colgarse de `estado-cambiado` y `comentario-creado`, con su propia tabla de
   entregas y preferencias por usuario.
2. Avisarles también a los adheridos, que hoy no se enteran de nada.
3. Si el polling pesa, un endpoint SSE para la campana.
