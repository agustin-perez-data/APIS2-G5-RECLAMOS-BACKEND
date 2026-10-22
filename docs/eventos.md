# Contratos de eventos — Módulo Reclamos (Grupo 5)

Este documento es **el contrato público** del módulo hacia el bus de CityPass+.
Si algo de acá cambia, se avisa en el canal de integración antes de mergear.

Implementación: `app/events/contracts.py` · `app/events/topics.py`

---

## 1. Convenciones

**Nombre del topic:** `<modulo>.<agregado>.<hecho>` — minúsculas, hecho en
pasado. Ej.: `reclamos.reclamo.estado-cambiado`.

**Key del mensaje:** siempre el `id` del reclamo. Garantiza que todos los
eventos del mismo reclamo caigan en la misma partición y conserven el orden.

**Formato:** JSON UTF-8. Headers de Kafka: `event_type`, `event_version`,
`source`, `content-type`, y `correlation_id` cuando existe.

**Envelope** (común a todo evento que entra o sale):

```json
{
  "event_id": "6f1c9a4e-3c2b-4a5d-9e11-2b7d5c8a1f30",
  "event_type": "reclamos.reclamo.creado",
  "event_version": "1.0",
  "occurred_at": "2026-08-13T14:22:31.512Z",
  "source": "reclamos",
  "correlation_id": "b23f...",
  "data": { }
}
```

También aceptamos el envelope al estilo **CloudEvents** (`id`, `type`, `time`,
`source`) al consumir: los alias están declarados en `EventEnvelope`.

**Versionado:**

- Agregar un campo **opcional** → misma `event_version`.
- Quitar o renombrar un campo, o cambiar su tipo → **subir la versión mayor** y
  publicar en paralelo hasta que todos los consumidores migren.
- Al consumir eventos ajenos usamos `extra="allow"`: que otro equipo agregue
  campos nunca rompe nuestro worker.

---

## 2. Eventos que publicamos

### `reclamos.reclamo.creado` — v1.0

Un vecino (o un evento de otro módulo) registró un reclamo.

```json
{
  "event_type": "reclamos.reclamo.creado",
  "data": {
    "reclamo_id": "6f1c9a4e-3c2b-4a5d-9e11-2b7d5c8a1f30",
    "ciudadano_id": "auth0|65f2c1...",
    "titulo": "Luminaria apagada en la plaza",
    "categoria": "ALUMBRADO",
    "prioridad": "MEDIA",
    "estado": "RECIBIDO",
    "barrio": "Centro",
    "direccion": "Rivadavia 800",
    "latitud": -34.6037,
    "longitud": -58.3816,
    "creado_at": "2026-08-13T14:22:31.500Z"
  }
}
```

### `reclamos.reclamo.clasificado` — v1.0

Solo cuando la categoría la decidió el modelo. Sirve para medir la calidad de la
clasificación y para que Analítica compare sugerencia vs. corrección manual.

```json
{
  "event_type": "reclamos.reclamo.clasificado",
  "data": {
    "reclamo_id": "6f1c9a4e-...",
    "categoria": "ALUMBRADO",
    "prioridad": "MEDIA",
    "confianza": 0.8134,
    "modelo": "naive-bayes-corpus-v1",
    "evidencia": ["luminaria", "poste", "apagada"]
  }
}
```

### `reclamos.reclamo.estado-cambiado` — v1.0

```json
{
  "event_type": "reclamos.reclamo.estado-cambiado",
  "data": {
    "reclamo_id": "6f1c9a4e-...",
    "ciudadano_id": "auth0|65f2c1...",
    "estado_anterior": "ASIGNADO",
    "estado_nuevo": "EN_PROCESO",
    "motivo": "cuadrilla en camino",
    "asignado_a": "cuadrilla-3",
    "cambiado_por": "operador-014",
    "cambiado_at": "2026-08-14T09:10:00.000Z"
  }
}
```

Consumidor típico: Notificaciones, para canales externos. La campana de la app
no depende de este evento: la notificación se guarda en la misma transacción que
el cambio ([ADR 0008](adr/0008-notificaciones-internas.md)).

### `reclamos.reclamo.resuelto` — v1.0

Se publica **además** del cambio de estado, porque es el hito que interesa a
Analítica y trae la métrica de gestión ya calculada.

```json
{
  "event_type": "reclamos.reclamo.resuelto",
  "data": {
    "reclamo_id": "6f1c9a4e-...",
    "ciudadano_id": "auth0|65f2c1...",
    "categoria": "ALUMBRADO",
    "resolucion": "Se reemplazo la luminaria",
    "horas_hasta_resolucion": 42.75,
    "resuelto_at": "2026-08-15T08:59:12.000Z"
  }
}
```

### `reclamos.reclamo.adherido` — v1.0

```json
{
  "event_type": "reclamos.reclamo.adherido",
  "data": {
    "reclamo_id": "6f1c9a4e-...",
    "ciudadano_id": "auth0|77aa...",
    "adhesiones_count": 10,
    "prioridad": "ALTA",
    "escalado": true
  }
}
```

