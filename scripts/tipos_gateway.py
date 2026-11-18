"""Turn our Avro schemas into what the bus console expects, and print the calls.

The gateway does not take an `.avsc`. It takes `{"name", "fields"}` and builds
the record itself: the namespace comes from the JWT (so a group cannot register
under another's prefix) and `metadata` is added by the bus. Translating by hand
is how a field ends up registered with the wrong type, and a registered type is
a contract six other modules read.

The schemas in `docs/avro/` stay the source of truth -- `tests/unit/
test_schemas_avro.py` already checks them against what `traducir()` actually
sends, so going through them keeps that guarantee instead of bypassing it.

    python scripts/tipos_gateway.py              # print the curl calls
    python scripts/tipos_gateway.py --json       # just the payloads
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ESQUEMAS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "avro"
GATEWAY = "https://test.citypass.mrfranco.net.ar"

# Section 5 of the bus README. A type outside this list is rejected on
# registration, and finding that out while registering is the expensive moment.
SIMPLES = {"string", "int", "long", "float", "double", "boolean", "bytes"}
COMPUESTOS = {"array", "map", "enum", "record", "fixed"}


def _soportado(tipo: Any) -> bool:
    if isinstance(tipo, str):
        return tipo in SIMPLES
    if isinstance(tipo, list):  # union, e.g. ["null", "string"]
        return all(t == "null" or _soportado(t) for t in tipo)
    if isinstance(tipo, dict):
        return tipo.get("type") in COMPUESTOS or tipo.get("type") in SIMPLES
    return False


def traducir(esquema: dict) -> dict:
    """`.avsc` -> the gateway's registration body."""
    campos = []
    for campo in esquema["fields"]:
        if not _soportado(campo["type"]):
            raise SystemExit(
                f"{esquema['name']}.{campo['name']}: el bus no acepta el tipo "
                f"{json.dumps(campo['type'])}"
            )
        # `default` travels: verified against the bus on 2026-11-13. Adding a
        # field that carries one answers `breaking: false` and keeps the type on
        # its topic; the same field without it answers `breaking: true`, opens a
        # `.vN` topic and leaves every subscriber on the old one. That is what
        # `ReclamoCreado` cost us. `doc` is dropped: it is not part of the body.
        traducido = {"name": campo["name"], "type": campo["type"]}
        if "default" in campo:
            traducido["default"] = campo["default"]
        campos.append(traducido)
    return {"name": esquema["name"], "fields": campos}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="solo los payloads")
    args = parser.parse_args()

    archivos = sorted(ESQUEMAS.glob("*.avsc"))
    if not archivos:
        raise SystemExit(f"no hay esquemas en {ESQUEMAS}")

    for archivo in archivos:
        esquema = json.loads(archivo.read_text(encoding="utf-8"))
        cuerpo = traducir(esquema)

        if args.json:
            print(json.dumps(cuerpo, indent=2, ensure_ascii=False))
            continue

        # Compact on one line: these get pasted into a terminal.
        payload = json.dumps(cuerpo, separators=(",", ":"), ensure_ascii=False)

        opcionales = sum(1 for c in cuerpo["fields"] if isinstance(c["type"], list))
        sin_default = [c["name"] for c in cuerpo["fields"] if "default" not in c]
        print(f"# {esquema['namespace']}.{esquema['name']}")
        print(f"#   {len(cuerpo['fields'])} campos, {opcionales} opcionales")
        # Worth seeing before pasting the call: if any of these is new, this
        # registration opens a `.vN` topic and the subscribers stay behind.
        print(f"#   sin default: {', '.join(sin_default) or 'ninguno'}")
        print(f"curl -X POST {GATEWAY}/api/v1/event-types \\")
        print('  -H "Authorization: Bearer $TOKEN" \\')
        print("  -H 'Content-Type: application/json' \\")
        print(f"  -d '{payload}'")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
