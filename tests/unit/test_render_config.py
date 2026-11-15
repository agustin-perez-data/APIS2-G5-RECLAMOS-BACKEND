"""`render.yaml` and the script that keeps Render in line with it (ADR 0021).

Two kinds of test: the comparison logic, and the file itself. The second kind
is what makes the file trustworthy as documentation: a variable the application
does not know, a secret written in clear text or a configuration that would not
boot in production fails here, before it reaches Render.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core.config import Settings

RAIZ = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "render_config", RAIZ / "scripts" / "render_config.py"
)
render_config = importlib.util.module_from_spec(_spec)
# Registered before executing: dataclasses with slots look their module up.
import sys  # noqa: E402

sys.modules["render_config"] = render_config
_spec.loader.exec_module(render_config)

YAML_MINIMO = """
services:
  - type: web
    name: api
    plan: free
    region: oregon
    branch: main
    healthCheckPath: /health/ready
    autoDeployTrigger: "off"
    envVars:
      - key: ENVIRONMENT
        value: production
      - key: DEBUG
        value: "false"
      - key: DATABASE_URL
        sync: false
"""

SERVICIO = {
    "name": "api",
    "branch": "main",
    "autoDeploy": "no",
    "serviceDetails": {"plan": "free", "region": "oregon", "healthCheckPath": "/health/ready"},
}


def _declarado():
    return render_config.leer_declarado(YAML_MINIMO)


# --- Reading the file ----------------------------------------------------------


def test_separa_las_variables_publicas_de_los_secretos():
    declarado = _declarado()

    assert declarado.publicas == {"ENVIRONMENT": "production", "DEBUG": "false"}
    assert declarado.secretas == {"DATABASE_URL"}
    assert declarado.auto_deploy is False


@pytest.mark.parametrize(
    ("variable", "mensaje"),
    [
        ("- key: DB_ECHO\n        value: false", "entre comillas"),
        ("- key: ENVIRONMENT\n        value: otra", "dos veces"),
        ("- key: SUELTA", "ni `value` ni `sync: false`"),
        ('- key: AMBAS\n        value: "x"\n        sync: false', "a la vez"),
    ],
)
def test_rechaza_un_archivo_mal_escrito(variable, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        render_config.leer_declarado(YAML_MINIMO + "      " + variable + "\n")


def test_exige_un_solo_servicio():
    with pytest.raises(ValueError, match="un servicio"):
        render_config.leer_declarado("services: []")


# --- Comparing -----------------------------------------------------------------


def test_sin_diferencias_cuando_render_coincide():
    variables = {"ENVIRONMENT": "production", "DEBUG": "false", "DATABASE_URL": "postgres://x"}

    dif = render_config.comparar(_declarado(), SERVICIO, variables)

    assert not dif.hay
    assert render_config.informe(dif) == ["Render coincide con render.yaml."]


def test_un_valor_publico_distinto_o_ausente_se_escribe():
    variables = {"ENVIRONMENT": "dev", "DATABASE_URL": "postgres://x"}

    dif = render_config.comparar(_declarado(), SERVICIO, variables)

    assert dif.a_escribir == {"ENVIRONMENT": "production", "DEBUG": "false"}
    assert not dif.sin_arreglo_automatico


def test_un_secreto_ausente_y_una_variable_de_mas_necesitan_a_una_persona():
    variables = {"ENVIRONMENT": "production", "DEBUG": "false", "VIEJA": "algo"}

    dif = render_config.comparar(_declarado(), SERVICIO, variables)

    assert dif.secretas_ausentes == ["DATABASE_URL"]
    assert dif.sobran == ["VIEJA"]
    assert not dif.a_escribir
    assert dif.sin_arreglo_automatico


def test_detecta_un_ajuste_del_servicio_cambiado_a_mano():
    servicio = {**SERVICIO, "autoDeploy": "yes"}
    servicio["serviceDetails"] = {**SERVICIO["serviceDetails"], "healthCheckPath": "/health"}
    variables = {"ENVIRONMENT": "production", "DEBUG": "false", "DATABASE_URL": "postgres://x"}

    dif = render_config.comparar(_declarado(), servicio, variables)

    assert dif.ajustes == ["healthCheckPath", "autoDeployTrigger"]


def test_el_informe_nunca_muestra_un_valor():
    """The logs of a public repository are public: names only."""
    variables = {"ENVIRONMENT": "valor-viejo", "DEBUG": "false", "CLAVE_DE_MAS": "s3cr3t0"}

    lineas = "\n".join(
        render_config.informe(render_config.comparar(_declarado(), SERVICIO, variables))
    )

    assert "ENVIRONMENT" in lineas and "CLAVE_DE_MAS" in lineas and "DATABASE_URL" in lineas
    for valor in ("valor-viejo", "s3cr3t0", "production"):
        assert valor not in lineas


# --- The real file -------------------------------------------------------------


@pytest.fixture(scope="module")
def real():
    return render_config.leer_declarado((RAIZ / "render.yaml").read_text(encoding="utf-8"))


def test_cada_variable_declarada_es_un_ajuste_que_la_aplicacion_conoce(real):
    conocidas = {nombre.upper() for nombre in Settings.model_fields}

    assert real.claves - conocidas == set()


def test_ningun_secreto_esta_escrito_en_el_archivo(real):
    sospechosas = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "DATABASE_URL", "EMAIL")

    # An address and the name of a claim: they contain the word, not a credential.
    no_son_credenciales = {"GATEWAY_TOKEN_URL", "JWT_TOKEN_USE_ESPERADO"}

    en_claro = [
        clave
        for clave in real.publicas
        if any(parte in clave for parte in sospechosas) and clave not in no_son_credenciales
    ]

    assert en_claro == []
    assert {"DATABASE_URL", "JWT_CIUDADANOS_SECRET", "GATEWAY_WEBHOOK_TOKEN"} <= real.secretas


def test_la_configuracion_declarada_arranca_en_produccion(real, monkeypatch):
    """The public values, plus stand-ins for the secrets, must pass every
    start-up validation. A change to render.yaml that would leave the service
    unable to boot fails here instead of in a deploy.

    They go in as environment variables, the way Render hands them over, so
    the lists are parsed exactly as in production."""
    for clave, valor in real.publicas.items():
        monkeypatch.setenv(clave, valor)
    for clave in real.secretas:
        monkeypatch.setenv(clave, "valor-de-prueba-que-no-es-el-de-ejemplo")
    # JIRA_URL is a secret here, and it has to look like an address.
    monkeypatch.setenv("JIRA_URL", "https://ejemplo.atlassian.net")

    cfg = Settings(_env_file=None)

    assert cfg.environment == "production"
    assert not cfg.is_local
    assert cfg.auth_dev_login_enabled is False
    assert cfg.jwt_staff_estricto is True
    assert cfg.jwt_staff_grupos_admin == ["reclamos-administradores"]
    assert "https://reclamos-frontend-g5.vercel.app" in cfg.cors_origins


def test_el_servicio_declarado_no_se_despliega_solo(real):
    """The CD workflow deploys, after the migrations. Render must not."""
    assert real.auto_deploy is False
    assert real.ajustes["healthCheckPath"] == "/health/ready"
    assert real.ajustes["branch"] == "main"