`escalado: true` indica que esa adhesión hizo subir la prioridad al alcanzar el
umbral configurado (`ADHESIONES_PARA_ESCALAR`, default 10).

### `reclamos.reclamo.comentario-creado` — v1.0

Alguien comentó un reclamo: el dueño, otro vecino, un operador o el propio
sistema (cuando un incidente de Emergencias sube la prioridad).

```json
{
  "event_type": "reclamos.reclamo.comentario-creado",
  "data": {
    "comentario_id": "3a9d0c1e-5b7f-4e2a-8c6d-1f0e9b8a7c65",
    "reclamo_id": "6f1c9a4e-...",
    "ciudadano_id": "auth0|65f2c1...",
    "autor_id": "operador-014",
    "autor_nombre": "Operador Municipal",
    "es_oficial": true,
    "created_at": "2026-08-15T08:59:12.000Z"
  }
}
```

`ciudadano_id` es el dueño del reclamo, no quien comentó (ese es `autor_id`).
**No lleva el texto**: es contenido libre del vecino. Si un consumidor lo
necesita, lo pide por `comentario_id`.

Consumidor típico: Notificaciones, para canales externos (email, push). Las
notificaciones **dentro de la app** no dependen de este evento: se escriben en la
misma transacción que el comentario
([ADR 0008](adr/0008-notificaciones-internas.md)).

### `reclamos.dlq`

Cola propia de mensajes entrantes que no pudimos procesar. No es para consumo de
otros equipos: es para nuestro diagnóstico.

```json
{
  "event_type": "reclamos.dlq",
  "data": {
    "topic_original": "residuos.contenedor.desbordado",
    "error": "ValidationError(...)",
    "payload": { }
  }
}
```

---

## 3. Eventos que consumimos

Solo se declaran los campos de los que dependemos. Aceptamos variantes de
nombre (`contenedorId`, `id`, `lat`, `lng`…) vía `AliasChoices`.

### `residuos.contenedor.desbordado` → Grupo 4

**Reacción:** alta automática de un reclamo de categoría `RESIDUOS`, canal
`EVENTO`. Prioridad `ALTA` si `nivel_llenado >= 95`, si no `MEDIA`.

```json
{
  "event_id": "...",
  "event_type": "residuos.contenedor.desbordado",
  "source": "residuos",
  "data": {
    "contenedor_id": "CT-1234",
    "nivel_llenado": 98.5,
    "direccion": "San Martin 1500",
    "barrio": "Centro",
    "latitud": -34.60,
    "longitud": -58.38
  }
}
```

Campo obligatorio: `contenedor_id`. El resto es opcional.

**Idempotencia:** guardamos `event_id` en `reclamos.evento_origen_id` con
restricción UNIQUE. Si Kafka reentrega el mensaje, no se duplica el reclamo.

### `emergencias.incidente.creado` → Grupo 6

**Reacción:** los reclamos **abiertos** de ese barrio suben de prioridad y
reciben un comentario oficial explicando por qué. Los cerrados y rechazados no
se tocan.

```json
{
  "event_id": "...",
  "event_type": "emergencias.incidente.creado",
  "source": "emergencias",
  "data": {
    "incidente_id": "INC-77",
    "tipo": "incendio",
    "severidad": "alta",
    "barrio": "Centro",
    "latitud": -34.60,
    "longitud": -58.38
  }
}
```

Mapeo de severidad:

| `severidad` recibida | Prioridad mínima que aplicamos |
| --- | --- |
| `critica` / `critical` / `alta` / `high` | `CRITICA` |
| `media` / `medium` | `ALTA` |
| cualquier otra o ausente | `ALTA` |

Sin `barrio` el evento se ignora (no tenemos con qué acotar la zona).

---

## 4. Vocabulario del dominio

Definido en `app/domain/enums.py`. Cambiar un valor implica versionar el
contrato.

- **Estado:** `RECIBIDO` · `EN_REVISION` · `ASIGNADO` · `EN_PROCESO` ·
  `RESUELTO` · `RECHAZADO` · `CERRADO`
- **Prioridad:** `BAJA` · `MEDIA` · `ALTA` · `CRITICA`
- **Categoría:** `ALUMBRADO` · `BACHES` · `RESIDUOS` · `ARBOLADO` ·
  `AGUA_CLOACAS` · `TRANSITO` · `RUIDOS` · `ESPACIOS_PUBLICOS` · `SEGURIDAD` ·
  `OTROS`
- **Canal:** `APP` · `WEB` · `TELEFONO` · `PRESENCIAL` · `EVENTO`
- **Origen de clasificación:** `CIUDADANO` · `MODELO` · `OPERADOR`

---

## 5. Trazabilidad

Todo request HTTP acepta y devuelve el header `X-Correlation-Id` (se genera uno
si no viene). Ese id se propaga al `correlation_id` de los eventos y se bindea a
todos los logs estructurados, así una operación se puede seguir de punta a punta
aunque atraviese varios módulos.

---

