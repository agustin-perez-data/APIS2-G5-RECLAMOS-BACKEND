"""Analytics authorization stays strict without changing other JWT consumers."""

from __future__ import annotations

import pytest

from app.core.analitica_auth import autenticar_admin_analitica
from app.core.exceptions import AnaliticaAccesoDenegado
from app.core.security import TokenInvalido
from tests.analitica_helpers import entorno_federado, firmar


@pytest.mark.parametrize(
    "cambio",
    [
        {"auth_enabled": False},
        {"jwt_algorithm": "HS256"},
        {"jwt_staff_estricto": False},
        {"jwt_roles_claim": "roles"},
        {"jwt_audience": "otra-api"},
        {"jwt_issuer": None},
        {"jwt_jwks_url": None},
        {"jwt_staff_grupos_admin": []},
    ],
)
def test_no_acepta_configuracion_relajada(monkeypatch, cambio: dict) -> None:
    cfg, clave = entorno_federado(monkeypatch)
    with pytest.raises(TokenInvalido):
        autenticar_admin_analitica(firmar(cfg, clave), cfg.model_copy(update=cambio))


def test_exige_human_aunque_el_validador_general_no_lo_exija(monkeypatch) -> None:
    cfg, clave = entorno_federado(monkeypatch)
    relajada = cfg.model_copy(update={"jwt_token_use_esperado": None})
    with pytest.raises(TokenInvalido):
        autenticar_admin_analitica(firmar(cfg, clave, token_use="service"), relajada)


def test_no_usa_el_module_como_sustituto_del_namespace(monkeypatch) -> None:
    cfg, clave = entorno_federado(monkeypatch)
    token = firmar(cfg, clave, namespace=None, module="reclamos")
    with pytest.raises(AnaliticaAccesoDenegado):
        autenticar_admin_analitica(token, cfg)


def test_no_usa_roles_alternativos_si_faltan_los_grupos_ldap(monkeypatch) -> None:
    cfg, clave = entorno_federado(monkeypatch)
    token = firmar(cfg, clave, groups=None, realm_access={"roles": ["reclamos-administradores"]})
    with pytest.raises(AnaliticaAccesoDenegado):
        autenticar_admin_analitica(token, cfg)
