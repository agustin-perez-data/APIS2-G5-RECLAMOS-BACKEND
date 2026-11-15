# ADR 0020 — Qué ve cada tipo de usuario de un reclamo

- **Estado:** Aceptada
- **Fecha:** 2026-11-15
- **Contexto:** G5D-3 · Seguridad e Identidad · Grupo 5

## Contexto

`GET /reclamos/{id}` pide estar autenticado y nada más. Es a propósito: un
vecino tiene que poder leer reclamos ajenos para adherir a uno que ya existe en
vez de cargar un duplicado (ADR 0007).

El problema es que esa respuesta era la misma para todos. Cualquier vecino
recibía, de cualquier reclamo:

- `asignado_a` y el `usuario_id` de cada entrada del historial, que son el
  identificador del operador en el Login Federado;
- `autor_id` y `autor_nombre` de los comentarios oficiales, que la aplicación
  además muestra en pantalla: el vecino veía el nombre de usuario del operador;
- `ticket_externo` y `correlation_id`, identificadores internos.

Eso contradecía una regla que el propio módulo ya aplicaba en otro lado: la
notificación de un comentario oficial dice "El municipio comentó", con un
comentario en el código que explica que la identidad del operador es interna.
La regla existía en un canal y no en los otros tres.

## Opciones consideradas

**A. Restringir el detalle al dueño del reclamo y al personal.** ❌
Es lo más simple y lo más seguro, pero rompe las adhesiones y la búsqueda de
similares, que son un caso de uso central: no se puede sumar a un reclamo que
no se puede leer.

**B. Un endpoint distinto para la vista pública.** ❌
Separa bien las dos vistas, pero obliga a cambiar la aplicación web para que
elija cuál pedir, y deja el endpoint actual con el mismo problema mientras
tanto.

**C. Misma ruta, respuesta filtrada según quién pregunta.** ✅
El contrato no cambia de forma: los mismos campos, con los internos en nulo o
con un valor genérico. La aplicación web no necesita ningún cambio, porque no
muestra esos campos a los vecinos, y donde sí mostraba el autor de un
comentario oficial pasa a mostrar "El municipio".

## Decisión

La regla vive en `app/api/visibilidad.py` y se aplica sobre los esquemas de
respuesta, nunca sobre los objetos de la base.

| Dato | Personal | Vecino dueño | Otro vecino |
| --- | --- | --- | --- |
| Título, descripción, estado, categoría, ubicación, área responsable, resolución | Sí | Sí | Sí |
| `asignado_a` | Sí | No | No |
| Autor de una entrada del historial hecha por el personal | Sí | `municipio` | `municipio` |
| Autor de un comentario oficial | Sí | `municipio` / "El municipio" | `municipio` / "El municipio" |
| `ticket_externo`, `correlation_id` | Sí | Sí | No |

Dos criterios detrás de la tabla:

1. **La identidad de quien atiende es interna para todos los vecinos**, incluido
   el dueño. El municipio responde como institución.
2. **Los identificadores internos son del dueño.** Le sirven para hacer el
   seguimiento; a un tercero no le sirven para nada.

Se aplica en `GET /reclamos/{id}`, `GET /reclamos/{id}/historial` y
`GET /reclamos/{id}/comentarios`. Las listas ya usaban una proyección sin esos
campos.

## Consecuencias

**Positivas**

- Un vecino ya no puede obtener el identificador de un operador por ninguna
  ruta de lectura de reclamos. Un test recorre la respuesta completa y verifica
  que el identificador no aparezca.
- La regla de "El municipio" queda escrita en un solo lugar y vale para los
  cuatro canales.
- Sin cambios en la aplicación web ni en el contrato de eventos.

**Negativas**

- El filtro se aplica en la capa de entrada. Un endpoint nuevo que devuelva un
  reclamo tiene que acordarse de pasar por `reclamo_visible`; no hay nada que
  lo obligue.
- Los comentarios y el historial viejos conservan el identificador del operador
  en la base: se oculta al leer, no se borra.
- `ciudadano_id` sigue a la vista de todos. Es un UUID local sin datos
  personales (ADR 0011), pero permite saber que dos reclamos son del mismo
  vecino.

**Qué queda por revisar**

1. Los eventos `ReclamoActualizado` y `ReclamoReclasificado` llevan `asignadoA`,
   `cambiadoPor` y `reclasificadoPor` hacia los otros módulos. Son sistemas del
   municipio, no vecinos, y esos campos están en el contrato registrado, pero
   conviene revisar si los necesitan.
2. Si se quiere ocultar también `ciudadano_id` a terceros, hay que ver primero
   cómo lo usa la aplicación web.
