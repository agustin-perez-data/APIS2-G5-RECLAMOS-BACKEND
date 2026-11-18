"""What we register in the bus catalogue has to carry the field defaults.

The gateway decides whether a change is breaking by looking at them: a new
field that brings a `default` keeps the type on its topic, and the same field
without one opens a `.vN` topic and leaves every subscriber behind on the old
version. `ReclamoCreado` already cost us that -- seven teams had to
re-subscribe -- because the translation dropped the defaults on the way out.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
ESQUEMAS = RAIZ / "docs" / "avro"


def _script():
    # `scripts/` is not a package, so it gets loaded by path.
    spec = importlib.util.spec_from_file_location(
        "tipos_gateway", RAIZ / "scripts" / "tipos_gateway.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


ARCHIVOS = sorted(ESQUEMAS.glob("*.avsc"))


@pytest.mark.parametrize("archivo", ARCHIVOS, ids=lambda a: a.stem)
def test_los_campos_opcionales_se_registran_con_su_default(archivo: pathlib.Path) -> None:
    esquema = json.loads(archivo.read_text(encoding="utf-8"))
    campos = {c["name"]: c for c in _script().traducir(esquema)["fields"]}

    for campo in esquema["fields"]:
        if "default" not in campo:
            continue
        registrado = campos[campo["name"]]
        assert "default" in registrado, f"'{campo['name']}' pierde el default al registrarse"
        assert registrado["default"] == campo["default"]


@pytest.mark.parametrize("archivo", ARCHIVOS, ids=lambda a: a.stem)
def test_no_se_inventa_un_default_donde_el_esquema_no_lo_declara(archivo: pathlib.Path) -> None:
    # A default on a required field would tell the gateway it can be left out.
    esquema = json.loads(archivo.read_text(encoding="utf-8"))
    sin_default = {c["name"] for c in esquema["fields"] if "default" not in c}

    for campo in _script().traducir(esquema)["fields"]:
        if campo["name"] in sin_default:
            assert "default" not in campo


def test_el_cuerpo_registrado_declara_los_mismos_campos_que_el_esquema() -> None:
    esquema = json.loads((ESQUEMAS / "ReclamoCreado.avsc").read_text(encoding="utf-8"))
    cuerpo = _script().traducir(esquema)

    assert cuerpo["name"] == "ReclamoCreado"
    assert [c["name"] for c in cuerpo["fields"]] == [c["name"] for c in esquema["fields"]]


def test_un_tipo_que_el_bus_no_acepta_corta_antes_de_registrar() -> None:
    # Finding this out while registering is the expensive moment: the call
    # fails with a 400 whose detail is the gateway's, not ours.
    esquema = {"name": "Inventado", "fields": [{"name": "cuando", "type": "timestamp-millis"}]}

    with pytest.raises(SystemExit, match="no acepta el tipo"):
        _script().traducir(esquema)
