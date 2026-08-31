# Guía de integración para el frontend — Entrega 1

Módulo de **Reclamos y Participación Ciudadana** (Grupo 5, CityPass+).
Todo lo que necesitás del backend para armar la app de la primera entrega.

- **Base URL local:** `http://localhost:8000`
- **Prefijo de la API:** `/api/v1`
- **Documentación viva:** `http://localhost:8000/docs` (OpenAPI, siempre al día)
- **CORS:** ya está habilitado para `http://localhost:5173` (Vite) y `:3000`.
  Si levantás en otro puerto, avisanos y lo agregamos.

---

## 1. Login

Para la Entrega 1 el login es **provisorio**: usuarios fijos en el backend. El
módulo de Login Federado (Grupo 2) todavía no está disponible.

### Endpoint

```http
POST /api/v1/auth/dev/login
Content-Type: application/json

{ "usuario": "vecino1", "password": "vecino1" }
```

**200 OK**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 28800,
  "usuario": {
    "id": "vecino-1",
    "nombre": "Vecina Perez",
    "email": "vecino1@citypass.local",
    "roles": ["ciudadano"]
  }
}
```

**401** si el usuario o la contraseña no coinciden (ver formato de error en §6).

### Usuarios de prueba

| Usuario | Contraseña | Roles | Para qué sirve en la demo |
| --- | --- | --- | --- |
| `vecino1` | `vecino1` | `ciudadano` | Carga reclamos, comenta, adhiere |
| `operador1` | `operador1` | `operador` | Backoffice: cambia estados, asigna |
| `admin1` | `admin1` | `operador`, `admin` | Todo lo anterior + métricas |

También podés pedirlos por API para no duplicar la lista en el front:
`GET /api/v1/auth/dev/usuarios` (devuelve todo menos las contraseñas).

### Cómo usar el token

Guardalo y mandalo en **todos** los requests a `/api/v1`:

```
Authorization: Bearer <access_token>
```

Sin ese header la API responde **401**. Sugerencia: un interceptor de fetch/axios
que lo agregue solo, y que ante un 401 mande de vuelta al login.

> **Importante para la Entrega 2:** este flujo es exactamente el que va a usar el
> login definitivo. Cuando LDAP esté listo, lo único que cambia del lado del
> front es **la URL del login**. El manejo del token, el header y los roles
> quedan igual. No hardcodees los usuarios en el front: pedilos siempre a la API.

---

## 2. Roles y qué ve cada uno

Los roles vienen en `usuario.roles` de la respuesta del login (y también dentro
del JWT, si preferís decodificarlo).

| Rol | Puede |
| --- | --- |
| `ciudadano` | Crear reclamos, ver listado y detalle, comentar, adherir |
| `operador` | Lo anterior + cambiar estados y asignar |
| `admin` | Lo anterior + `GET /reclamos/estadisticas` |

**Ojo con esto:** un `operador` **NO** puede ver las métricas — el backend
devuelve **403**. Es un requisito explícito de la cátedra, así que la pantalla de
métricas tiene que estar oculta en el menú para ciudadano y operador.

Armá las rutas del front según el rol. El backend valida todo del lado del
servidor igual, pero la UI no debería ofrecer algo que va a dar 403.

---

## 3. Endpoints principales

Todos bajo `/api/v1`, todos requieren `Authorization` salvo los de login.

| Método | Ruta | Rol | Qué hace |
| --- | --- | --- | --- |
| `POST` | `/reclamos` | ciudadano | Alta de reclamo |
| `GET` | `/reclamos` | autenticado | Listado paginado, con filtros |
| `GET` | `/reclamos/{id}` | autenticado | Detalle con historial y comentarios |
| `PATCH` | `/reclamos/{id}/estado` | operador | Cambia el estado |
| `POST` | `/reclamos/{id}/comentarios` | autenticado | Comenta |
| `GET` | `/reclamos/{id}/comentarios` | autenticado | Lista comentarios |
| `GET` | `/reclamos/{id}/historial` | autenticado | Trazabilidad de estados |
| `POST` | `/reclamos/{id}/adhesiones` | ciudadano | "A mí también me pasa" |
| `POST` | `/reclamos/clasificacion` | autenticado | Sugerencia del modelo (§4) |
| `GET` | `/reclamos/estadisticas` | **admin** | Métricas agregadas |

### Alta de reclamo

```http
POST /api/v1/reclamos

