from __future__ import annotations

import argparse
from pathlib import Path

from .database import MassBankDatabase
from .importer import MassBankImporter


def build_sqlite(
    records_tsv: str | Path,
    peaks_json: str | Path,
    *,
    recreate: bool = True,
) -> None:
    """Build SQLite database from MassBank records TSV and peaks JSON."""
    db = MassBankDatabase()

    if recreate:
        db.recreate_tables()
    else:
        db.create_tables()

    with db.session() as session:
        importer = MassBankImporter(session)
        importer.import_records_tsv(records_tsv)
        importer.import_peaks_json(peaks_json)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build MassBank SQLite database from TSV and peak JSON files.",
    )

    parser.add_argument(
        "--records-tsv",
        required=True,
        help="Path to MassBank records TSV file.",
    )

    parser.add_argument(
        "--peaks-json",
        required=True,
        help="Path to MassBank peaks JSON file.",
    )

    parser.add_argument(
        "--no-recreate",
        action="store_true",
        help="Do not drop existing tables before importing.",
    )

    return parser.parse_args()


def main() -> None:

    build_sqlite(
        records_tsv='data/trash/massbank_records.tsv',
        peaks_json='data/trash/massbank_peaks.json',
        recreate=False,
    )


if __name__ == "__main__":
    main()