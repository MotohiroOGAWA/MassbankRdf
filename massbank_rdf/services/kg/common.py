from __future__ import annotations

import re

import pandas as pd


INCHIKEY_PATTERN = re.compile(
    r"[A-Z]{14}-[A-Z]{10}-[A-Z]",
    re.IGNORECASE,
)
SHORT_INCHIKEY_PATTERN = re.compile(
    r"(?<![A-Z])[A-Z]{14}(?![A-Z])",
    re.IGNORECASE,
)

SHORT_INCHIKEY_LENGTH = 14


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


def to_short_inchikey(value: str) -> str | None:
    """Return the 14-character connectivity block of an InChIKey."""
    inchikey = extract_inchikey_value(value)

    if inchikey is not None:
        return inchikey[:SHORT_INCHIKEY_LENGTH]

    match = SHORT_INCHIKEY_PATTERN.search(str(value))
    if match is None:
        return None

    return match.group(0).upper()


def normalize_short_inchikey_values(
    values: list[str],
) -> list[str]:
    """Normalize, shorten, and deduplicate InChIKey values."""
    normalized: list[str] = []

    for value in values:
        short_inchikey = to_short_inchikey(value)

        if short_inchikey is not None and short_inchikey not in normalized:
            normalized.append(short_inchikey)

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
