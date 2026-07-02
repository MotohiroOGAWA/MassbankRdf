from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data/db/massbank.sqlite3"


def fetch_unique_inchikeys(db_path: str | Path) -> list[str]:
    """Return sorted unique InChIKeys from massbank_records."""
    conn = sqlite3.connect(Path(db_path))
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT inchikey
            FROM massbank_records
            WHERE inchikey IS NOT NULL
              AND trim(inchikey) != ''
            ORDER BY inchikey
            """
        ).fetchall()
    finally:
        conn.close()

    return [row[0] for row in rows]


def write_inchikeys(
    inchikeys: list[str],
    output_path: str | Path | None = None,
) -> None:
    text = "\n".join(inchikeys)
    if text:
        text += "\n"

    if output_path is None:
        sys.stdout.write(text)
        return

    Path(output_path).write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract unique InChIKeys from massbank_records.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite DB path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output text file path. Defaults to stdout.",
    )
    args = parser.parse_args()

    inchikeys = fetch_unique_inchikeys(args.db_path)
    write_inchikeys(inchikeys, args.output)


if __name__ == "__main__":
    main()
