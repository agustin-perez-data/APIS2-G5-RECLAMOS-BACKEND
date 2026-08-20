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

Consumidor típico: Notificaciones / la app del vecino.

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
