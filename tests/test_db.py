"""Read-only guard tests for the DB layer."""

import pytest

from studio_agent import db


@pytest.mark.parametrize(
    "stmt",
    [
        "DELETE FROM project",
        "UPDATE user SET user_name='x'",
        "INSERT INTO user (user_name) VALUES ('x')",
        "DROP TABLE project",
        "  truncate timing",
    ],
)
def test_write_statements_are_refused(stmt):
    with pytest.raises(db.WriteAttemptError):
        db.query(stmt)


@pytest.mark.parametrize("stmt", ["SELECT 1 AS ok", "  select 2", "SHOW TABLES"])
def test_read_statements_allowed(stmt):
    # Should not raise the guard (may still return rows).
    db.query(stmt)
