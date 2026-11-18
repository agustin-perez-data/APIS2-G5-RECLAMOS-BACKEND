# Analítica de Reclamos: integración con React y despliegue

El backend implementa el contrato del Grupo 8: solicita `GET /embed/reclamos`
con el Bearer humano del administrador y `Accept: text/html`. No utiliza tokens
de servicio ni credenciales de EDA. Operadores y ciudadanos no tienen acceso.
Esta guía describe los endpoints existentes; la conexión con servicios y
credenciales reales debe validarse antes de habilitar producción.

## Endpoints

Todas las rutas siguientes son relativas al **origen HTTPS del frontend**.

| Método y ruta | Credenciales y requisitos | Respuesta correcta |
| --- | --- | --- |
| `POST /api/v1/admin/analitica/sesion` | Bearer humano, `Content-Type: application/json`, cuerpo `{}`, Origin permitido | 200: `usuario_id`, `expires_at`, `estado`, `iframe_url`, `csrf_token`; establece cookie |
| `GET /api/v1/admin/analitica` | Cookie y navegación inicial de iframe del mismo origen; alternativamente Bearer humano para acceso directo | 200: HTML del Grupo 8 |
| `GET /api/v1/admin/analitica/sesion` | Bearer humano y cookie pertenecientes al mismo usuario | 200: `usuario_id`, `expires_at`, `estado: "activa"` |
| `DELETE /api/v1/admin/analitica/sesion` | Origin permitido y `X-CSRF-Token` si hay cookie; no requiere Bearer | 200: `{"revocada": true}`; elimina cookie |

El JWT requiere firma RS256, issuer configurado, expiración válida, audiencia
`citypass-reclamos-api` (también dentro de una lista), `token_use=human`,
`namespace=com.citypass.reclamos` y grupo federado de administrador de Reclamos.
No se exige el claim `module`. Un Authorization explícito inválido nunca se
sustituye por una cookie válida.

## Flujo para React

Usar el token del login federado existente. No obtener el HTML con `fetch` para
insertarlo con `innerHTML`, `srcdoc` o una URL blob: el iframe debe navegar a la
ruta relativa y recibir directamente el HTML y las cabeceras del backend.

Ejemplo mínimo de helpers y componente, para conectar a los controles existentes:

```tsx
const ruta = "/api/v1/admin/analitica";
type Sesion = {
  usuario_id: string;
  expires_at: string;
  estado: string;
  iframe_url: string;
  csrf_token: string;
};

async function iniciar(jwt: string): Promise<Sesion> {
  const r = await fetch(`${ruta}/sesion`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${jwt}`,
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  if (!r.ok) throw new Error(`Analítica: ${r.status}`);
  return r.json();
}

async function revocar(csrf: string) {
  const r = await fetch(`${ruta}/sesion`, {
    method: "DELETE",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "X-CSRF-Token": csrf },
  });
  if (!r.ok) throw new Error(`Cierre de Analítica: ${r.status}`);
}

