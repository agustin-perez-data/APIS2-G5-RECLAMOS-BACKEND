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

**Identidad:** hay **dos orígenes distintos** y conviene no confundirlos, porque
sólo uno se puede cruzar contra el directorio del Grupo 2.

| Campo | Qué es |
| --- | --- |
| `ciudadano_id` (`ciudadanoId` en el gateway) | Un **UUID que emite Reclamos**. El IdP del Grupo 2 autentica sólo personal municipal, así que un vecino no existe en su directorio: **este id no se resuelve contra ellos**. |
| `cambiado_por`, `reclasificado_por`, `asignado_a` | El claim `sub` del token del Grupo 2 (ej. `U000042`). Estos sí se cruzan contra su directorio. |
| `usuario_id`, `autor_id`, `destinatario_id` | **Mixtos**: puede ser cualquiera de los dos anteriores, o `"sistema"` cuando la acción la disparó un evento de otro módulo. |

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

`objeto_afectado` es el **espacio urbano sobre el que es el reclamo**, un eje
independiente de `categoria`: la categoría dice *qué pasó* y éste dice *sobre
qué*. Un auto sobre una bicisenda es `TRANSITO` y un pozo en esa misma bicisenda
es `BACHES`, pero los dos son `CICLOVIA`, así que quien se ocupa de ciclovías se
suscribe a un solo valor en vez de seguir todas las categorías. **Es opcional y
puede venir en `null`**: lo elige el vecino al cargar el reclamo y no todos los
reclamos afectan un espacio identificable.

