from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import Sequence

import docker
import oracledb
from docker.errors import APIError, DockerException, ImageNotFound, NotFound

CONTAINER_NAME = "statistikkbank-oracle-test"
CONTAINER_IMAGE = "gvenzl/oracle-free:23-slim-faststart"
CONTAINER_LABEL = "no.nav.statistikkbank.testenv"
CONTAINER_LABEL_VALUE = "managed"
CONTAINER_PORT = 1521
ORACLE_USER = "system"
ORACLE_PASSWORD = "testpassword"
ORACLE_SERVICE = "FREEPDB1"
TZ = "Europe/Oslo"
READY_TIMEOUT = 300
LOGGER_MESSAGE = (
    "Oracle-testmiljøet er ikke tilgjengelig. Kjør "
    "'statistikkbank testenv setup' utenfor sandkassen."
)


class TestEnvironmentError(Exception):
    pass


def setup() -> None:
    """Starter eller gjenbruker det administrerte Oracle-testmiljøet."""
    client = _docker_client()
    container = _get_named_container(client)
    if container is not None:
        _verify_managed(container)
        was_running = container.status == "running"
        if not was_running:
            try:
                container.start()
            except APIError as exc:
                raise TestEnvironmentError("Kunne ikke starte Oracle-testcontaineren.") from exc
            container.reload()
        _wait_ready()
        if was_running:
            print("Det administrerte Oracle-testmiljøet kjører allerede.")
        else:
            print("Det stoppede Oracle-testmiljøet er startet og klart.")
        return

    try:
        client.images.get(CONTAINER_IMAGE)
    except ImageNotFound:
        print(f"Oracle-testbildet {CONTAINER_IMAGE} lastes ned.")
        try:
            client.images.pull(CONTAINER_IMAGE)
        except DockerException as exc:
            raise TestEnvironmentError(
                "Kunne ikke hente Oracle-testbildet fra Docker-registeret."
            ) from exc
    except DockerException as exc:
        raise TestEnvironmentError("Kunne ikke kontrollere Oracle-testbildet.") from exc

    try:
        container = client.containers.run(
            CONTAINER_IMAGE,
            name=CONTAINER_NAME,
            detach=True,
            ports={"1521/tcp": CONTAINER_PORT},
            environment={
                "ORACLE_PASSWORD": ORACLE_PASSWORD,
                "TZ": TZ,
                "ORA_SDTZ": TZ,
            },
            labels={CONTAINER_LABEL: CONTAINER_LABEL_VALUE},
        )
    except APIError as exc:
        if "port is already allocated" in str(exc).lower() or "port is already in use" in str(exc).lower():
            raise TestEnvironmentError(
                f"Port {CONTAINER_PORT} er allerede i bruk. Stopp tjenesten som bruker porten."
            ) from exc
        if "already in use" in str(exc).lower():
            raise TestEnvironmentError(
                f"Containernavnet {CONTAINER_NAME} er allerede i bruk av en annen container."
            ) from exc
        raise TestEnvironmentError("Kunne ikke opprette Oracle-testcontaineren.") from exc

    print("Oracle-testmiljøet startes. Dette kan ta noen minutter.")
    try:
        _wait_ready()
        _grant_dictionary_access()
    except TestEnvironmentError:
        raise

    print("Oracle-testmiljøet er klart og fortsetter å kjøre etter at kommandoen avsluttes.")


def teardown() -> None:
    """Stopper og fjerner bare den administrerte testcontaineren."""
    client = _docker_client()
    container = _get_named_container(client)
    if container is None:
        print("Det finnes ikke noe administrert Oracle-testmiljø å fjerne.")
        return
    _verify_managed(container)
    try:
        if container.status == "running":
            container.stop(timeout=20)
        container.remove()
    except APIError as exc:
        raise TestEnvironmentError("Kunne ikke stoppe og fjerne Oracle-testmiljøet.") from exc
    print("Oracle-testmiljøet er stoppet og fjernet.")


