"""Reusable column types."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def enum_column(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Persist an enum as VARCHAR rather than a native Postgres type.

    A native ENUM forces an ALTER TYPE on every migration and does not exist in
    SQLite (which the test suite uses). With `native_enum=False` the same model
    runs on both engines and adding a category needs no migration.

    Validation lives in the application layer: `validate_strings=True` in the
    ORM, plus the Pydantic enums at the HTTP edge and in the event contracts.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [miembro.value for miembro in e],
        validate_strings=True,
    )
