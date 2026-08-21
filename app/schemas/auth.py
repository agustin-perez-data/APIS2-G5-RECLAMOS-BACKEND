"""DTOs of the development login.

Field descriptions stay in Spanish: they end up in the OpenAPI page the front
end reads. The response shape deliberately mirrors what Group 2's Federated
Login will return, so a client written against this stub keeps working against
the real issuer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginPedido(BaseModel):
    usuario: str = Field(description="Nombre de usuario de prueba", examples=["vecino1"])
    password: str = Field(description="Contrasena del usuario de prueba")


class UsuarioOut(BaseModel):
    """Identity behind the token, so the front end does not have to decode it."""

    id: str = Field(description="Identificador del usuario (claim `sub` del JWT)")
    nombre: str
    email: str
    roles: list[str] = Field(description="Roles del usuario dentro del modulo")


class TokenOut(BaseModel):
    """OAuth2-flavoured response: the same shape the real issuer will use."""

    access_token: str = Field(description="JWT a enviar en el header Authorization")
    token_type: str = Field(default="bearer", description="Siempre `bearer`")
    expires_in: int = Field(description="Segundos hasta el vencimiento del token")
    usuario: UsuarioOut
