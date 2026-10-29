# ADR 0013 — Reclamos relacionados con actividades masivas

- **Estado:** Aceptada
- **Fecha:** 2026-10-28
- **Contexto:** Caso de uso transversal del squad 3, "Recolección inteligente después de un evento masivo" · Grupo 5

## Contexto

Termina un festival en una plaza y los sensores detectan una acumulación anormal
de residuos. El diagrama del squad tiene un solo evento, `ActividadCreada`, que
publica Espacios Públicos y Cultura. Reaccionan cuatro módulos, y a Reclamos le
toca esto:

> "Se entera que va a haber un evento masivo, entonces todos los reclamos que se
> hagan en la zona se sabe que están relacionados al evento masivo."

El evento trae la actividad con su capacidad, su estado, la fecha de inicio y de
fin en milisegundos y la ubicación en coordenadas (`ubicacion { lat, lng }`). No
trae barrio. Residuos y Movilidad ya acordaron en el squad tres números: es
masiva desde **1.000 personas**, la zona es de **300 m** y la limpieza sigue
**6 h** después del fin.

Hay que decidir qué quiere decir "relacionado" en nuestro modelo y en qué momento
se calcula.

## Opciones consideradas

### A. Relacionar los reclamos abiertos de la zona cuando llega el evento

- ✅ Es lo mismo que ya hacen los handlers de Emergencias y del CU-INT-01.
- ❌ **No es lo que pide el diagrama.** Habla de los reclamos *que se hagan*. Un
  bache denunciado hace un mes no tiene nada que ver con un festival que se
  anunció hoy.
- ❌ El evento llega cuando se crea la actividad, muchas veces días antes. En ese
  momento todavía no existe ninguno de los reclamos que importan.

### B. Calcular la relación al leer, sin guardarla

En cada listado, buscar por distancia y horario qué actividad le corresponde a
cada reclamo.

- ✅ No agrega ninguna columna.
- ❌ Cada listado calcula distancias contra todas las actividades, y filtrar "los
  reclamos de este festival" obliga a recorrer todos los reclamos.
- ❌ La relación puede cambiar sola si cambia la ventana o el radio, y un reclamo
  que ayer estaba relacionado hoy deja de estarlo sin que nadie lo toque.

### C. Guardar la actividad y relacionar cada reclamo en su alta *(elegida)*

`ActividadCreada` guarda la actividad. Al dar de alta un reclamo, si cae cerca de
una actividad en curso, se guarda su `actividad_id` en la misma transacción.

- ✅ Es literalmente lo que dice el diagrama: la relación nace con el reclamo.
- ✅ Filtrar por actividad es una columna indexada.
- ✅ El reclamo y su relación se guardan juntos o no se guarda ninguno.
- ✅ No toca a ningún otro caso de uso: el alta sigue igual para los reclamos que
  no caen cerca de nada.
- ❌ Un reclamo cargado antes de que llegue el evento no se relaciona después.

## Decisión

Adoptamos **C**.

### Qué actividades se guardan

Las que no están canceladas, tienen 1.000 personas o más y traen coordenadas. El
resto se ignora y se responde `204`, porque no hay nada que relacionar.

Sin `fechaHoraInicio`, la actividad cuenta desde que llega el evento. Sin
`fechaHoraFinalizacion` el evento es inválido, como cualquier otro payload mal
formado: el handler falla y el dispatcher lo reintenta y lo deja en su cola de
muertos.

**Idempotencia:** la clave es el `actividadId` de Espacios, con un `UNIQUE` en
la tabla. Una reentrega, o la misma actividad publicada con otro `eventId`, no la
duplica.

### Cuándo un reclamo queda relacionado

Cuando, en su alta, cumple las tres cosas:

1. Tiene coordenadas.
2. Está a 300 m o menos del centro de la actividad.
3. La actividad ya empezó y terminó hace menos de 6 h.

Con dos actividades en rango gana la más cercana. Vale para todos los reclamos,
incluidos los que abre Residuos por un contenedor desbordado: son justamente los
que más importan después de un festival.

Los tres números son configuración (`ACTIVIDAD_MASIVA_CAPACIDAD_MINIMA`,
`ACTIVIDAD_MASIVA_RADIO_METROS`, `ACTIVIDAD_MASIVA_HORAS_DESPUES`), con los
valores acordados en el squad como valor por defecto.

### Qué no hace

- **No cambia la prioridad ni notifica a nadie.** El diagrama pide saber que los
  reclamos están relacionados, nada más. La prioridad por eventos culturales ya la
  maneja el CU-INT-01 por su lado.
- **No publica ningún evento.** En el diagrama del squad, Reclamos solo recibe.

### Nombres de los campos

Aceptamos los del plan del squad (`actividadId`, `fechaHoraFinalizacion`,
`ubicacion`) y también los del primer borrador de Espacios, en inglés
(`communityEventId`, `endDate`, `latitude`). Así funciona con cualquiera de las
dos versiones de su publicador.

## Consecuencias

**Positivas.** El operador ve en la bandeja, el listado y el detalle con qué
actividad se relaciona cada reclamo, y puede filtrar todos los de un festival con
`GET /reclamos?actividad_id=`. `GET /actividades` muestra las actividades en
curso con cuántos reclamos lleva cada una.

**Negativas.**
- Un reclamo sin coordenadas no se puede relacionar: el evento no trae barrio.
- Si Espacios publica la actividad tarde, los reclamos cargados antes no quedan
  relacionados.
- Una actividad cancelada después de creada sigue relacionando reclamos: hoy
  Espacios no publica cancelaciones.

**Qué queda por revisar.**
1. Si Espacios suma `ActividadCancelada`, cerrar la ventana de la actividad al
   recibirla.
2. Si Analítica necesita la relación, sumar `actividadId` a `ReclamoCreado`.
   Requiere acordarlo con el Grupo 1, porque el schema Avro está registrado en
   su catálogo.
