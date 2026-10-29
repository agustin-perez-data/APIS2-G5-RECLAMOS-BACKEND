"""DTOs of both logins: the development stand-in and the citizens one.

Field descriptions stay in Spanish: they end up in the OpenAPI page the front
end reads. The response shape deliberately mirrors what Group 2's Federated
Login will return, so a client written against this stub keeps working against
the real issuer.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


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


class RegistroCiudadano(BaseModel):
    """What a neighbour sends to open an account."""

    email: EmailStr = Field(description="Correo del vecino; tambien es su usuario")
    # No composition rules: NIST 800-63B advises against them, length is what
    # matters. The ceiling bounds the cost of hashing an attacker's input.
    password: str = Field(min_length=10, max_length=128, description="Minimo 10 caracteres")
    nombre: str = Field(min_length=2, max_length=120, description="Nombre para mostrar")


class LoginCiudadano(BaseModel):
    email: EmailStr = Field(description="Correo con el que se registro")
    password: str = Field(max_length=128)