export function Tablero({ activo }: { activo: boolean }) {
  return activo ? (
    <iframe
      title="Analítica de Reclamos"
      src={ruta}
      sandbox="allow-scripts"
    />
  ) : null;
}
```

En el contenedor React guardar la respuesta de `iniciar` en estado en memoria
(por ejemplo `useState<Sesion | null>(null)`). Mostrar el iframe solamente después
del POST exitoso y comprobar que `usuario_id` corresponda al administrador actual.
No añadir `allow-same-origin`: el documento queda aislado de la página principal.
El backend agrega además su propia CSP `sandbox allow-scripts`.

El contenedor debe serializar los POST, deshabilitar el botón mientras hay una
operación y descartar respuestas de una identidad anterior. Al cambiar usuario,
desmontar primero el iframe, revocar con el CSRF anterior y luego iniciar la
nueva sesión. Coordinar también logout/cambio de usuario entre pestañas: la
cookie se comparte. Un POST rota la cookie previa; no mantener dos arranques
concurrentes. No reintentar automáticamente un 409 en bucle.

Programar un temporizador hasta `expires_at` para desmontar el iframe; limpiar
el temporizador al cambiar sesión o desmontar el componente. La duración máxima
es 300 segundos y nunca supera el JWT. No hay renovación automática: iniciar
otra sesión exige un JWT válido. Revocar la sesión no borra un documento que
ya fue descargado: quitar el iframe también al cerrar sesión. Si falla la
revocación, ocultarlo igualmente y mostrar el error para permitir reintentar;
el backend conserva su vencimiento independiente.

Para consultar estado, usar GET de sesión con `Authorization: Bearer ...`,
`credentials: "same-origin"` y `cache: "no-store"`. No devuelve el CSRF:
tras recargar la página, un nuevo POST permite obtenerlo rotando la sesión.
`estado: activa` verifica la sesión, no acredita disponibilidad del Grupo 8 ni
que el tablero se haya renderizado. `iframe.onload` tampoco acredita éxito;
el padre no puede inspeccionar el documento aislado.

## Cookies, CSRF y errores

El navegador administra `__Secure-citypass_analitica`: identificador opaco,
`Secure; HttpOnly; SameSite=Strict; Path=/api/v1/admin/analitica`, sin Domain.
Nunca contiene el JWT. JavaScript no debe leerla ni copiarla. PostgreSQL guarda
solo el hash del identificador y el JWT cifrado con Fernet.

POST y DELETE exigen un `Origin` exacto de `ANALITICA_FRONTEND_ORIGINS`; si viene
`Sec-Fetch-Site`, debe ser `same-origin`. El navegador los genera: no simularlos
desde React. POST exige JSON y Bearer; DELETE exige el CSRF devuelto por POST
cuando hay cookie. Sin cookie, DELETE es idempotente. GET del iframe con cookie
exige Fetch Metadata `same-origin`, `iframe`, `navigate`. No sirve abrir esa URL
en una pestaña ni usar un iframe dirigido al dominio separado del backend.

Las respuestas incluyen `Cache-Control: no-store`. En HTML se conservan los
bytes y las cabeceras recibidas admitidas por el proxy: `Content-Type`,
`Cache-Control`, `Content-Security-Policy`, `X-Content-Type-Options` y
`Referrer-Policy`. Se exige `Content-Type: text/html`; las otras cabeceras
pueden faltar sin provocar rechazo. Se agrega no-store cuando falta esa
directiva. No quitar cabeceras en el proxy inverso.

| Estado | Manejo esperado |
| --- | --- |
| 401 | Credencial/sesión ausente, inválida o vencida; ocultar iframe y permitir iniciar sesión nuevamente con JWT válido |
| 403 | Permisos, namespace, Origin, CSRF o navegación rechazados; también puede provenir del Grupo 8 |
| 409 | Identidad distinta o conflicto de rotación; detener operaciones concurrentes y reconciliar el usuario actual |
| 400 / 415 | Cookie ambigua / falta Content-Type JSON en POST |
| 502 / 503 / 504 | Fallo remoto / indisponibilidad o sesiones sin configurar / timeout; mostrar reintento controlado |
| 404 | Con Analítica deshabilitada sus rutas no se montan |

Los errores controlados usan `application/problem+json`; no incluir tokens,
CSRF ni identificadores de sesión en URLs, HTML, mensajes o logs. No interpretar
un 401 de la sesión temporal como logout obligatorio del login general.

## Configuración y responsabilidades de DevOps

`render.yaml` mantiene Analítica deshabilitada hasta completar el despliegue.
No cambia EDA, Kafka ni la autenticación general.

| Variable | Valor declarado / requisito |
| --- | --- |
| `ANALITICA_ENABLED` | `false`; activar explícitamente tras configurar y comprobar el flujo |
| `ANALITICA_URL` | `https://citypass-backend-prod-becqetepcjbqa8c7.brazilsouth-01.azurewebsites.net`, base del contrato del Grupo 8; confirmar disponibilidad |
| `ANALITICA_TIMEOUT_SECONDS` | `10`, timeout de la consulta al Grupo 8 |
| `ANALITICA_SESSION_TTL_SECONDS` | `300`; rango permitido 1–300, limitado además por JWT |
| `ANALITICA_SESSION_KEY` | Secreto Fernet exclusivo, `sync: false`; mismo valor en todos los procesos |
| `ANALITICA_FRONTEND_ORIGINS` | JSON de orígenes exactos HTTPS, sin ruta ni barra final; Render declara el origen ya registrado `https://reclamos-frontend-g5.vercel.app`; confirmar despliegue efectivo |