{
  "titulo": "Luminaria apagada en la plaza",
  "descripcion": "Hace una semana que no funciona el alumbrado de la cuadra.",
  "direccion": "Rivadavia 800",
  "barrio": "Centro",
  "latitud": -34.6037,
  "longitud": -58.3816,
  "fotos": []
}
```

Validaciones: `titulo` entre 5 y 150 caracteres, `descripcion` entre 10 y 5000,
hasta 5 fotos. **`categoria` y `prioridad` son opcionales**: si no los mandás,
los completa el clasificador automático (§4).

### Listado paginado

`GET /reclamos?estado=RECIBIDO&categoria=BACHES&barrio=Centro&page=1&size=20`

Filtros disponibles: `estado`, `categoria`, `prioridad`, `ciudadano_id`,
`asignado_a`, `barrio`, `texto` (busca en título y descripción), `desde`,
`hasta`, `orden`.

La respuesta siempre tiene esta forma:

```json
{ "items": [ ... ], "total": 42, "page": 1, "size": 20 }
```

Cada item del listado es liviano, pensado para tabla y para mapa:

```json
{
  "id": "6f1c9a4e-...",
  "titulo": "Luminaria apagada en la plaza",
  "categoria": "ALUMBRADO",
  "prioridad": "MEDIA",
  "estado": "RECIBIDO",
  "barrio": "Centro",
  "latitud": -34.6037,
  "longitud": -58.3816,
  "adhesiones_count": 3,
  "created_at": "2026-08-20T14:22:31.500Z"
}
```

---

## 4. Autocompletado del formulario con IA

Esto es lo que pidió el profesor: **el vecino escribe el texto y los campos se
completan solos**.

```http
POST /api/v1/reclamos/clasificacion

