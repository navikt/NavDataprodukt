from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from statistikkbank import app
from statistikkbank.config import load_configuration
from statistikkbank.testenv import TestEnvironmentError

LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


class NorskHelpFormatter(argparse.HelpFormatter):
    def _format_usage(self, usage, actions, groups, prefix):
        return super()._format_usage(usage, actions, groups, prefix).replace(
            "usage:", "bruk:", 1
        )


class NorskArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("add_help", False)
        kwargs.setdefault("formatter_class", NorskHelpFormatter)
        super().__init__(*args, **kwargs)
        self._positionals.title = "kommandoer og argumenter"
        self._optionals.title = "valg"

    def error(self, message: str) -> None:
        if message.startswith("invalid choice:"):
            message = "Ugyldig valg."
        elif message.startswith("the following arguments are required:"):
            message = "Påkrevde argumenter mangler."
        elif message.startswith("unrecognized arguments:"):
            message = "Ukjente argumenter."
        self._print_message(self.format_usage(), sys.stderr)
        self.exit(2, f"{self.prog}: FEIL: {message}\n")

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "bruk:", 1)


def _add_logging_options(parser: argparse.ArgumentParser) -> None:
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


def _add_help_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-h", "--help",
        action="help",
        help="Vis denne hjelpen og avslutt.",
    )


def _add_aggregate_options(parser: argparse.ArgumentParser) -> None:
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
    parser = NorskArgumentParser(
        prog="statistikkbank",
        description="Lag og vedlikehold småaggregater for statistikkbanken.",
        epilog="Bruk 'statistikkbank aggregat prikking --help' for flere valg.",
    )
    _add_help_option(parser)
    commands = parser.add_subparsers(dest="command", required=True)
    aggregate = commands.add_parser(
        "aggregat", help="Kjør prikking for ett eller flere småaggregater."
    )
    _add_help_option(aggregate)
    aggregate_commands = aggregate.add_subparsers(dest="aggregate_command", required=True)
    suppression = aggregate_commands.add_parser(
        "prikking", help="Kjør prikking for ett eller flere småaggregater."
    )
    _add_help_option(suppression)
    _add_aggregate_options(suppression)

    testenv = commands.add_parser(
        "testenv", help="Administrer Oracle-miljøet som brukes av tester."
    )
    _add_help_option(testenv)
    testenv_commands = testenv.add_subparsers(dest="testenv_command", required=True)
    setup_parser = testenv_commands.add_parser("setup", help="Start det eksterne Oracle-testmiljøet.")
    _add_help_option(setup_parser)
    teardown_parser = testenv_commands.add_parser("teardown", help="Stopp og fjern det administrerte testmiljøet.")
    _add_help_option(teardown_parser)
    pytest_parser = testenv_commands.add_parser(
        "pytest", help="Kjør pytest mot Oracle-testmiljøet som allerede kjører."
    )
    _add_help_option(pytest_parser)
    pytest_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Argumenter som sendes videre til pytest etter --.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "testenv":
        _run_testenv(args, parser)
        return
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else getattr(logging, args.log_level),
        format="%(levelname)s: %(message)s",
    )
    config_path = args.config or "konfigurasjon.yml"
    try:
        configuration, config_directory = load_configuration(config_path)
    except (ValueError, OSError, ValidationError) as exc:
        _report_error(
            str(exc), debug=args.verbose or args.log_level == "DEBUG"
        )
        raise SystemExit(2) from None
    try:
        app.run(
            configuration,
            config_directory,
            selected_tables=args.aggregater,
            input_directory=args.input_directory,
            output_directory=args.output_directory,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        _report_error(
            str(exc), debug=args.verbose or args.log_level == "DEBUG"
        )
        raise SystemExit(1) from None
    except Exception:
        _report_error(
            "Kjøringen feilet. Bruk --log-level=DEBUG for tekniske detaljer.",
            debug=args.verbose or args.log_level == "DEBUG",
        )
        raise SystemExit(1) from None


def _run_testenv(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from statistikkbank import testenv

    try:
        if args.testenv_command == "setup":
            testenv.setup()
        elif args.testenv_command == "teardown":
            testenv.teardown()
        else:
            arguments = list(args.pytest_args)
            if arguments and arguments[0] == "--":
                arguments.pop(0)
            if not arguments:
                parser.error("testenv pytest krever -- etterfulgt av pytest-argumenter.")
            raise SystemExit(testenv.run_pytest(arguments))
    except TestEnvironmentError as exc:
        print(f"FEIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print(
            "FEIL: Testmiljøkommandoen feilet. Kontroller Docker og prøv igjen.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def _report_error(message: str, *, debug: bool) -> None:
    print(f"FEIL: {message}", file=sys.stderr)
    if debug:
        logging.exception("Detaljer for feilen:")


if __name__ == "__main__":
    main()
