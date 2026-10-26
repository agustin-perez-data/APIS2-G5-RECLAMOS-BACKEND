# Schemas Avro de los eventos que publicamos

Estos tres archivos son los que hay que cargar en el **catálogo del gateway del
Grupo 1**. El gateway valida cada evento contra el schema registrado antes de
aceptarlo: un tipo que no está en el catálogo se rechaza, que es exactamente por
qué `ReclamoReclasificado` fallaba antes de registrarlo.

| Archivo | Nombre completo en el catálogo | Cuándo se emite |
| --- | --- | --- |
| `ReclamoCreado.avsc` | `com.citypass.reclamos.ReclamoCreado` | Alta de un reclamo |
| `ReclamoActualizado.avsc` | `com.citypass.reclamos.ReclamoActualizado` | Cada cambio de estado. **La resolución viaja acá**, con `estadoNuevo = RESUELTO` |
| `ReclamoReclasificado.avsc` | `com.citypass.reclamos.ReclamoReclasificado` | Un operador corrigió la clasificación |

El `namespace` sale del claim del mismo nombre en nuestro token de servicio, así
que tiene que ser `com.citypass.reclamos` y no otro.

## Cómo registrarlos

Desde la consola del gateway, en el catálogo de tipos, cargando el contenido de
cada `.avsc`. Después se crea una suscripción por cada evento que queremos
recibir, apuntando a nuestro webhook.

> **El secreto del webhook va en la URL**, como `?token=...`. El dispatcher del
> Grupo 1 no envía cabeceras propias, así que la opción de `X-Webhook-Token` que
> el endpoint también acepta no aplica acá. Por eso el filtro de
> `app/core/logging.py` que lo enmascara en el log de acceso no es una red de
> seguridad opcional: es lo único que evita que el secreto quede en texto plano
> en los logs de la plataforma.

## Por qué los tipos son `string` y no `enum`

Avro permite declarar enumeraciones, y para `categoria`, `prioridad` o `estado`
sería más preciso. No se usan a propósito: **agregar un valor nuevo a un enum de
Avro es un cambio de schema**, y entonces sumar una categoría obligaría a
coordinar con el Grupo 1 y a que todos los consumidores actualicen.

Es la misma decisión que ya está tomada en `app/db/types.py`, donde los enums se
guardan como `VARCHAR` para que agregar una categoría no requiera una migración.
Los valores válidos están documentados en el campo `doc` de cada uno.

## Cómo se mantienen sincronizados con el código

`tests/unit/test_schemas_avro.py` compara cada schema contra la salida real de
`traducir()`, en `app/events/gateway.py`. Verifica que no sobre ni falte ningún
campo, que todo lo que puede venir nulo esté declarado como tal, y que el nombre
completo coincida con el del catálogo.

**Si cambiás un payload del gateway y no actualizás el schema, la suite falla.**
Es deliberado: un schema que miente es peor que no tenerlo, porque el gateway
empieza a rechazar eventos válidos y el síntoma aparece en producción, del lado
de otro equipo.

## Qué se puede cambiar sin romper a nadie

Es la misma regla de versionado que ya está en [`../eventos.md`](../eventos.md),
y no es casualidad: viene de las reglas de compatibilidad de Avro.

- **Agregar un campo opcional, con `default`** → compatible. Los consumidores que
  leen el schema viejo lo ignoran.
- **Quitar o renombrar un campo, o cambiarle el tipo** → rompe. Hay que subir la
  versión mayor y publicar en paralelo hasta que todos migren.

Por eso los campos opcionales se declaran como `["null", "<tipo>"]` con
`"default": null`. Avro exige que el default corresponda a la primera rama de la
unión, y sin él un consumidor que lee un schema anterior no tiene con qué
completar el hueco.