def run_pytest(arguments: Sequence[str]) -> int:
    """Kontrollerer testmiljøet og kjører pytest med videresendte argumenter."""
    try:
        _wait_ready(timeout=5)
    except TestEnvironmentError as exc:
        raise TestEnvironmentError(LOGGER_MESSAGE) from exc

    environment = os.environ.copy()
    environment["STATISTIKKBANK_TESTENV_EXTERNAL"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", *arguments],
        env=environment,
        check=False,
    ).returncode


def _docker_client():
    """Oppretter en Docker-klient og kontrollerer at daemonen svarer."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as exc:
        raise TestEnvironmentError(
            "Docker er ikke tilgjengelig. Start Docker og kjør "
            "'statistikkbank testenv setup' utenfor sandkassen."
        ) from exc


def _get_named_container(client):
    """Henter den faste testcontaineren hvis den finnes."""
    try:
        return client.containers.get(CONTAINER_NAME)
    except NotFound:
        return None
    except DockerException as exc:
        raise TestEnvironmentError("Kunne ikke undersøke Docker-containerne.") from exc


def _verify_managed(container) -> None:
    """Avviser containere som ikke samsvarer med testmiljøets innstillinger."""
    labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
    image = container.attrs.get("Config", {}).get("Image")
    environment = container.attrs.get("Config", {}).get("Env", []) or []
    environment_values = dict(item.split("=", 1) for item in environment if "=" in item)
    bindings = container.attrs.get("HostConfig", {}).get("PortBindings", {}) or {}
    host_ports = {
        binding.get("HostPort")
        for values in bindings.values()
        for binding in (values or [])
    }
    if (
        labels.get(CONTAINER_LABEL) != CONTAINER_LABEL_VALUE
        or image != CONTAINER_IMAGE
        or str(CONTAINER_PORT) not in host_ports
        or environment_values.get("ORACLE_PASSWORD") != ORACLE_PASSWORD
        or environment_values.get("TZ") != TZ
        or environment_values.get("ORA_SDTZ") != TZ
    ):
        raise TestEnvironmentError(
            f"Containeren {CONTAINER_NAME} finnes, men er ikke et kompatibelt "
            "statistikkbank-testmiljø. Den blir ikke endret. Fjern eller gi nytt "
            "navn til containeren manuelt, og kjør 'statistikkbank testenv setup'."
        )


def _wait_ready(timeout: int = READY_TIMEOUT) -> None:
    """Venter på at Oracle skal godta tilkoblinger på den faste porten."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", CONTAINER_PORT), timeout=2):
                pass
            connection = oracledb.connect(
                user=ORACLE_USER,
                password=ORACLE_PASSWORD,
                dsn=oracledb.makedsn(
                    "127.0.0.1", CONTAINER_PORT, service_name=ORACLE_SERVICE
                ),
                tcp_connect_timeout=2,
            )
            connection.close()
            return
        except (OSError, oracledb.Error) as exc:
            last_error = exc
            time.sleep(2)
    raise TestEnvironmentError(
        "Oracle-testmiljøet svarte ikke innen tidsfristen. Kontroller Docker-logger."
    ) from last_error


def _grant_dictionary_access() -> None:
    """Gir testbrukeren lesetilgang til Oracle-visningene som valideringen bruker."""
    connection = None
    try:
        connection = oracledb.connect(
            user="sys",
            password=ORACLE_PASSWORD,
            dsn=oracledb.makedsn(
                "127.0.0.1", CONTAINER_PORT, service_name=ORACLE_SERVICE
            ),
            mode=oracledb.AuthMode.SYSDBA,
            tcp_connect_timeout=5,
        )
        with connection.cursor() as cursor:
            cursor.execute("GRANT SELECT_CATALOG_ROLE TO SYSTEM")
    except oracledb.Error as exc:
        raise TestEnvironmentError(
            "Kunne ikke gi SYSTEM lesetilgang til Oracle sine DBA-visninger."
        ) from exc
    finally:
        if connection is not None:
            connection.close()
