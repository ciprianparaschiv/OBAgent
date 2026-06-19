"""Test fixtures. Connector tests are integration tests against the local
snapshot DB; they skip automatically if it isn't reachable."""

import pytest

from studio_agent import db


@pytest.fixture(scope="session", autouse=True)
def _require_db():
    try:
        db.query("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001 - any connection problem -> skip
        pytest.skip(f"Local snapshot DB not reachable: {exc}", allow_module_level=True)
