---
description: Adds a published or consumed event, with contract, test and docs
argument-hint: publicar|consumir <topic.name>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Add the requested event to the bus, together with its contract and docs.

**Event:** $ARGUMENTS

First decide whether it is **published** (we emit it) or **consumed** (it comes
from another team), because the rules differ.

## If we publish it

1. Topic constant in `app/events/topics.py`, added to `PUBLICADOS`. Naming:
   `<module>.<aggregate>.<fact>`, lowercase, fact in past tense.
2. Pydantic payload in `app/events/contracts.py`. Explicit, typed fields; use the
   enums from `app/domain/enums.py`, never loose strings.
3. Publish from `app/services/reclamo_service.py`, **after the commit** (see ADR
   0004) and with `key=str(reclamo.id)` — without that key, ordering per
   aggregate is lost.
4. Propagate `correlation_id=reclamo.correlation_id`.
5. Test in `tests/integration/test_reclamo_service.py` asserting with
   `publisher.eventos_de(topics.X)` that the use case emitted it with the right
   data.

## If we consume it

1. Topic constant, added to `CONSUMIDOS`.
2. Payload in `app/events/contracts.py` with **`extra="allow"`** and
   `AliasChoices` covering the name variants (`contenedorId`, `id`, `lat`,
   `lng`…). Declare **only** the fields we depend on: another team adding fields
   must never be able to take our worker down.
3. Handler in `app/events/handlers.py`, registered in `HANDLERS`.
4. **The handler never touches the database**: it goes through `ReclamoService`.
   That way a claim born from an event respects the same invariants as one filed
   from the app.
5. **Idempotency**: if the handler creates something, use
   `service.crear_desde_evento(..., evento_id=str(evento.event_id))`. Kafka
   redelivers messages; without this you duplicate claims.
6. Tests in `tests/integration/test_event_handlers.py`: the happy path, the
   **same event processed twice**, and a payload missing a required field.

## Always

- Document it in `docs/eventos.md` with a full JSON example, in **Spanish**. That
  file is the public contract towards the other teams: if it is not there, it
  does not exist.
- If the topic is new, add it to `redpanda-init` in `docker-compose.yml`.
- Versioning: adding an optional field keeps `event_version`; removing or
  renaming one forces a major bump and dual publishing.

When done, run `pytest` and show me the example JSON you documented.
