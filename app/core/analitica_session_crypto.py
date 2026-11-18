"""Opaque session identifiers and authenticated encryption of stored JWTs."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import SesionAnaliticaInvalida


def nuevo_identificador() -> str:
    return secrets.token_urlsafe(32)


def hash_identificador(identificador: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", identificador):
        raise SesionAnaliticaInvalida()
    return hashlib.sha256(identificador.encode("ascii")).hexdigest()


class AnaliticaSessionCrypto:
    def __init__(self, clave: str) -> None:
        try:
            self._fernet = Fernet(clave.encode("ascii"))
        except (ValueError, UnicodeError):
            raise ValueError("ANALITICA_SESSION_KEY debe ser una clave Fernet valida") from None

    def cifrar(self, token: str, contexto: str) -> bytes:
        cuerpo = json.dumps({"token": token, "contexto": contexto}).encode("utf-8")
        return self._fernet.encrypt(cuerpo)

    def descifrar(self, cifrado: bytes, contexto: str) -> str:
        try:
            cuerpo = json.loads(self._fernet.decrypt(cifrado))
            if not hmac.compare_digest(cuerpo["contexto"], contexto):
                raise ValueError("Session binding mismatch")
            token = cuerpo["token"]
            if not isinstance(token, str) or not token:
                raise ValueError("Empty token")
            return token
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise SesionAnaliticaInvalida() from None
