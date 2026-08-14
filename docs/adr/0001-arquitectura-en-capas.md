# ADR 0001 — Arquitectura en capas con puertos

- **Estado:** Aceptada
- **Fecha:** 2026-08-13
- **Contexto:** Sprint 0 · Grupo 5 (Reclamos y Participación Ciudadana)

## Contexto

El módulo tiene que exponer una API REST, persistir en Supabase, publicar y
consumir eventos de Kafka, y correr un clasificador. Necesitamos una estructura
interna que permita testear la lógica de negocio sin levantar broker ni base, y
que aguante que el equipo (5 personas trabajando en paralelo) toque partes
distintas sin pisarse.

La rúbrica evalúa explícitamente "modularidad interna, separación de
responsabilidades y uso de patrones adecuados" (10 pts).

## Opciones consideradas

### A. Todo en los routers de FastAPI

Endpoints que abren sesión, hacen queries y publican eventos.

- ✅ Rapidísimo para el MVP, cero indirección.
- ❌ Imposible testear una regla de negocio sin levantar HTTP + base + broker.
- ❌ Con 5 personas, los routers se convierten en el archivo de los conflictos.
- ❌ La lógica se duplica: un reclamo creado por evento no pasaría por las
  mismas validaciones que uno creado por la app.

### B. Arquitectura hexagonal completa

Entidades de dominio puras, puertos y adaptadores para todo (persistencia, bus,
HTTP), mappers entre modelo de dominio y modelo ORM.

- ✅ Máximo desacople, la más "de libro".
- ❌ Duplicar cada entidad (dominio + ORM + DTO) y mantener mappers a mano es
  mucho código para un módulo de este tamaño.
- ❌ Costo de aprendizaje alto para un equipo que recién arranca con FastAPI;
  el riesgo es terminar con una hexagonal a medias, que es peor que ninguna.

### C. Capas + puertos donde importa *(elegida)*

`api → services → repositories → db`, con `domain/` puro y un **puerto** solo
para el bus de eventos (`EventPublisher`).

- ✅ Cada capa se testea sola; el servicio no importa FastAPI ni Kafka.
- ✅ Los modelos ORM se usan como entidades: sin mappers, sin duplicación.
- ✅ El puerto del bus es donde el desacople **paga**: permite correr toda la
  suite sin broker con `InMemoryEventPublisher`.
- ⚠️ El servicio conoce SQLAlchemy indirectamente (recibe `AsyncSession`). Es un
  acople aceptado: no vamos a cambiar de motor.

## Decisión

Adoptamos la opción **C**.

Reglas concretas:

1. Las dependencias apuntan hacia adentro. `api/` no importa `repositories/` ni
   modelos ORM; `services/` no importa nada de `api/`; `domain/` no importa nada
   del proyecto.
2. El repositorio hace `flush()`, **nunca `commit()`**. La unidad de trabajo la
   controla el servicio.
3. El servicio depende de la abstracción `EventPublisher`, no de `aiokafka`.
4. Los handlers de eventos **no** tocan la base: pasan por `ReclamoService`, de
   modo que un reclamo nacido de un evento respeta las mismas invariantes que
   uno creado desde la app.

## Consecuencias

**Positivas.** El 100% de las reglas de negocio se testea sin infraestructura
(90 tests corriendo en ~3 segundos). Cambiar Kafka por otro bus es implementar
una clase. Los conflictos de merge bajaron porque cada persona trabaja en su
capa.

**Negativas.** Hay indirección: agregar un endpoint toca cuatro archivos
(schema, servicio, router, test). Lo asumimos como el costo de que el código
sea navegable a seis sprints vista.

**A revisar.** Si aparece un segundo agregado con reglas propias (por ejemplo
"Encuestas vecinales"), evaluar mover a módulos verticales por agregado en lugar
de capas horizontales.
