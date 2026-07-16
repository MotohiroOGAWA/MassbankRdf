from __future__ import annotations

import argparse
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from data.db.build_kg_1nf_sqlite import build_1nf_database  # noqa: E402
from massbank_rdf.db.kg.build_sqlite import build_sqlite  # noqa: E402
from massbank_rdf.db.massbank.database import MassBankDatabase  # noqa: E402


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SHORT_DB = BASE_DIR / "kg_short_inchikey.sqlite3"
DEFAULT_SHORT_1NF_DB = BASE_DIR / "kg_short_inchikey_1nf.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Query KG endpoints by short InChIKey and build normalized and "
            "1NF SQLite metadata databases."
        )
    )
    parser.add_argument(
        "--massbank-db-path",
        type=Path,
        default=MassBankDatabase.DEFAULT_DB_PATH,
    )
    parser.add_argument("--short-db", type=Path, default=DEFAULT_SHORT_DB)
    parser.add_argument(
        "--short-1nf-db",
        type=Path,
        default=DEFAULT_SHORT_1NF_DB,
    )
    parser.add_argument("--endpoint-settings", type=Path, default=None)
    parser.add_argument("--max-inchikeys", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--sparql-limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--no-recreate",
        action="store_true",
        help="Keep existing normalized KG tables before importing.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume short-InChIKey queries already stored in the output DB.",
    )
    parser.add_argument(
        "--kg-json-dir",
        type=Path,
        default=None,
        help=(
            "Raw SPARQL response directory. Defaults to "
            "<short-db-dir>/kg_short_inchikey_lookup_batches."
        ),
    )
    parser.add_argument("--no-save-kg-json", action="store_true")
    return parser.parse_args()


def build_short_inchikey_databases(
    *,
    massbank_db_path: Path,
    short_db: Path,
    short_1nf_db: Path,
    endpoint_settings: Path | None = None,
    max_inchikeys: int | None = None,
    batch_size: int = 1,
    sparql_limit: int | None = None,
    timeout: int = 300,
    recreate: bool = True,
    resume: bool = False,
    kg_json_dir: Path | None = None,
    save_kg_json: bool = True,
) -> None:
    """Build short-key KG metadata via SPARQL, then build its 1NF DB."""
    short_db = Path(short_db)
    short_1nf_db = Path(short_1nf_db)
    if short_db.resolve() == short_1nf_db.resolve():
        raise ValueError("Normalized and 1NF output paths must be different.")

    resolved_json_dir = kg_json_dir
    if resolved_json_dir is None and save_kg_json:
        resolved_json_dir = (
            short_db.parent / "kg_short_inchikey_lookup_batches"
        )

    build_sqlite(
        massbank_db_path=massbank_db_path,
        kg_db_path=short_db,
        endpoint_settings=endpoint_settings,
        max_inchikeys=max_inchikeys,
        batch_size=batch_size,
        sparql_limit=sparql_limit,
        timeout=timeout,
        recreate=recreate,
        resume=resume,
        kg_json_dir=resolved_json_dir,
        save_kg_json=save_kg_json,
        use_short_inchikey=True,
    )
    build_1nf_database(short_db, short_1nf_db, overwrite=True)


def main() -> None:
    args = parse_args()
    build_short_inchikey_databases(
        massbank_db_path=args.massbank_db_path,
        short_db=args.short_db,
        short_1nf_db=args.short_1nf_db,
        endpoint_settings=args.endpoint_settings,
        max_inchikeys=args.max_inchikeys,
        batch_size=args.batch_size,
        sparql_limit=args.sparql_limit,
        timeout=args.timeout,
        recreate=not args.no_recreate and not args.resume,
        resume=args.resume,
        kg_json_dir=args.kg_json_dir,
        save_kg_json=not args.no_save_kg_json,
    )
    print(f"Created short-InChIKey KG database: {args.short_db}")
    print(f"Created short-InChIKey 1NF database: {args.short_1nf_db}")


if __name__ == "__main__":
    main()
