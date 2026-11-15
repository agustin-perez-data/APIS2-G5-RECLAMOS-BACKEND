"""Keep the Render service in line with `render.yaml` (ADR 0021).

    python scripts/render_config.py verificar   # compare, exit 1 on any difference
    python scripts/render_config.py aplicar     # write the public values, then deploy

Reads RENDER_API_KEY and RENDER_SERVICE_ID from the environment.

What it does and what it refuses to do:

- A variable declared with `value` is public configuration. `aplicar` writes it
  to Render when it differs; `verificar` reports it.
- A variable declared with `sync: false` is a secret. Only its presence is
  checked. Its value is never compared, written or printed.
- It never deletes anything. A variable that exists in Render and is not in the
  file is reported as drift for a person to decide: deleting a secret by
  accident is not something to automate.
- It prints names only, never values: the logs of a public repository are public.

The comparison is pure and lives apart from the HTTP calls so it can be tested
without a Render account.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

API = "https://api.render.com/v1"
ARCHIVO = Path(__file__).resolve().parent.parent / "render.yaml"

# Deploy states that will not change any more.
DEPLOY_FALLIDO = frozenset(
    {"build_failed", "update_failed", "pre_deploy_failed", "canceled", "deactivated"}
)

# Service settings compared against the file: name in render.yaml -> where the
# Render API reports it.
AJUSTES_DEL_SERVICIO: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "repo": ("repo",),
    "branch": ("branch",),
    "runtime": ("serviceDetails", "runtime"),
    "plan": ("serviceDetails", "plan"),
    "region": ("serviceDetails", "region"),
    "healthCheckPath": ("serviceDetails", "healthCheckPath"),
    "dockerfilePath": ("serviceDetails", "envSpecificDetails", "dockerfilePath"),
    "dockerContext": ("serviceDetails", "envSpecificDetails", "dockerContext"),
}


@dataclass(frozen=True, slots=True)
class Declarado:
    """What `render.yaml` says about the service."""

    ajustes: dict[str, str]
    publicas: dict[str, str]
    secretas: frozenset[str]
    auto_deploy: bool

    @property
    def claves(self) -> frozenset[str]:
        return frozenset(self.publicas) | self.secretas


@dataclass(slots=True)
class Diferencias:
    """Everything that separates Render from the file. Names only."""

    a_escribir: dict[str, str] = field(default_factory=dict)
    secretas_ausentes: list[str] = field(default_factory=list)
    sobran: list[str] = field(default_factory=list)
    ajustes: list[str] = field(default_factory=list)

    @property
    def hay(self) -> bool:
        return bool(self.a_escribir or self.secretas_ausentes or self.sobran or self.ajustes)

    @property
    def sin_arreglo_automatico(self) -> bool:
        """Differences `aplicar` does not fix: they need a person."""
        return bool(self.secretas_ausentes or self.sobran or self.ajustes)


def leer_declarado(texto: str) -> Declarado:
    """Parse `render.yaml`. Exactly one service is expected."""
    documento = yaml.safe_load(texto)
    servicios = (documento or {}).get("services") or []
    if len(servicios) != 1:
        raise ValueError(f"render.yaml tiene que declarar un servicio y declara {len(servicios)}")
    servicio = servicios[0]

    publicas: dict[str, str] = {}
    secretas: set[str] = set()
    for variable in servicio.get("envVars") or []:
        clave = variable["key"]
        if clave in publicas or clave in secretas:
            raise ValueError(f"render.yaml declara dos veces la variable {clave}")
        if "value" in variable:
            if variable.get("sync") is False:
                raise ValueError(f"{clave} tiene `value` y `sync: false` a la vez")
            # YAML reads `true` and `12` as bool and int; Render stores text.
            if not isinstance(variable["value"], str):
                raise ValueError(
                    f"el valor de {clave} tiene que ir entre comillas para que sea texto"
                )
            publicas[clave] = variable["value"]
        elif variable.get("sync") is False:
            secretas.add(clave)
        else:
            raise ValueError(f"{clave} no tiene ni `value` ni `sync: false`")

    disparador = servicio.get("autoDeployTrigger", "commit")
    return Declarado(
        ajustes={k: str(servicio[k]) for k in AJUSTES_DEL_SERVICIO if k in servicio},
        publicas=publicas,
        secretas=frozenset(secretas),
        auto_deploy=disparador != "off",
    )


def _en(servicio: dict[str, Any], camino: tuple[str, ...]) -> str | None:
    actual: Any = servicio
    for paso in camino:
        if not isinstance(actual, dict):
            return None
        actual = actual.get(paso)
    return None if actual is None else str(actual)


def comparar(
    declarado: Declarado, servicio: dict[str, Any], variables: dict[str, str]
) -> Diferencias:
    """Diff the file against what Render reports."""
    dif = Diferencias()

    for clave, valor in declarado.publicas.items():
        if variables.get(clave) != valor:
            dif.a_escribir[clave] = valor
    dif.secretas_ausentes = sorted(c for c in declarado.secretas if not variables.get(c))
    dif.sobran = sorted(set(variables) - declarado.claves)

    for nombre, camino in AJUSTES_DEL_SERVICIO.items():
        if nombre in declarado.ajustes and _en(servicio, camino) != declarado.ajustes[nombre]:
            dif.ajustes.append(nombre)
    if (servicio.get("autoDeploy") == "yes") != declarado.auto_deploy:
        dif.ajustes.append("autoDeployTrigger")
    return dif


def informe(dif: Diferencias) -> list[str]:
    """Human-readable lines. Names only, by design."""
    if not dif.hay:
        return ["Render coincide con render.yaml."]
    lineas = []
    for clave in sorted(dif.a_escribir):
        lineas.append(f"valor distinto del declarado: {clave}")
    for clave in dif.secretas_ausentes:
        lineas.append(f"secreto declarado que falta en Render: {clave}")
    for clave in dif.sobran:
        lineas.append(f"variable en Render que no esta en render.yaml: {clave}")
    for nombre in dif.ajustes:
        lineas.append(f"ajuste del servicio distinto del declarado: {nombre}")
    return lineas


class Render:
    """The handful of Render API calls this needs."""

    def __init__(self, api_key: str, servicio: str) -> None:
        self._api_key = api_key
        self._base = f"{API}/services/{urllib.parse.quote(servicio, safe='')}"

    def _pedir(self, metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None) -> Any:
        pedido = urllib.request.Request(  # noqa: S310 - fixed https host
            self._base + ruta,
            data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
            method=metodo,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(pedido, timeout=60) as respuesta:  # noqa: S310
                contenido = respuesta.read()
        except urllib.error.HTTPError as exc:
            # The body may echo what was sent, so it is deliberately not shown.
            raise RuntimeError(f"Render respondio {exc.code} a {metodo} {ruta}") from None
        return json.loads(contenido) if contenido else None

    def servicio(self) -> dict[str, Any]:
        return self._pedir("GET", "")

    def variables(self) -> dict[str, str]:
        todas: dict[str, str] = {}
        cursor = ""
        while True:
            pagina = self._pedir("GET", f"/env-vars?limit=100{cursor}")
            if not pagina:
                return todas
            for item in pagina:
                todas[item["envVar"]["key"]] = item["envVar"]["value"]
            cursor = "&cursor=" + urllib.parse.quote(pagina[-1]["cursor"], safe="")

    def escribir(self, clave: str, valor: str) -> None:
        # One variable at a time. The bulk endpoint (PUT /env-vars) replaces the
        # whole set with whatever is sent and would wipe every secret.
        self._pedir("PUT", f"/env-vars/{urllib.parse.quote(clave, safe='')}", {"value": valor})

    def desplegar(self, espera_segundos: int = 600) -> str:
        """Trigger a deploy and wait for it. Returns the final status."""
        deploy = self._pedir("POST", "/deploys", {})["id"]
        limite = time.monotonic() + espera_segundos
        estado = "created"
        while time.monotonic() < limite:
            estado = self._pedir("GET", f"/deploys/{deploy}")["status"]
            print(f"  deploy {deploy}: {estado}")
            if estado == "live" or estado in DEPLOY_FALLIDO:
                return estado
            time.sleep(10)
        return estado


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"verificar", "aplicar"}:
        print(__doc__)
        return 2
    api_key = os.environ.get("RENDER_API_KEY", "")
    servicio_id = os.environ.get("RENDER_SERVICE_ID", "")
    if not api_key or not servicio_id:
        print("Faltan RENDER_API_KEY o RENDER_SERVICE_ID")
        return 2

    declarado = leer_declarado(ARCHIVO.read_text(encoding="utf-8"))
    render = Render(api_key, servicio_id)
    dif = comparar(declarado, render.servicio(), render.variables())
    for linea in informe(dif):
        print(linea)

    if argv[1] == "verificar":
        return 1 if dif.hay else 0

    if dif.a_escribir:
        for clave, valor in sorted(dif.a_escribir.items()):
            render.escribir(clave, valor)
            print(f"escrita: {clave}")
        # Writing a variable through the API does not restart the service.
        estado = render.desplegar()
        if estado != "live":
            print(f"El deploy termino en {estado}")
            return 1
    # What is left needs a person; say so with a red run instead of hiding it.
    return 1 if dif.sin_arreglo_automatico else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
