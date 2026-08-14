"""Mint a local JWT for development.

The real tokens come from the Federated Login module (Group 2). While that
service is not reachable, this script signs a token with the same shared secret
so the API can be exercised end to end.

    python scripts/dev_token.py --sub vecino-1 --roles ciudadano
    python scripts/dev_token.py --sub operador-1 --roles operador admin
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a development JWT")
    parser.add_argument("--sub", default="vecino-1", help="User id (JWT `sub` claim)")
    parser.add_argument("--roles", nargs="+", default=["ciudadano"], help="Roles to embed")
    parser.add_argument("--horas", type=int, default=8, help="Lifetime in hours")
    args = parser.parse_args()

    if settings.jwt_algorithm != "HS256":
        raise SystemExit(
            f"This script only signs HS256 tokens; JWT_ALGORITHM is {settings.jwt_algorithm}. "
            "Ask Group 2 for a real token instead."
        )

    ahora = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": args.sub,
            "roles": args.roles,
            "email": f"{args.sub}@citypass.local",
            "name": args.sub,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": ahora,
            "exp": ahora + timedelta(hours=args.horas),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )

    print(token)


if __name__ == "__main__":
    main()
