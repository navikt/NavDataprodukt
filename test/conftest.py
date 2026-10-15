import os

import oracledb
import pytest
from sqlalchemy.engine import make_url
from testcontainers.community.oracle import OracleDbContainer

from statistikkbank.testenv import (
    CONTAINER_IMAGE,
    CONTAINER_NAME,
    CONTAINER_PORT,
    ORACLE_PASSWORD,
    ORACLE_SERVICE,
    ORACLE_USER,
    TZ,
)

EXTERNAL = os.environ.get("STATISTIKKBANK_TESTENV_EXTERNAL") == "1"


@pytest.fixture(scope="session")
def oracle_container():
    """Oppretter Oracle-containeren når en ekstern testdatabase ikke brukes."""
    if EXTERNAL:
        yield None
        return
    container = OracleDbContainer(
        image=CONTAINER_IMAGE,
        oracle_password=ORACLE_PASSWORD,
        dbname=ORACLE_SERVICE,
    )
    container.with_env("TZ", TZ)
    container.with_env("ORA_SDTZ", TZ)
    container.with_bind_ports(CONTAINER_PORT, CONTAINER_PORT)
    container.with_name(CONTAINER_NAME)
    with container:
        yield container


@pytest.fixture
def oracle_connection(oracle_container):
    """Oppretter en Oracle-tilkobling for testfunksjonen."""
    if EXTERNAL:
        dsn = oracledb.makedsn(
            "127.0.0.1", CONTAINER_PORT, service_name=ORACLE_SERVICE
        )
        try:
            connection = oracledb.connect(
                user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=dsn
            )
        except oracledb.Error as exc:
            pytest.fail(
                "Kan ikke koble til det eksterne Oracle-testmiljøet. "
                "Kjør 'statistikkbank testenv setup' utenfor sandkassen."
            )
    else:
        url = make_url(oracle_container.get_connection_url())
        dsn = oracledb.makedsn(
            url.host,
            url.port,
            service_name=url.query.get("service_name", "FREEPDB1"),
        )
        connection = oracledb.connect(
            user=url.username,
            password=url.password,
            dsn=dsn,
        )
    try:
        yield connection
    finally:
        connection.close()
