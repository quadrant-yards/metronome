from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from metronome.snowflake_conn import SnowflakeConfig, _load_private_key_der, connect, execute_query


def _generate_test_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem_bytes.decode()


def test_load_private_key_der_round_trips_a_pem_key():
    pem_text = _generate_test_pem()

    der_bytes = _load_private_key_der(pem_text)

    assert isinstance(der_bytes, bytes)
    reloaded = serialization.load_der_private_key(der_bytes, password=None)
    original = serialization.load_pem_private_key(pem_text.encode(), password=None)
    assert reloaded.private_numbers() == original.private_numbers()


def test_connect_passes_config_and_der_key_to_snowflake_connector():
    pem_text = _generate_test_pem()
    config = SnowflakeConfig(
        account="acct1", user="user1", private_key_pem=pem_text,
        role="role1", database="db1", warehouse="wh1",
    )

    fake_conn = MagicMock()
    with patch("snowflake.connector.connect", return_value=fake_conn) as mock_connect:
        with connect(config) as conn:
            assert conn is fake_conn

    _, kwargs = mock_connect.call_args
    assert kwargs["account"] == "acct1"
    assert kwargs["user"] == "user1"
    assert kwargs["role"] == "role1"
    assert kwargs["database"] == "db1"
    assert kwargs["warehouse"] == "wh1"
    assert isinstance(kwargs["private_key"], bytes)
    fake_conn.close.assert_called_once()


def test_execute_query_returns_fetchall_result_and_closes_cursor():
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = [("Stage A", "2026-07-01", 3)]
    fake_cursor.nextset.return_value = None
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor

    rows = execute_query(fake_conn, "select 1")

    assert rows == [("Stage A", "2026-07-01", 3)]
    fake_cursor.execute.assert_called_once_with("select 1", num_statements=0)
    fake_cursor.close.assert_called_once()


def test_execute_query_drains_multi_statement_scripts_and_returns_the_last_result():
    fake_cursor = MagicMock()
    fake_cursor.fetchall.side_effect = [
        [("Statement executed successfully.",)],
        [("Stage A", "2026-07-01", 3)],
    ]
    fake_cursor.nextset.side_effect = [True, None]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor

    rows = execute_query(fake_conn, "SET period = 'week'; select 1")

    assert rows == [("Stage A", "2026-07-01", 3)]
    fake_cursor.execute.assert_called_once_with("SET period = 'week'; select 1", num_statements=0)
    fake_cursor.close.assert_called_once()
