"""Read-only MySQL access to the local PMS snapshot.

Two layers of read-only protection:
  1. The DB user is granted ``SELECT`` only (see scripts/import_snapshot.sh).
  2. ``query()`` rejects any statement that isn't a read.

Encoding note: the legacy tables are MySQL ``latin1`` (effectively cp1252). We
connect as ``utf8mb4`` so MySQL converts text server-side — the strict client
cp1252 codec used by ``charset="latin1"`` raises on bytes undefined in cp1252
(0x81/0x8d/0x8f/0x90/0x9d) that real rows contain. Double-encoded rows (UTF-8
stored in latin1) are repaired in ``repository._clean_text``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import pymysql
from pymysql.cursors import DictCursor

from .config import db_settings

# Statements we allow. Anything else (INSERT/UPDATE/DELETE/DDL/...) is refused
# before it ever reaches the server.
_READ_ONLY_PREFIXES = ("select", "show", "describe", "desc", "explain", "with")


class WriteAttemptError(RuntimeError):
    """Raised when a non-read statement is passed to the read-only connector."""


def _assert_read_only(sql: str) -> None:
    stripped = sql.lstrip().lstrip("(").lstrip()
    first = stripped.split(None, 1)[0].lower() if stripped else ""
    if first not in _READ_ONLY_PREFIXES:
        raise WriteAttemptError(
            f"Refusing non-read statement (starts with {first!r}). "
            "This connector is read-only."
        )


@contextmanager
def connect() -> Iterator[pymysql.connections.Connection]:
    """Yield a read-only connection. Autocommit on; no transaction needed for reads."""
    cfg = db_settings()
    conn = pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.name,
        charset=cfg.charset,
        cursorclass=DictCursor,
        autocommit=True,
    )
    try:
        # Belt-and-braces: ask the server to reject writes on this session too.
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
        yield conn
    finally:
        conn.close()


def query(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    """Run a read-only query and return rows as dicts."""
    _assert_read_only(sql)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def query_one(sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None
