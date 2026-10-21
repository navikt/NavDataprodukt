from __future__ import annotations

import argparse
import os
from pathlib import Path

import logging
from statistikkbank import app
from statistikkbank.config import load_configuration, ConfigError

LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
LOGGER = logging.getLogger(__name__)


def _add_logging_options(parser: argparse.ArgumentParser) -> None:
    """Legger til flagg for loggnivå og detaljert visning."""
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        type=str.upper,
        help="Velg hvor detaljert meldingsloggen skal være (standard: INFO).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Vis også verdier fra metadata og mer detaljerte meldinger.",
    )


def _add_aggregate_options(parser: argparse.ArgumentParser) -> None:
    """Legger til valg for konfigurasjon, filer og aggregater."""
    parser.add_argument(
        "aggregater",
        nargs="*",
        metavar="TABELL",
        help="Tabellnavn for småaggregatene som skal behandles (standard: alle).",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("STATISTIKKBANK_AGGREGAT_CONFIG"),
        help="YAML-konfigurasjonsfil (standard: STATISTIKKBANK_AGGREGAT_CONFIG eller konfigurasjon.yml).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Vis hva som ville blitt gjort uten å skrive data.")
    parser.add_argument(
        "--input-directory",
        type=Path,
        help="Les CSV fra denne mappen. Uten valget leses data fra Oracle.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        help="Skriv CSV til denne mappen. Uten valget skrives resultatet til Oracle.",
    )
    _add_logging_options(parser)


def build_parser() -> argparse.ArgumentParser:
    """Bygger kommandolinjens underkommandoer og argumenter."""
    parser = argparse.ArgumentParser(
        prog="statistikkbank",
        description="Lag og vedlikehold småaggregater for statistikkbanken.",
        epilog="Bruk 'statistikkbank aggregat prikking --help' for flere valg.",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    aggregate = commands.add_parser(
        "aggregat", help="Kjør prikking for ett eller flere småaggregater."
    )

    aggregate_commands = aggregate.add_subparsers(dest="aggregate_command", required=True)
    suppression = aggregate_commands.add_parser(
        "prikking", help="Kjør prikking for ett eller flere småaggregater."
    )
    _add_aggregate_options(suppression)

    testenv = commands.add_parser(
        "testenv", help="Administrer Oracle-miljøet som brukes av tester."
    )

    testenv_commands = testenv.add_subparsers(dest="testenv_command", required=True)
    testenv_setup = testenv_commands.add_parser("setup", help="Start det eksterne Oracle-testmiljøet.")
    _add_logging_options(testenv_setup)

    teardown_parser = testenv_commands.add_parser("teardown", help="Stopp og fjern det administrerte testmiljøet.")
    _add_logging_options(teardown_parser)

    pytest_parser = testenv_commands.add_parser(
        "pytest", help="Kjør pytest mot Oracle-testmiljøet som allerede kjører."
    )

    pytest_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Argumenter som sendes videre til pytest etter --.",
    )
    return parser


def main() -> None:
    """Tolker argumenter, kjører valgt kommando og håndterer feil."""
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=getattr(args, "log_level", "INFO"), format="%(levelname)s: %(message)s")

    try:
        if args.command == "testenv":
            _run_testenv(args, parser)

        elif args.command == "aggregat" and args.aggregate_command == "prikking":
            config_path = args.config
            configuration, config_directory = load_configuration(config_path)

            app.run(
                configuration,
                config_directory,
                selected_tables=args.aggregater,
                input_directory=args.input_directory,
                output_directory=args.output_directory,
                dry_run=args.dry_run,
            )
        else:
            raise NotImplementedError("Ukjent kommando: " + args.command)
    except ConfigError as exc:
        _report_error(
            f"Konfigurasjonsfeil: {exc}",
            debug=args.log_level == "DEBUG",
        )
        raise SystemExit(2) from None
    except Exception as exc:
        _report_error(
            f"{exc}. Bruk --log-level=DEBUG for å se detaljer.",
            debug=args.log_level == "DEBUG",
        )
        raise SystemExit(1) from None


def _run_testenv(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Utfører valgt testmiljøkommando."""
    from statistikkbank import testenv

    if args.testenv_command == "setup":
        testenv.setup()
    elif args.testenv_command == "teardown":
        testenv.teardown()
    else:
        arguments = list(args.pytest_args)
        if arguments:
            if arguments[0] == "--":
                arguments.pop(0)
            else:
                parser.error("Argumenter til pytest må starte med --.")

        pytest_exit_code = testenv.run_pytest(arguments)
        raise SystemExit(pytest_exit_code)


def _report_error(message: str, *, debug: bool) -> None:
    """Viser en norsk feilmelding og eventuelle feilsøkingsdetaljer."""
    LOGGER.error(f"{message}")
    if debug:
        LOGGER.exception("Detaljer for feilen:")


if __name__ == "__main__":
    main()
