"""Password hashing for the citizens this module authenticates.

Uses `hashlib.scrypt` from the standard library: it is memory-hard, OWASP lists
it as an acceptable alternative to Argon2id, and it keeps the dependency list
untouched (see ADR 0011 and the rule in `CLAUDE.md`).

The hash is stored self-describing:

    scrypt$n=16384,r=8,p=1$<salt b64>$<hash b64>

which is what makes the choice reversible. Moving to Argon2 later means adding a
prefix to `verificar_password` and rehashing on the next successful login: no
data migration and no mass password reset.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Tuned for roughly 100-250 ms per hash. Worth timing on the real deploy: too
# fast is cheap to attack, too slow is a denial of service on ourselves.
N = 2**14
R = 8
P = 1
LARGO_CLAVE = 32
LARGO_SALT = 16
# scrypt needs about 128 * N * r bytes; the default ceiling is far below that.
MAX_MEMORIA = 64 * 1024 * 1024

_ETIQUETA = "scrypt"


def _b64(crudo: bytes) -> str:
    return base64.b64encode(crudo).decode("ascii")


def hash_password(password: str, *, n: int = N, r: int = R, p: int = P) -> str:
    """Hash a password into the self-describing format described above."""
    salt = secrets.token_bytes(LARGO_SALT)
    derivada = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=LARGO_CLAVE, maxmem=MAX_MEMORIA
    )
    return f"{_ETIQUETA}$n={n},r={r},p={p}${_b64(salt)}${_b64(derivada)}"


def _partes(almacenado: str) -> tuple[dict[str, int], bytes, bytes] | None:
    """Split a stored hash, or None when it is not one we can read."""
    try:
        etiqueta, parametros, salt_b64, hash_b64 = almacenado.split("$")
        if etiqueta != _ETIQUETA:
            return None
        valores = {
            clave: int(valor) for clave, valor in (par.split("=") for par in parametros.split(","))
        }
        if not {"n", "r", "p"} <= valores.keys():
            return None
        return valores, base64.b64decode(salt_b64), base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return None


def verificar_password(password: str, almacenado: str) -> bool:
    """Check a password against a stored hash.

    An unreadable hash is a failed login, never an exception: a corrupted row
    must not turn into a 500.
    """
    partes = _partes(almacenado)
    if partes is None:
        return False
    parametros, salt, esperado = partes
    try:
        derivada = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=parametros["n"],
            r=parametros["r"],
            p=parametros["p"],
            dklen=len(esperado) or LARGO_CLAVE,
            maxmem=MAX_MEMORIA,
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(derivada, esperado)


def necesita_rehash(almacenado: str) -> bool:
    """True when the stored hash was made with parameters we no longer use.

    The service calls this on a successful login, which is the only moment the
    plain password is available. That is what makes raising the cost later, or
    switching algorithms, free.
    """
    partes = _partes(almacenado)
    if partes is None:
        return True
    parametros, _, _ = partes
    return (parametros["n"], parametros["r"], parametros["p"]) != (N, R, P)
