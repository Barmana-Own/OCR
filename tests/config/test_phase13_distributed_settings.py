import pytest

from ocr_platform.config import Settings
from ocr_platform.errors import ConfigurationError


def test_distributed_settings_are_explicit_and_secret_free() -> None:
    settings = Settings(
        environment="test",
        artifact_store_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_prefix="ocr-prod",
        metadata_backend="postgres",
        postgres_dsn="postgresql://user:secret@db/ocr",
        queue_backend="redis",
        redis_url="redis://:secret@redis:6379/0",
    )

    assert settings.configuration_payload["artifact_store_backend"] == "s3"
    assert "secret" not in str(settings.configuration_payload)


def test_distributed_backends_require_connection_configuration() -> None:
    with pytest.raises(ConfigurationError, match="PostgreSQL"):
        Settings(environment="test", metadata_backend="postgres")
    with pytest.raises(ConfigurationError, match="Redis"):
        Settings(environment="test", queue_backend="redis")
