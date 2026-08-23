"""Connection configuration for ExaDoctor.

Credentials are read from environment variables only. ExaDoctor never
persists credentials to disk or accepts them as CLI arguments (which would
leak into shell history and process listings).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from exadoctor.errors import ConfigurationError

HOST_VAR = "EXADOCTOR_HOST"
PORT_VAR = "EXADOCTOR_PORT"
USER_VAR = "EXADOCTOR_USER"
PASSWORD_VAR = "EXADOCTOR_PASSWORD"
SCHEMA_VAR = "EXADOCTOR_SCHEMA"
ENCRYPTION_VAR = "EXADOCTOR_ENCRYPTION"
TLS_INSECURE_VAR = "EXADOCTOR_TLS_INSECURE"

DEFAULT_PORT = 8563


@dataclass(frozen=True)
class ConnectionConfig:
    host: str
    port: int
    user: str
    password: str
    schema: str | None = None
    encryption: bool = True
    # Skips TLS certificate verification. Off by default; only meant for a
    # known local/dev instance with a self-signed certificate (e.g. Exasol
    # Docker-DB) -- never for a real deployment target.
    tls_insecure: bool = False

    def __repr__(self) -> str:
        return (
            f"ConnectionConfig(host={self.host!r}, port={self.port!r}, "
            f"user={self.user!r}, password='***', schema={self.schema!r}, "
            f"encryption={self.encryption!r}, tls_insecure={self.tls_insecure!r})"
        )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ConnectionConfig:
        env = env if env is not None else os.environ

        missing = [name for name in (HOST_VAR, USER_VAR, PASSWORD_VAR) if not env.get(name)]
        if missing:
            raise ConfigurationError(
                "Missing required connection settings: "
                f"{', '.join(missing)}. Set them as environment variables; "
                "ExaDoctor does not read credentials from files or CLI flags."
            )

        port_raw = env.get(PORT_VAR, str(DEFAULT_PORT))
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ConfigurationError(f"{PORT_VAR} must be an integer, got {port_raw!r}.") from exc

        encryption_raw = env.get(ENCRYPTION_VAR, "true").strip().lower()
        encryption = encryption_raw not in {"0", "false", "no"}

        tls_insecure_raw = env.get(TLS_INSECURE_VAR, "false").strip().lower()
        tls_insecure = tls_insecure_raw in {"1", "true", "yes"}

        return cls(
            host=env[HOST_VAR],
            port=port,
            user=env[USER_VAR],
            password=env[PASSWORD_VAR],
            schema=env.get(SCHEMA_VAR) or None,
            encryption=encryption,
            tls_insecure=tls_insecure,
        )
