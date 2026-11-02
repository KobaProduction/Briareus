"""Briareus greenfield PostgreSQL connection; no legacy DSN or crypto settings.

Only the deployment-provided POSTGRES_PASSWORD is a required secret. Host,
database name, port and username follow the one selected Compose topology.
No DB connection is opened by constructing the settings or SQLAlchemy metadata.
"""

from __future__ import annotations

from collections.abc import AsyncIterator as AsyncIterator
from collections.abc import Callable
from contextlib import asynccontextmanager as asynccontextmanager
from typing import ClassVar, Literal

from pydantic import Field, SecretStr
from pydantic import field_validator as field_validator
from pydantic import model_validator as model_validator
from sqlalchemy import MetaData
from sqlalchemy import text as text
from sqlalchemy.engine import URL as URL
from sqlalchemy.exc import DBAPIError as DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine as AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker as async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as create_async_engine
from sqlalchemy.orm import DeclarativeBase

from common.platform_errors import Conflict, PersistenceTimeout
from common.settings import ProcessSettings
from service_runtime.platform_db_mechanics import (
    DatabaseRuntime,
    DatabaseSettingsMechanics,
    OwnerDatabaseValidation,
)
from service_runtime.platform_db_mechanics import close_database as close_database
from service_runtime.platform_db_mechanics import connect_database as connect_database
from service_runtime.platform_db_mechanics import database_transaction as database_transaction
from service_runtime.platform_db_mechanics import require_owner_database as require_owner_database


class PlatformDatabaseSettings(DatabaseSettingsMechanics, ProcessSettings):
    """DB-only contract: credentials, topology and no unrelated app options."""

    postgres_host: str = Field("briareus-postgres", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(validation_alias="POSTGRES_DB")
    postgres_user: str = Field(validation_alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")


class PlatformBase(DeclarativeBase):
    metadata = MetaData()


# Separate SQLAlchemy registries: models owned by different logical databases
# must never share one MetaData or rely on a cross-database foreign key.
class IdentityBase(DeclarativeBase):
    metadata = MetaData()


class AccessBase(DeclarativeBase):
    metadata = MetaData()


class ControlBase(DeclarativeBase):
    metadata = MetaData()


class CatalogBase(DeclarativeBase):
    metadata = MetaData()


class FilesBase(DeclarativeBase):
    metadata = MetaData()


class RuntimeBase(DeclarativeBase):
    metadata = MetaData()


class ReverseBase(DeclarativeBase):
    metadata = MetaData()


class IngestBase(DeclarativeBase):
    metadata = MetaData()


OwnerName = Literal[
    "identity", "access", "platform", "resources", "files", "runtime", "reverse", "ingest"
]
OWNER_DB_NAMES: dict[OwnerName, str] = {
    "identity": "briareus_identity",
    "access": "briareus_access",
    "platform": "briareus_platform",
    "resources": "briareus_resources",
    "files": "briareus_files",
    "runtime": "briareus_runtime",
    "reverse": "briareus_reverse",
    "ingest": "briareus_ingest",
}


class OwnerDatabaseSettings(OwnerDatabaseValidation, PlatformDatabaseSettings):
    """Single-owner SQL connection; never accepts an obsolete shared database."""

    owner: OwnerName
    _owner_database_lookup: ClassVar[Callable[[OwnerName], str]] = staticmethod(
        OWNER_DB_NAMES.__getitem__
    )


class PlatformDatabase(DatabaseRuntime[PlatformDatabaseSettings]):
    _conflict_error = Conflict
    _timeout_error = PersistenceTimeout
