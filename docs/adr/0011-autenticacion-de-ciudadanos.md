# ADR 0011 — Autenticación de ciudadanos en el propio módulo

- **Estado:** Aceptada (con deuda técnica registrada)
- **Fecha:** 2026-10-25
- **Contexto:** Entrega 2 · Grupo 5

## Contexto

El 25 de octubre de 2026 el Grupo 2 publicó su guía de integración con una
aclaración que invalida una premisa que este módulo venía arrastrando:

> **Solo para personal municipal.** El Login Federado autentica empleados,
> operadores y administradores de cada módulo. **No es el login de los
> ciudadanos.** Si tu módulo tiene usuarios finales, su registro y login los
> resuelve tu grupo por separado.

Reclamos es el módulo de cara al vecino: su usuario principal no es personal
interno. Hasta ahora asumíamos que el IdP del Grupo 2 iba a cubrirlo, y sobre esa
suposición se escribió el login de desarrollo (`app/api/v1/auth_dev.py`), cuyo
criterio de eliminación era "cuando el Grupo 2 exponga su emisor, se borra". Ese
criterio ya no alcanza: para el staff sigue valiendo, para los vecinos no hay a
quién delegarles nada.

Hay un segundo problema, de contrato: `docs/eventos.md` afirmaba que el
`ciudadano_id` de nuestros eventos es el `sub` del IdP y que los otros módulos lo
pueden cruzar contra su directorio. Con esta definición, un vecino no existe ahí.
Se corrigió en G5D-428.

## Opciones consideradas

### A. Esperar a que el Grupo 2 cubra usuarios finales

- ❌ Lo descartaron por escrito, no es una demora.
- ❌ Dejaría el módulo sin forma de que un vecino cargue un reclamo.

### B. Cada módulo con su propio login de ciudadanos *(elegida)*

Registro y login propios, con tokens que firmamos nosotros.

- ✅ Es lo que el Grupo 2 indica explícitamente.
- ✅ No bloquea: no dependemos de que nadie nos habilite nada.
- ❌ Dos sistemas de identidad conviviendo, y un vecino que use dos módulos va a
  tener una cuenta en cada uno. Es consecuencia de su decisión, no nuestra.

### C. Sesiones con cookie en vez de JWT para vecinos

- ❌ Dos mecanismos distintos de autenticación en la misma API: cada endpoint
  tendría que aceptar los dos, y el frontend manejar los dos.
- ❌ El token ya funciona y el front ya lo usa.

## Decisión

Adoptamos **B**. Los ciudadanos se registran con correo y contraseña en
`POST /api/v1/auth/ciudadanos/registro` y entran por `.../login`. Su identificador
es un **UUID**, deliberadamente distinto del `U000042` del IdP: viaja como `sub`
del token y aterriza en `reclamos.ciudadano_id`, donde tiene que ser imposible de
confundir con un empleado.

### Dos emisores, no dos caminos

Se descartó validar con dos dependencias distintas o probar un emisor y después
el otro. En su lugar hay un **registro `iss → EmisorJWT`**: el `iss` se lee sin
verificar sólo para elegir la configuración, y `jwt.decode` verifica todo contra
ella, `issuer` incluido, así que un `iss` mentido no sobrevive a la firma. Los
endpoints no cambiaron: `UsuarioDep`, `StaffDep` y `AdminDep` siguen razonando
por rol, que es lo correcto — la autorización es por rol y el origen es
procedencia.

Tres barreras independientes impiden que un token de ciudadano pase por operador:

1. **Issuer distinto** ⇒ otra clave, otro algoritmo y otra audiencia.
2. **Whitelist de roles por emisor**: el emisor local sólo puede otorgar
   `ciudadano`. Aunque un bug nuestro firmara `admin`, el rol se descarta al
   validar. Hay un test que lo comprueba quitando la whitelist.
3. **Un único algoritmo por emisor**, que cierra el *algorithm confusion*: la
   clave pública RS256 del IdP no se puede replayear como secreto HS256.

Decisión asociada: **no hay rol por defecto para el staff**. Un grupo LDAP que no
mapea no otorga nada, porque un empleado sin grupos asignados no tiene que
terminar con acceso de staff.

### Hashing con la biblioteca estándar

`hashlib.scrypt`, en `app/core/passwords.py`. Es memory-hard, OWASP lo acepta
como alternativa a Argon2id y no agrega dependencias, con el mismo criterio con
el que el ADR 0005 dejó afuera numpy y sklearn. Se descartó `passlib` (sin
mantenimiento desde 2020), `bcrypt` (trunca a 72 bytes) y `argon2-cffi`
(dependencia binaria para una sola función).