{ "titulo": "Fuga de gas", "descripcion": "Sale gas de la vereda, huele fuerte" }
```

**200 OK**

```json
{
  "categoria": "AGUA_CLOACAS",
  "prioridad": "CRITICA",
  "confianza": 0.376,
  "evidencia": ["olor", "fuga", "gas", "fuga gas"],
  "modelo": "naive-bayes-corpus-v1"
}
```

**Este endpoint no guarda nada.** Es solo la sugerencia.

### Cómo usarlo en la UI

1. El vecino escribe título y descripción.
2. Al salir del campo descripción (o con un *debounce* de ~500 ms), llamás a
   este endpoint.
3. Pre-seleccionás los combos de categoría y prioridad con lo que devolvió,
   **dejando que el usuario los cambie**.
4. Mostrá la `evidencia` como justificación: *"Detectamos: fuga gas, olor"*. Le
   da confianza al vecino y hace explicable la sugerencia.
5. Si `confianza < 0.5`, presentalo más tibio (*"¿Es esta la categoría?"*) en vez
   de darlo por hecho.

Después, en el `POST /reclamos`, mandá los valores que quedaron en el formulario.
Si el usuario no tocó nada, podés directamente **no mandar** `categoria` ni
`prioridad` y el backend los recalcula.

---

## 5. Vocabulario del dominio

Son los valores exactos que viajan por la API. Los textos que ve el usuario los
definís vos en el front.

**Estados** — `RECIBIDO`, `EN_REVISION`, `ASIGNADO`, `EN_PROCESO`, `RESUELTO`,
`RECHAZADO`, `CERRADO`.

`CERRADO` y `RECHAZADO` son finales: no admiten más cambios.

**Prioridades** — `BAJA`, `MEDIA`, `ALTA`, `CRITICA`. Buen candidato a chip de
color.

**Categorías** — `ALUMBRADO`, `BACHES`, `RESIDUOS`, `ARBOLADO`, `AGUA_CLOACAS`,
`TRANSITO`, `RUIDOS`, `ESPACIOS_PUBLICOS`, `SEGURIDAD`, `OTROS`.

**Transiciones válidas**, para habilitar o deshabilitar los botones del
backoffice:

```
RECIBIDO     -> EN_REVISION, ASIGNADO, RECHAZADO
EN_REVISION  -> RECIBIDO, ASIGNADO, RECHAZADO
ASIGNADO     -> EN_PROCESO, RECHAZADO
EN_PROCESO   -> RESUELTO, ASIGNADO
RESUELTO     -> CERRADO, EN_PROCESO
RECHAZADO    -> (final)
CERRADO      -> (final)
```

Cualquier transición fuera de este mapa devuelve **409** con
`code: "transicion_invalida"`.

---

## 6. Formato de errores

**Todos** los errores de la API usan RFC 7807, con
`Content-Type: application/problem+json`:

```json
{
  "type": "https://citypass.local/errors/transicion_invalida",
  "code": "transicion_invalida",
  "title": "Transicion de estado invalida",
  "status": 409,
  "detail": "No se puede pasar de RESUELTO a ASIGNADO",
  "instance": "/api/v1/reclamos/6f1c.../estado"
}
```

**Usá siempre `code`**, no `title` ni el status: `code` es estable y no cambia si
reescribimos el mensaje.

| `code` | Status | Cuándo |
| --- | --- | --- |
| `reclamo_no_encontrado` | 404 | El id no existe |
| `transicion_invalida` | 409 | Cambio de estado no permitido |
| `adhesion_duplicada` | 409 | Ya adhirió a ese reclamo |
| `adhesion_del_autor` | 422 | Quiso adherir a su propio reclamo |
| `reclamo_cerrado` | 409 | Está cerrado, no admite cambios |
| `permiso_denegado` | 403 | No tiene permisos sobre ese recurso |
| `validacion` | 422 | Campos inválidos — ver abajo |
| `http_401` | 401 | Falta el token o es inválido |
| `http_403` | 403 | El rol no alcanza |

En los errores de validación viene además un array `errors`, listo para pintar
campo por campo:

```json
{
  "code": "validacion",
  "status": 422,
  "errors": [
    {
      "campo": "titulo",
      "mensaje": "String should have at least 5 characters",
      "tipo": "string_too_short"
    }
  ]
}
```

---

## 7. Trazabilidad (opcional, pero suma)

La API acepta y devuelve el header `X-Correlation-Id`. Si el front genera un UUID
por operación y lo manda, podemos seguir esa operación completa por los logs del
backend y de los otros módulos. Si no lo mandás, el backend genera uno y lo
devuelve en la respuesta.

---

## 8. Levantar el backend

```bash
git clone https://github.com/agustin-perez-data/APIS2-G5-RECLAMOS-BACKEND
cd APIS2-G5-RECLAMOS-BACKEND
python -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env          # anda tal cual para desarrollo
alembic upgrade head
uvicorn app.main:app --reload
```

Para la Entrega 1 **no hace falta Kafka**: con `KAFKA_ENABLED=false` en el `.env`
la API levanta sola. Sí hace falta una base; con Docker alcanza
`docker compose up -d postgres`.

Verificá que esté vivo con `GET http://localhost:8000/health`.

---

## 9. Coordinación con los otros equipos

El profesor pidió unificar el look & feel con los frontends de los demás grupos
(formularios, login, navegación). Conviene arrancar esa charla temprano: si el
login termina siendo una pantalla compartida, mejor saberlo antes de construir la
nuestra.

Dudas sobre contratos, campos o códigos de error: preguntá antes de asumir. Si
falta un campo que necesitás para una pantalla, se puede agregar — es mucho más
barato ahora que después de la integración.
