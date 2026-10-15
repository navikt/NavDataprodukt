from __future__ import annotations

import logging
import re

import oracledb

from statistikkbank.config import SmallAggregate

LOGGER = logging.getLogger(__name__)


def read_metadata(
    connection: oracledb.Connection, schema: str, aggregate: SmallAggregate
) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT comments FROM dba_tab_comments WHERE owner = :owner "
            "AND table_name = :table_name",
            owner=schema.upper(),
            table_name=aggregate.tabell.upper(),
        )
        row = cursor.fetchone()
        result = parse_metadata(row[0] if row else None)
        entities = [(aggregate.tabell, aggregate)] + [
            (variable.kolonne, variable)
            for variable in [*aggregate.variabler, aggregate.tallkolonne]
        ]
        for column, model in entities:
            if column == aggregate.tabell:
                comments = result
            else:
                cursor.execute(
                    "SELECT comments FROM dba_col_comments WHERE owner = :owner "
                    "AND table_name = :table_name AND column_name = :column_name",
                    owner=schema.upper(),
                    table_name=aggregate.tabell.upper(),
                    column_name=column.upper(),
                )
                row = cursor.fetchone()
                comments = parse_metadata(row[0] if row else None)
            for tag in ("navn", "navn_en", "beskrivelse", "beskrivelse_en"):
                value = getattr(model, tag)
                if value:
                    LOGGER.info("%s.%s hentes fra konfigurasjonen.", column, tag)
                elif comments.get(tag.upper()):
                    setattr(model, tag, comments[tag.upper()])
                    LOGGER.info("%s.%s hentes fra databasekommentar.", column, tag)
                else:
                    raise ValueError(
                        f"Metadatafeltet {tag} mangler for {column}; angi det i YAML "
                        "eller legg det til som databasekommentar."
                    )
                LOGGER.debug("%s.%s = %s", column, tag, getattr(model, tag))
    return result


def parse_metadata(comment: str | None) -> dict[str, str]:
    if not comment:
        return {}
    matches = list(re.finditer(r"#(NAVN(?:_EN)?|BESKRIVELSE(?:_EN)?)\b", comment, re.I))
    values: dict[str, str] = {}
    seen: set[str] = set()
    for index, match in enumerate(matches):
        tag = match.group(1).upper()
        if tag in seen:
            raise ValueError(f"Databasekommentaren inneholder taggen #{tag} flere ganger.")
        seen.add(tag)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(comment)
        value = comment[match.end() : end].strip()
        if value:
            values[tag] = value
    return values
