# ADR 0021 — La configuración de Render vive en el repositorio

- **Estado:** Aceptada
- **Fecha:** 2026-11-15
- **Contexto:** G5D-7 · DevOps · Grupo 5

## Contexto

El servicio de producción estaba configurado a mano en el panel de Render: el
plan, la región, el health check y 38 variables de entorno. Nada de eso estaba
en el repositorio, con tres consecuencias que ya se habían pagado:

- Nadie podía saber qué configuración tenía producción sin entrar al panel, y
  al panel entra una sola persona del equipo. La variable `ENVIRONMENT` estuvo
  semanas en `dev` sin que se notara.
- Un cambio de configuración no pasaba por revisión ni dejaba historial.
- Si el servicio se perdía había que reconstruirlo de memoria.

## Opciones consideradas

**A. Seguir en el panel y documentar las variables en un texto.** ❌
Es lo que había. Un documento que nadie ejecuta se desactualiza el mismo día en
que alguien cambia algo en el panel.

**B. Un Blueprint de Render (`render.yaml` vinculado al repositorio).** ❌ por ahora
Es el mecanismo nativo, pero la API de Render no permite crear un Blueprint:
hay que vincularlo desde el panel, autorizando el repositorio con la cuenta
dueña del servicio. Además Render ignora en cada sincronización las variables
marcadas como secreto, así que no reemplaza una verificación propia.

**C. `render.yaml` en el repositorio, aplicado y verificado por un workflow
propio con la API de Render.** ✅
El archivo usa el formato de Blueprint, así que la opción B queda abierta sin
reescribir nada, pero no depende de ella: `scripts/render_config.py` lo lee y
lo compara con lo que informa la API.

## Decisión

`render.yaml`, en la raíz, es la fuente de verdad del servicio y de toda
variable de entorno que no sea un secreto. Se escribió a partir de lo que
devolvió la API de Render el 15/11/2026, no de memoria.

- Una variable con `value` es configuración pública: se versiona con su valor.
- Una variable con `sync: false` es un secreto: se versiona solo el nombre.

El workflow `configuracion-render.yml` corre `scripts/render_config.py`:

| Cuándo | Qué hace |
| --- | --- |
| Un cambio de `render.yaml` llega a `main` | Escribe en Render las variables públicas que difieren y redespliega |
| Los lunes, y a pedido | Solo compara; si Render difiere del archivo, la corrida queda en rojo |

Lo que el script no hace, a propósito:

- **No escribe ni lee el valor de un secreto.** Solo verifica que exista.
- **No borra nada.** Una variable que está en Render y no en el archivo se
  informa como diferencia para que la resuelva una persona.
- **No imprime valores, solo nombres.** El repositorio es público y sus logs
  también.
- **No usa la escritura masiva de variables** de la API, que reemplaza el
  conjunto completo y borraría todos los secretos; escribe de a una.

Tres tests sobre el archivo real corren en cada PR: toda variable declarada es
un ajuste que la aplicación conoce, ningún secreto está escrito en claro, y la
configuración declarada pasa las validaciones de arranque de producción.

## Consecuencias

**Positivas**

- La configuración de producción se lee en el repositorio, se cambia por pull
  request y queda en el historial.
- Un cambio hecho a mano en el panel se detecta a lo sumo en una semana.
- Un `render.yaml` que dejaría al servicio sin arrancar falla en el CI.

**Negativas**

- Los valores de los secretos siguen solo en Render. Recrear el servicio desde
  cero exige volver a cargarlos.
- Los ajustes del servicio que no son variables (plan, región, health check)
  se verifican pero no se aplican: cambiarlos sigue siendo manual.
- Supabase y Vercel siguen configurados a mano.

**Queda por revisar**

- Vincular el repositorio como Blueprint, si se quiere que Render aplique
  también los ajustes del servicio.
