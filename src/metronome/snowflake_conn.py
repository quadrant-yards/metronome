from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import snowflake.connector
from cryptography.hazmat.primitives import serialization


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    private_key_pem: str
    role: str
    database: str
    warehouse: str


def _load_private_key_der(pem_text: str) -> bytes:
    private_key = serialization.load_pem_private_key(pem_text.encode(), password=None)
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@contextmanager
def connect(config: SnowflakeConfig) -> Iterator[snowflake.connector.SnowflakeConnection]:
    conn = snowflake.connector.connect(
        account=config.account,
        user=config.user,
        private_key=_load_private_key_der(config.private_key_pem),
        role=config.role,
        database=config.database,
        warehouse=config.warehouse,
    )
    try:
        yield conn
    finally:
        conn.close()


def execute_query(conn: snowflake.connector.SnowflakeConnection, sql: str) -> list[tuple]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, num_statements=0)
        rows = cursor.fetchall()
        while cursor.nextset() is not None:
            rows = cursor.fetchall()
        return rows
    finally:
        cursor.close()
