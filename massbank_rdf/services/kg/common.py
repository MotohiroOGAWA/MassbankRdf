from __future__ import annotations

import re

import pandas as pd


INCHIKEY_PATTERN = re.compile(
    r"[A-Z]{14}-[A-Z]{10}-[A-Z]",
    re.IGNORECASE,
)


def escape_sparql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def sparql_values(
    variable: str,
    values: list[str],
) -> str:
    if len(values) == 0:
        return f"VALUES ?{variable} {{ }}"

    quoted = [
        f'"{escape_sparql_string(value)}"'
        for value in values
    ]

    return f"VALUES ?{variable} {{ {' '.join(quoted)} }}"


def normalize_inchikey_values(
    values: list[str],
) -> list[str]:
    normalized: list[str] = []

    for value in values:
        match = INCHIKEY_PATTERN.search(str(value))

        if match is None:
            continue

        inchikey = match.group(0).upper()

        if inchikey not in normalized:
            normalized.append(inchikey)

    return normalized


def extract_inchikey_value(
    value: object,
) -> str | None:
    if value is None:
        return None

    match = INCHIKEY_PATTERN.search(str(value))

    if match is None:
        return None

    return match.group(0).upper()


def ensure_columns(
    df: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    df = df.copy()

    for column in columns:
        if column not in df.columns:
            df[column] = ""

    return df