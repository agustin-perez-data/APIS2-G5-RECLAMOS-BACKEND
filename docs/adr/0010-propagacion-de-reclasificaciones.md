# ADR 0010 — Propagar las reclasificaciones con un evento propio

- **Estado:** Aceptada
- **Fecha:** 2026-10-22
- **Contexto:** Caso de uso integrado CU-INT-01 · Grupo 5

Extiende el catálogo de eventos decidido en el [ADR 0009](0009-integracion-por-el-gateway.md).
No lo reemplaza: la decisión de integrarse por el gateway y traducir en el borde
sigue vigente; lo que cambia es que salen tres eventos y no dos.

## Contexto

Cuando un operador corrige la clasificación de un reclamo, hoy eso no sale del
módulo. La reclasificación no toca la máquina de estados —es deliberado, ver
ADR 0005— así que no genera un `ReclamoActualizado`, y el evento interno de
clasificación no se publica al gateway porque se asumió que nadie lo consumía
afuera.

El agujero es concreto: un reclamo que pasa de `RUIDOS` a `BACHES` se vuelve
relevante para Movilidad, Emergencias y Residuos, y ninguno se entera. Y no es
un caso raro. El clasificador manda a revisión manual todo lo que predice con
menos de 0,35 de confianza, así que la corrección del operador es parte normal
del flujo — y es exactamente el caso donde la categoría estaba mal, o sea donde
`afectaCirculacion` probablemente también lo estaba.

Lo detectaron **Emergencias y Residuos por separado**, lo que descarta que sea
una preocupación teórica nuestra. Residuos además ya dejó implementado el
consumidor: si un reclamo pasa a `TRANSITO` evalúan si el auto tapa un
contenedor, y si deja de serlo liberan el contenedor que tenían bloqueado.

## Opciones consideradas

### A. Dejarlo documentado como limitación

- ❌ Residuos ya implementó su lado y está esperándonos. Movilidad y Emergencias
  tomarían decisiones con una categoría que saben desactualizada.

### B. Emitir `ReclamoActualizado` con el estado sin cambiar

- ✅ No requiere registrar nada nuevo en el catálogo del gateway.
- ❌ Rompe la semántica del evento para todos los demás: `ReclamoActualizado`
  significa "cambió el estado", y mandarlo con `estadoAnterior` igual a
  `estadoNuevo` obliga a cada consumidor a filtrar un caso que no esperaba.
- ❌ No tiene dónde poner la categoría anterior, que es justamente lo que los
  consumidores necesitan para deshacer lo que hicieron con la vieja.

### C. Un tipo de evento nuevo *(elegida)*

`reclamos.reclamo.reclasificado` internamente,
`com.citypass.reclamos.ReclamoReclasificado` en el gateway.

- ✅ Semántica clara y payload que puede llevar el par anterior/nuevo.
- ✅ Los consumidores se suscriben sólo si les interesa.
- ❌ Hay que registrarlo en el catálogo del Grupo 1 antes de que funcione.

## Decisión

Adoptamos **C**, y además **`reclasificar()` deja de publicar
`ReclamoClasificado`**.

Ese evento describe lo que decidió el modelo y lleva su confianza, su nombre y
su evidencia. Una corrección humana no tiene nada de eso: hasta ahora lo
publicábamos con `confianza=1.0`, `modelo="operador"` y `evidencia=[]`, es decir
rellenando de mentira campos que son del clasificador. El evento nunca fue el
adecuado para este caso. A partir de ahora `ReclamoClasificado` significa
exactamente "el modelo clasificó" y `ReclamoReclasificado`, "una persona
corrigió".

### El payload

Lleva el par anterior/nuevo de las tres cosas que la reclasificación puede
cambiar —categoría, prioridad y objeto afectado— más el contexto que un
consumidor necesita para actuar: `ciudadanoId`, `titulo`, `descripcion`,
`barrio`, `latitud`, `longitud`, `reclasificadoPor`, `reclasificadoAt` y
`correlationId`.

En el gateway se agregan además **`afectaCirculacionAnterior` y
`afectaCirculacionNueva`**, calculadas de la categoría igual que en
`ReclamoCreado`. Es el dato sobre el que realmente actúan Movilidad, Emergencias
y Residuos, y mandarlo calculado evita que cada uno reimplemente la regla.

**Por qué un payload más amplio que el que pidió Residuos.** Ellos pidieron ocho
campos. El esquema Avro del gateway se registra una sola vez y extenderlo
después cuesta otra ronda de coordinación con el Grupo 1, así que conviene
cubrir de entrada lo que previsiblemente va a pedir el resto.

## Consecuencias

**Positivas.** Se cierra un agujero real que afecta a tres módulos.
`ReclamoClasificado` recupera un significado preciso.

**Negativas.** Un tipo de evento más que mantener, y una dependencia: **esto no
funciona hasta que el Grupo 1 registre el tipo en su catálogo.** Mientras tanto
el gateway responde 400 o 404, y nuestro publisher lo loguea como
`evento.rechazado.gateway` y no reintenta, así que se puede desplegar sin
romper nada y empieza a funcionar solo cuando lo registren, sin redeploy.

**Qué queda por revisar.** Si aparece un consumidor que necesite saber que el
modelo reclasificó por su cuenta —hoy no pasa, el modelo sólo clasifica en el
alta— habría que revisar si `ReclamoClasificado` también debería salir al
gateway.