La decisión es **reversible sin costo**: el hash se guarda autodescrito
(`scrypt$n=16384,r=8,p=1$salt$hash`), así que migrar a Argon2 es agregar un
prefijo a `verificar_password` y rehashear en el próximo login exitoso. No hay
migración de datos ni reseteo masivo.

Sí se agregó **una** dependencia: `pydantic[email]`, pura Python y del mismo
autor que pydantic, porque el correo es el identificador de login y validarlo con
una expresión regular propia es un generador clásico de bugs.

### Dos rutas sin dependencia de identidad

`registro` y `login` se suman a la lista de excepciones del `CLAUDE.md`, junto a
`/health`, el login de desarrollo y el webhook del gateway (ADR 0009). El motivo
es el mismo de siempre: **no se puede presentar un token antes de tenerlo**. Los
controles que las protegen:

- **Rate limit por IP**, más estricto en el registro (5/hora) que en el login
  (10/minuto), porque una registración cuesta CPU y crea filas.
- **Respuesta genérica en el login**: contraseña incorrecta, correo no registrado
  y cuenta dada de baja devuelven exactamente el mismo cuerpo. Además se verifica
  contra un hash señuelo cuando el correo no existe, para que el tiempo de
  respuesta tampoco delate quién está registrado.
- **RLS en la tabla desde la migración que la crea**: vive en `public` y la anon
  key de Supabase es pública, así que sin RLS cualquiera leería los hashes por la
  API REST.
- Ninguna respuesta incluye el hash, y los logs no registran la contraseña ni el
  correo completo.

### Sin clave foránea

`reclamos.ciudadano_id` guarda tres clases de valor a la vez: un UUID local, el
`sub` del IdP en las acciones de staff, y `"sistema"` en los reclamos que abre un
evento de otro módulo. Una clave foránea obligaría a inventar filas fantasma para
los dos últimos.

## Consecuencias

**Positivas.** El módulo deja de depender de una decisión ajena para su caso de
uso principal. El contrato de eventos dice la verdad sobre qué id es cruzable y
cuál no.

**Negativas.** Mantenemos credenciales, que es responsabilidad que antes no
teníamos. El docstring de `app/core/security.py` y el `CLAUDE.md` decían *"nunca
emitimos tokens ni almacenamos credenciales"*: se corrigieron en este mismo
cambio, porque documentación activamente falsa es peor que no tenerla.

## Deuda registrada

1. **Sin verificación de correo.** Cualquiera se registra con un correo ajeno.
   Hoy el daño está acotado porque las notificaciones son in-app (ADR 0008);
   cualquier canal por mail en el futuro **exige** verificar primero.
2. **Sin recuperación de contraseña.** Una contraseña perdida es una cuenta
   perdida, con su historial de reclamos. Tampoco hay reseteo por admin.
3. **Sin refresh ni revocación.** El token es un bearer de 12 horas que no se
   puede invalidar; el logout es el frontend borrándolo. Camino: access corto más
   refresh con lista de revocación, como hace el Grupo 2.
4. **El 409 de correo duplicado es un oráculo de enumeración.** Se acepta por
   usabilidad del formulario; eliminarlo requiere el flujo del punto 1, así que
   están atados.
5. **Rate limit en memoria y por IP**, un solo proceso. No cubre fuerza bruta
   distribuida contra una cuenta puntual: falta backoff o bloqueo por cuenta.
6. **Parámetros de scrypt sin cronometrar en Railway.** En la máquina de
   desarrollo dan ~57 ms, por debajo del objetivo de 100–250 ms. Mitigado por el
   hash autodescrito y el rehash en el login.
7. **Sin borrado de cuenta**, así que el derecho al olvido queda pendiente.
8. **El JWKS del Grupo 2 se consulta de forma bloqueante** dentro del event loop
   (`PyJWKClient.get_signing_key_from_jwt`). Hoy no se nota porque nadie usa
   RS256; con el IdP real cableado, el primer request tras vencer la cache
   bloquea contra un servicio de otro grupo.
9. **Secreto simétrico.** Si algún día otro módulo necesitara verificar nuestros
   tokens de ciudadano, habría que compartirle el secreto. Hoy somos el único
   verificador; la salida sería RS256 con un JWKS propio.

**Criterio de salida.** Si el Grupo 2 llegara a cubrir usuarios finales, la
migración es agregar `idp_sub` a `ciudadanos`, vincular en el primer login
federado y dejar de emitir tokens locales. `CurrentUser.origen` ya distingue las
dos procedencias para esa convivencia.
