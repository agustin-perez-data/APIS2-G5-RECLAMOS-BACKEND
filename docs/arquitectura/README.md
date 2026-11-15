# Arquitectura del módulo de Reclamos (Grupo 5)

Este directorio documenta la arquitectura con dos modelos complementarios:

- **C4** (Contexto, Contenedores, Componentes): hace zoom desde la plataforma
  CityPass+ hasta los paquetes de este repositorio.
- **4+1 de Kruchten**: mira el mismo sistema desde cinco ángulos, uno por tipo de
  pregunta.

Los diagramas están en Mermaid, así que GitHub los dibuja sin herramientas extra y
se revisan en un pull request como cualquier otro cambio.

## Qué vista responde qué pregunta

| Pregunta | Vista |
| --- | --- |
| ¿Con quién habla Reclamos y para qué? | [C4 nivel 1: Contexto](c4-1-contexto.md) |
| ¿Qué procesos corren, dónde y cómo se comunican? | [C4 nivel 2: Contenedores](c4-2-contenedores.md) |
| ¿Cómo está organizado el backend por dentro? | [C4 nivel 3: Componentes](c4-3-componentes.md) |
| ¿Qué entidades maneja el dominio y qué estados recorre un reclamo? | [Vista lógica](vista-logica.md) |
| ¿Qué pasa, paso a paso, cuando entra un pedido o un evento? | [Vista de procesos](vista-procesos.md) |
| ¿Cómo se organiza el código y cómo llega a producción? | [Vista de desarrollo](vista-desarrollo.md) |
| ¿En qué infraestructura corre cada parte? | [Vista física](vista-fisica.md) |
| ¿Cómo se combinan las vistas en los casos de uso que importan? | [Escenarios (+1)](escenarios.md) |

## Cómo se relacionan los dos modelos

| C4 | 4+1 | Qué comparten |
| --- | --- | --- |
| Nivel 1, Contexto | Escenarios | Los mismos actores y módulos vecinos |
| Nivel 2, Contenedores | Vista física | Los contenedores, ubicados en su infraestructura |
| Nivel 3, Componentes | Vista de desarrollo | Los componentes, vistos como paquetes y capas |
| (no aplica) | Vista lógica | El modelo de dominio |
| (no aplica) | Vista de procesos | El comportamiento en ejecución |

El nivel 4 de C4 (código) no se dibuja: el propio modelo C4 recomienda no
mantenerlo a mano, y en este repositorio lo cubren el código y sus tests.

## Reglas de mantenimiento

1. **La fuente es el código.** Los estados salen de `app/domain/enums.py`, los
   tópicos de `app/events/topics.py`, las entidades de `app/db/models/` y las
   capas de la estructura de `app/`. Un nombre que aparece en un diagrama tiene que
   existir en el código.
2. **Se dibuja lo que hay, con sus deudas.** Las limitaciones conocidas figuran en
   la vista donde se ven, con el ADR que las registra.
3. **Un cambio de arquitectura actualiza su vista en el mismo pull request**, igual
   que actualiza su ADR.

## Decisiones que explican los diagramas

Cada vista cita los ADR que justifican lo que muestra. El índice completo está en
[`docs/adr/`](../adr/README.md). El contrato de eventos, campo por campo, está en
[`docs/eventos.md`](../eventos.md) y los esquemas Avro en [`docs/avro/`](../avro/).
