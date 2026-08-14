---
description: Agrega un evento publicado o consumido, con contrato, test y doc
argument-hint: publicar|consumir <nombre.del.topic>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Agregá el evento pedido al bus, con su contrato y su documentación.

**Evento:** $ARGUMENTS

Primero decidí si es **publicado** (lo emitimos nosotros) o **consumido** (viene
de otro grupo), porque las reglas son distintas.

## Si lo publicamos

1. Constante del topic en `app/events/topics.py` y sumala a `PUBLICADOS`.
   Naming: `<modulo>.<agregado>.<hecho>`, minúsculas, hecho en pasado.
2. Payload Pydantic en `app/events/contracts.py`. Campos explícitos y tipados;
   usá los enums de `app/domain/enums.py`, no strings sueltos.
3. Publicación desde `app/services/reclamo_service.py`, **después del commit**
   (ver ADR 0004) y con `key=str(reclamo.id)` — sin esa key se pierde el orden
   por agregado.
4. Propagá `correlation_id=reclamo.correlation_id`.
5. Test en `tests/integration/test_reclamo_service.py` afirmando con
   `publisher.eventos_de(topics.X)` que el caso de uso lo emitió con los datos
   correctos.

## Si lo consumimos

1. Constante del topic y sumala a `CONSUMIDOS`.
2. Payload en `app/events/contracts.py` con **`extra="allow"`** y `AliasChoices`
   para las variantes de nombre (`contenedorId`, `id`, `lat`, `lng`…). Declará
   **solo** los campos de los que dependemos: que el otro equipo agregue campos
   nunca puede tirar abajo nuestro worker.
3. Handler en `app/events/handlers.py` y registralo en `HANDLERS`.
4. **El handler no toca la base**: pasa por `ReclamoService`. Así un reclamo
   nacido de un evento respeta las mismas invariantes que uno creado desde la
   app.
5. **Idempotencia**: si el handler crea algo, usá
   `service.crear_desde_evento(..., evento_id=str(evento.event_id))`. Kafka
   reentrega mensajes; sin esto duplicás reclamos.
6. Tests en `tests/integration/test_event_handlers.py`: el caso feliz, el caso
   **del mismo evento procesado dos veces**, y el del payload al que le falta un
   campo obligatorio.

## Siempre

- Documentalo en `docs/eventos.md` con un ejemplo de JSON completo. Ese archivo
  es el contrato público hacia los otros grupos: si no está ahí, no existe.
- Si el topic es nuevo, agregalo al `redpanda-init` de `docker-compose.yml`.
- Versionado: agregar un campo opcional mantiene `event_version`; quitar o
  renombrar obliga a subir la versión mayor y publicar en paralelo.

Al terminar corré `pytest` y mostrame el JSON de ejemplo que documentaste.
