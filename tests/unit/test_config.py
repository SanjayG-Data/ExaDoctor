import pytest

from exadoctor.connection.config import ConnectionConfig
from exadoctor.errors import ConfigurationError

VALID_ENV = {
    "EXADOCTOR_HOST": "exasol.example.com",
    "EXADOCTOR_USER": "test_user",
    "EXADOCTOR_PASSWORD": "hunter2",
}


def test_from_env_applies_defaults() -> None:
    config = ConnectionConfig.from_env(dict(VALID_ENV))
    assert config.host == "exasol.example.com"
    assert config.port == 8563
    assert config.user == "test_user"
    assert config.password == "hunter2"
    assert config.schema is None
    assert config.encryption is True
    assert config.tls_insecure is False


def test_from_env_reads_tls_insecure_opt_out() -> None:
    config = ConnectionConfig.from_env(dict(VALID_ENV, EXADOCTOR_TLS_INSECURE="true"))
    assert config.tls_insecure is True


def test_from_env_reads_optional_settings() -> None:
    env = dict(VALID_ENV, EXADOCTOR_PORT="8888", EXADOCTOR_SCHEMA="MY_SCHEMA", EXADOCTOR_ENCRYPTION="false")
    config = ConnectionConfig.from_env(env)
    assert config.port == 8888
    assert config.schema == "MY_SCHEMA"
    assert config.encryption is False


@pytest.mark.parametrize("missing_key", ["EXADOCTOR_HOST", "EXADOCTOR_USER", "EXADOCTOR_PASSWORD"])
def test_from_env_raises_on_missing_required_setting(missing_key: str) -> None:
    env = dict(VALID_ENV)
    del env[missing_key]
    with pytest.raises(ConfigurationError):
        ConnectionConfig.from_env(env)


def test_from_env_raises_on_invalid_port() -> None:
    env = dict(VALID_ENV, EXADOCTOR_PORT="not-a-number")
    with pytest.raises(ConfigurationError):
        ConnectionConfig.from_env(env)


def test_repr_never_includes_password() -> None:
    config = ConnectionConfig.from_env(dict(VALID_ENV))
    assert "hunter2" not in repr(config)
    assert "***" in repr(config)