Generar la clave en un entorno privado con la herramienta ya instalada:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Cargarla directamente como secreto de Render, nunca en Git ni logs de CI.
Provisionarla **antes** de aplicar la reconciliación de `render.yaml`: el control
de configuración detecta secretos declarados ausentes incluso si la función
está deshabilitada. Cambiar esta clave invalida sesiones y CSRF existentes;
coordinar el reinicio de todos los procesos y el nuevo inicio de sesión.
Sin clave válida las operaciones de sesión devuelven 503; con lista de orígenes
vacía los POST son rechazados. El healthcheck general no acredita este flujo.

Aplicar las migraciones existentes (`alembic upgrade head`), incluida
`0014_sesiones_analitica.py` y sus políticas RLS, sobre el PostgreSQL compartido de
la API. La limpieza periódica de expiradas ya está implementada (cada 60 s
cuando Analítica y su clave están configuradas); no requiere un cron nuevo.
La expiración se comprueba al acceder, sin esperar la limpieza.

Conservar la configuración federada de producción: `AUTH_ENABLED=true`,
`AUTH_DEV_LOGIN_ENABLED=false`, RS256, JWKS e issuer del Grupo 2,
`JWT_AUDIENCE=citypass-reclamos-api`, `JWT_ROLES_CLAIM=groups`,
`JWT_TOKEN_USE_ESPERADO=human`, `JWT_STAFF_ESTRICTO=true` y grupos administrativos
acordados. No reutilizar secretos de EDA para Analítica.

El frontend y Render tienen dominios distintos en la configuración registrada.
DevOps debe publicar `/api/v1/admin/analitica` y `/api/v1/admin/analitica/sesion`
**bajo el origen HTTPS del frontend**, reenviándolos al backend sin cambiar
ruta, métodos, Authorization, Origin, Cookie, Set-Cookie, X-CSRF-Token ni Fetch
Metadata. Configurar el proxy/rewrite real del hosting (por ejemplo Vercel) sin
cachear respuestas, sin convertirlas en HTML del SPA y sin reescribir Domain
de la cookie. No basta con habilitar CORS ni `credentials: include` hacia Render.
La CSP de la página principal debe permitir `frame-src 'self'`; conservar las
CSP de la respuesta embebida. No se requiere alojar React y FastAPI juntos.

## Comprobación con los servicios reales

1. DevOps confirma proxy HTTPS, secretos, migración y origen efectivo; luego
   habilita Analítica mediante la configuración versionada y despliega.
2. Grupo 2 proporciona un acceso de administrador real y confirma sus claims;
   Grupo 8 confirma URL, disponibilidad de `/embed/reclamos`, aceptación de ese
   JWT, HTML autocontenido y cabeceras del contrato. No hay credenciales de
   servicio adicionales que registrar en este flujo.
3. Frontend implementa los controles anteriores sin cambiar el login existente.
   En DevTools comprobar POST, atributos de cookie, iframe con URL relativa y
   sandbox exacto; consultar estado, esperar vencimiento y probar cierre y cambio
   de usuario. No exportar HAR con credenciales.
4. Verificar rechazo de operador/ciudadano y ausencia de mezcla de sesiones en
   pestañas concurrentes; comprobar HTML y cabeceras del Grupo 8 y ausencia de
   caché en proxy/hosting. Validar en los navegadores objetivo, especialmente
   Safari/WebKit: las pruebas locales anteriores no acreditan todo navegador
   ni la topología de producción.

El backend y sus pruebas automatizadas están implementados; la configuración
queda lista para revisión. La habilitación y la aceptación de extremo a extremo
dependen del proxy del frontend, credenciales federadas y servicio real del
Grupo 8. Esta etapa no incorpora cambios al repositorio React ni valida esos
servicios externos.