```json
{
  "event_type": "reclamos.reclamo.creado",
  "data": {
    "reclamo_id": "6f1c9a4e-3c2b-4a5d-9e11-2b7d5c8a1f30",
    "ciudadano_id": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
    "titulo": "Luminaria apagada en la plaza",
    "categoria": "ALUMBRADO",
    "objeto_afectado": "PLAZA_PARQUE",
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

Sólo cuando la categoría la decidió **el modelo**. Sirve para medir la calidad del
clasificador. Si quien corrige es un operador, el evento es
`reclamos.reclamo.reclasificado`, no éste (ver ADR 0010).

```json
{
  "event_type": "reclamos.reclamo.clasificado",
  "data": {
    "reclamo_id": "6f1c9a4e-...",
    "categoria": "ALUMBRADO",
    "objeto_afectado": "PLAZA_PARQUE",
    "prioridad": "MEDIA",
    "confianza": 0.8134,
    "modelo": "naive-bayes-corpus-v1",
    "evidencia": ["luminaria", "poste", "apagada"]
  }
}
```

### `reclamos.reclamo.reclasificado` — v1.0

Un **operador** corrigió la clasificación. Lleva el par anterior/nuevo de las tres
cosas que una reclasificación puede cambiar, porque quien consumió la clasificación
vieja necesita saber qué deshacer: Residuos libera un contenedor cuando un reclamo
deja de ser `TRANSITO`.

```json
{
  "event_type": "reclamos.reclamo.reclasificado",
  "data": {
    "reclamo_id": "6f1c9a4e-...",
    "ciudadano_id": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
    "categoria_anterior": "RUIDOS",
    "categoria_nueva": "TRANSITO",
    "prioridad_anterior": "BAJA",
    "prioridad_nueva": "ALTA",
    "objeto_afectado_anterior": null,
    "objeto_afectado_nuevo": "CICLOVIA",
    "titulo": "Auto estacionado sobre la ciclovia",
    "descripcion": "Hay un auto arriba de la bicisenda y no se puede pasar",
    "barrio": "Palermo",
    "latitud": -34.5955,
    "longitud": -58.4281,
    "reclasificado_por": "operador-1",
    "reclasificado_at": "2026-10-22T20:31:04.120Z"
  }
}
```

### `reclamos.reclamo.estado-cambiado` — v1.0

```json
{
  "event_type": "reclamos.reclamo.estado-cambiado",
  "data": {
    "reclamo_id": "6f1c9a4e-...",
    "ciudadano_id": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
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
    "ciudadano_id": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
    "categoria": "ALUMBRADO",
    "objeto_afectado": "PLAZA_PARQUE",
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
    "ciudadano_id": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
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
    "ciudadano_id": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
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
- **Objeto afectado:** `CICLOVIA` · `CALZADA` · `VEREDA` · `SENDA_PEATONAL` ·
  `PLAZA_PARQUE` · `MOBILIARIO_URBANO` · `EDIFICIO_PUBLICO` · `OTRO`
  (opcional: puede venir en `null`)
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
- Salen **tres** de nuestros siete eventos. El resto no tiene consumidores fuera
  del módulo.

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
  "ciudadanoId": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
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
  "ciudadanoId": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
  "estadoAnterior": "EN_PROCESO",
  "estadoNuevo": "RESUELTO",
  "motivo": "Se retiro el vehiculo",
  "asignadoA": "cuadrilla-3",
  "cambiadoPor": "operador-1",
  "correlationId": "req-7c9e6679",
  "updatedAt": 1792349999000
}
```

### `com.citypass.reclamos.ReclamoReclasificado`

Se publica cuando un operador corrige la clasificación. Es el evento que cierra el
hueco que detectaron Emergencias y Residuos: una reclasificación no cambia el estado
del reclamo, así que no genera un `ReclamoActualizado` y hasta ahora no salía nada.

```json
{
  "reclamoId": "b1d4e8f2-6a30-4c99-8e71-0f5a2d6c3b84",
  "ciudadanoId": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
  "categoriaAnterior": "RUIDOS",
  "categoriaNueva": "TRANSITO",
  "prioridadAnterior": "BAJA",
  "prioridadNueva": "ALTA",
  "objetoAfectadoAnterior": null,
  "objetoAfectadoNuevo": "CICLOVIA",
  "afectaCirculacionAnterior": false,
  "afectaCirculacionNueva": true,
  "titulo": "Auto estacionado sobre la ciclovia",
  "descripcion": "Hay un auto arriba de la bicisenda y no se puede pasar",
  "barrio": "Palermo",
  "latitud": -34.5955,
  "longitud": -58.4281,
  "reclasificadoPor": "operador-1",
  "correlationId": "req-7c9e6679",
  "reclasificadoAt": 1792349999000
}
```

`afectaCirculacionAnterior` y `afectaCirculacionNueva` van calculadas de la categoría,
igual que en `ReclamoCreado`, para que nadie tenga que reimplementar la regla sólo
para saber si el reclamo pasó a importarle.

**Este evento depende de que el Grupo 1 lo registre en el catálogo.** Hasta entonces
el gateway lo rechaza, nosotros lo logueamos y seguimos: no rompe nada, pero tampoco
llega.

### Lo que recibimos por webhook

`POST /api/v1/webhooks/citypass`. Se autentica con un secreto compartido, por
cabecera `X-Webhook-Token` (preferido) o por `?token=...`. Las entregas son
*at-least-once* y los tres handlers son idempotentes.

| Tipo del gateway | Qué hacemos |
| --- | --- |
| `com.citypass.residuos.AlertaGenerada` | Si `tipoAlerta = SATURACION`, abre un reclamo de RESIDUOS. Las de incendio se ignoran. |
| `com.citypass.emergencias.EmergenciaCreada` | Eleva la prioridad de los reclamos abiertos del barrio. No escala si la severidad es baja ni si `afectaCirculacion` es falso. |
| `com.citypass.espacios.EventoComunitarioPublicado` | Con cupo ≥ 100, eleva a `MEDIA` los reclamos abiertos de la zona. Los `CANCELLED` se ignoran. |
| `com.citypass.espacios.IntervencionFinalizada` | **Cierra el reclamo.** Con `resultado: RESUELTO` pasa a RESUELTO; con `RECHAZADO`, a RECHAZADO. Ver abajo. |

#### `IntervencionFinalizada`, el que cierra el circuito

Es el ultimo eslabon del caso de uso: el vecino reporta, nosotros derivamos,
Espacios Publicos resuelve en la calle y nos avisa como termino.

```json
{
  "reclamoId": "7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
  "resultado": "RESUELTO",
  "idAuto": "AB123CD",
  "solicitadoAt": 1792346000000,
  "resueltoAt": 1792349999000
}
```

`resultado` es el campo que importa y acepta **`RESUELTO`** o **`RECHAZADO`**.
No son lo mismo: Espacios manda el evento aunque no hayan intervenido - si no
hacia falta una grua, por ejemplo - y en ese caso el reclamo no se resolvio, no
se tomo. El vecino lee un texto distinto en cada caso, y mandar todo como
resuelto seria decirle que su problema se soluciono cuando puede seguir ahi.

El resto de los campos son del dominio de ellos: no los guardamos, viajan para
que Analitica pueda medir cuanto tardo la intervencion.

**Idempotencia:** si el reclamo ya esta en ese estado, o ya esta cerrado o
rechazado, el evento no hace nada. Una reentrega del gateway es inofensiva.


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
