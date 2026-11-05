# ADR 0015 — Autenticación ciudadana solo con email

- **Estado:** Aceptada
- **Fecha:** 2026-11-05
- **Contexto:** G5D-433 · Grupo 5
- **Sustituye:** La decisión de usar contraseñas ciudadanas del
  [ADR 0011](0011-autenticacion-de-ciudadanos.md). Sus decisiones sobre identidad
  local, UUID y separación respecto de G2 siguen vigentes.

## Contexto

El ADR 0011 estableció que Reclamos registra a sus propios ciudadanos porque el
Login Federado del Grupo 2 autentica solo a personal municipal. En ese momento
se eligió correo y contraseña para el registro y el login de vecinos. Por
indicación del profesor, el flujo ciudadano debe utilizar únicamente el email,
sin contraseña. Esto no cambia la autenticación de operadores y administradores.

El frontend ya consume un JWT de Reclamos para las rutas protegidas. Conviene
conservar ese contrato de respuesta y la separación entre el emisor local de
ciudadanos y el emisor de G2 para empleados.

## Opciones consideradas

### A. Mantener correo y contraseña para ciudadanos

- ✅ Permite comprobar un secreto que conoce quien registró la cuenta.
- ❌ Contradice el requisito indicado para G5D-433 y obliga al frontend a seguir
  solicitando y administrando una contraseña ciudadana.

### B. Registro con nombre y email; login solo con email *(elegida)*

- ✅ Cumple el requisito sin alterar el formato del JWT ni los permisos actuales.
- ✅ Elimina la contraseña de los formularios y del servicio ciudadano.
- ❌ Conocer un email registrado basta para obtener un token de esa cuenta: el
  sistema no comprueba la posesión del buzón.

### C. Verificar la posesión del email mediante enlace u OTP

- ✅ Probaría el control del buzón antes de emitir el token.
- ❌ Añade envío de correo, expiración y validación de desafíos que no forman
  parte del flujo pedido para esta tarea.

## Decisión

Adoptamos **B** para los ciudadanos:

- `POST /api/v1/auth/ciudadanos/registro` recibe `nombre` y `email`, sin
  contraseña. El email se valida, se recortan sus espacios exteriores y se
  guarda en minúsculas. El nombre se recorta y debe tener entre 2 y 120
  caracteres. El registro crea la cuenta local y devuelve un JWT directamente.
- `POST /api/v1/auth/ciudadanos/login` recibe solo `email`. Busca una cuenta
  existente por el email normalizado; si no existe responde 401 con
  `email_no_registrado`, y si está inactiva responde 401 con `cuenta_inactiva`.
  No crea cuentas. Si está activa, actualiza el último acceso y devuelve un JWT.
- El registro conserva el 409 para `email_ya_registrado` y las entradas inválidas
  siguen produciendo 422. La respuesta exitosa mantiene `TokenOut`:
  `access_token`, `token_type`, `expires_in` y `usuario`.

### Identidad y permisos que se conservan

El ciudadano mantiene un **UUID local** como identificador. Ese UUID viaja en
`sub` del JWT y, como cadena, en `reclamos.ciudadano_id`. No se sustituye por un
identificador de G2 ni se agrega una clave foránea a esa columna compartida con
otros tipos de actor, tal como decidió el ADR 0011.

Reclamos sigue emitiendo el JWT ciudadano con el rol `ciudadano`, un emisor,
audiencia y secreto propios. La validación selecciona la configuración por
`iss`, verifica firma, audiencia, emisor y expiración, y limita los roles que el
emisor local puede otorgar. `UsuarioDep`, `StaffDep` y `AdminDep` conservan sus
reglas de autorización; un token ciudadano no obtiene permisos de operador o
administrador.

El **Login Federado de G2** continúa siendo el mecanismo para empleados. Sus
tokens y grupos se validan mediante la configuración del emisor de staff; esta
decisión no cambia sus endpoints, credenciales ni permisos. El login local de
desarrollo (`/api/v1/auth/dev/login`) conserva `usuario` y `password` para
usuarios fijos de prueba: es un sustituto temporal del flujo de G2, no el login
ciudadano de producción ni el mecanismo real del IdP.

### Persistencia y transición

La migración Alembic **0010** cambia únicamente `ciudadanos.password_hash` a
nullable. El modelo y el servicio dejan de escribir ese campo, por lo que una
cuenta nueva puede registrarse sin contraseña. Los hashes de cuentas anteriores
permanecen en la base por ahora; la columna no se elimina en esta fase. No hay
cambio de esquema para empleados.

El `downgrade` de 0010 intenta volver la columna a `NOT NULL`. **No puede
completarse si ya hay ciudadanos nuevos con `password_hash = NULL`** sin una
estrategia explícita para esos datos. Tampoco se debe asumir compatibilidad de
login durante un despliegue mixto: una versión anterior que todavía exige
contraseña no podrá autenticar las cuentas nuevas sin hash. Aplicar 0010 antes
de desplegar el servicio nuevo permite el alta sin contraseña, pero no resuelve
esa limitación de convivencia ni el rollback.

## Consecuencias

**Positivas.** Se cumple el flujo ciudadano solicitado sin cambiar el contrato
del token, los UUID locales, la identidad de empleados ni la autorización por
roles. El frontend puede retirar contraseña y confirmación de contraseña de
los formularios ciudadanos.

**Negativas.** El email funciona como identificador, no como prueba de identidad.
Cualquier persona que conozca el email de una cuenta activa puede iniciar sesión
como ella y acceder a sus reclamos. Los códigos distintos para email inexistente
y cuenta inactiva, junto con el 409 de registro, también permiten inferir el
estado de una cuenta. El rate limit existente reduce solicitudes repetidas,
pero no verifica la posesión del correo. Esta limitación se acepta por el
requisito indicado; no debe presentarse como autenticación segura para un
despliegue que necesite verificar identidad.

**Pendiente de revisión.** Si se requiere probar la posesión del email, hará
falta una decisión posterior sobre enlace u OTP y sobre la emisión del token.
Antes de eliminar la columna histórica `password_hash` o prometer un downgrade
reversible, habrá que definir el tratamiento de las cuentas existentes y de
las creadas con valor nulo.