## 6. Integración por el gateway de CityPass+ (CU-INT-01)

Entre módulos **no se habla por Kafka**: el Grupo 1 expone un gateway HTTP y es
por ahí que entran y salen los eventos del caso de uso integrado. Todo lo de las
secciones 2 y 3 sigue siendo nuestro contrato interno; esta sección es lo que ven
los otros equipos. El porqué está en el
[ADR 0009](adr/0009-integracion-por-el-gateway.md).

Diferencias con nuestro contrato interno, para que no sorprendan:

- Los nombres son los del catálogo del gateway: `com.citypass.reclamos.ReclamoCreado`.
- Los campos van en **camelCase**.
- Las fechas van en **milisegundos desde epoch** (`long`), no en ISO. Es lo que
  lee la capa silver de Analítica.
- Sólo salen **dos** de nuestros seis eventos. El resto no tiene consumidores
  fuera del módulo.

### Sobre del gateway

El dispatcher agrega la metadata; nosotros mandamos sólo los campos de negocio.

```json
{
  "metadata": {
    "eventId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "eventType": "com.citypass.reclamos.ReclamoCreado",
    "source": "reclamos",
    "receivedAt": 1792345678901
  },
  "data": { }
}
```

### `com.citypass.reclamos.ReclamoCreado`

Se publica al dar de alta un reclamo, venga de un vecino o de un evento de otro
módulo.

```json
{
  "reclamoId": "b1d4e8f2-6a30-4c99-8e71-0f5a2d6c3b84",
  "ciudadanoId": "U000042",
  "canal": "APP",
  "titulo": "Auto estacionado sobre la ciclovia",
  "descripcion": "Hay un auto arriba de la bicisenda y no se puede pasar",
  "categoria": "TRANSITO",
  "prioridad": "ALTA",
  "origenClasificacion": "CIUDADANO",
  "confianzaClasificacion": null,
  "direccion": "Av. Cordoba 4800",
  "barrio": "Palermo",
  "latitud": -34.5955,
  "longitud": -58.4281,
  "afectaCirculacion": true,
  "correlationId": "req-7c9e6679",
  "createdAt": 1792345678901
}
```

`afectaCirculacion` es **verdadero para `TRANSITO`, `BACHES` y `ARBOLADO`**. Es
el campo que usan Movilidad —para no recomendar estaciones cerca de un
incidente— y Espacios Públicos —para avisar a los inscriptos de un evento
cercano—. La misma regla se expone en nuestra API como `afecta_circulacion`, así
que el frontend no necesita reimplementarla.

El campo `objeto_afectado` que suma G5D-425 **no viaja por acá**: el tipo de
evento del gateway está validado contra un esquema Avro registrado en el catálogo
del Grupo 1, así que sumarlo hay que acordarlo con ellos. Por ahora vive sólo en
el contrato interno.

### `com.citypass.reclamos.ReclamoActualizado`

Se publica en cada transición de estado. **La resolución viaja acá**, con
`estadoNuevo = RESUELTO`: no hay un evento separado.

```json
{
  "reclamoId": "b1d4e8f2-6a30-4c99-8e71-0f5a2d6c3b84",
  "ciudadanoId": "U000042",
  "estadoAnterior": "EN_PROCESO",
  "estadoNuevo": "RESUELTO",
  "motivo": "Se retiro el vehiculo",
  "asignadoA": "cuadrilla-3",
  "cambiadoPor": "operador-1",
  "correlationId": "req-7c9e6679",
  "updatedAt": 1792349999000
}
```

### Lo que recibimos por webhook

`POST /api/v1/webhooks/citypass`. Se autentica con un secreto compartido, por
cabecera `X-Webhook-Token` (preferido) o por `?token=...`. Las entregas son
*at-least-once* y los tres handlers son idempotentes.

| Tipo del gateway | Qué hacemos |
| --- | --- |
| `com.citypass.residuos.AlertaGenerada` | Si `tipoAlerta = SATURACION`, abre un reclamo de RESIDUOS. Las de incendio se ignoran. |
| `com.citypass.emergencias.EmergenciaCreada` | Eleva la prioridad de los reclamos abiertos del barrio. No escala si la severidad es baja ni si `afectaCirculacion` es falso. |
| `com.citypass.espacios.EventoComunitarioPublicado` | Con cupo ≥ 100, eleva a `MEDIA` los reclamos abiertos de la zona. Los `CANCELLED` se ignoran. |

El barrio se compara **sin distinguir mayúsculas**, así que da igual si mandan
`Palermo`, `PALERMO` o `palermo`.

### Respuestas del webhook

| Código | Cuándo |
| --- | --- |
| `204` | Procesado, o de un tipo que no consumimos (se acepta y se ignora). |
| `400` | Falta `metadata.eventId`, `metadata.eventType` o `data`. |
| `401` | Secreto ausente o incorrecto. |
| `429` | Se superó el límite de entregas por minuto. |
| `500` | Falló el procesamiento. El dispatcher reintenta y después manda a su cola de muertos. |
