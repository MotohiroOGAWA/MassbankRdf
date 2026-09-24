from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from socket import timeout as SocketTimeout
from typing import Iterable
from urllib.error import HTTPError, URLError

import pandas as pd
from sqlalchemy import func, select
from SPARQLWrapper.SPARQLExceptions import SPARQLWrapperException
from tqdm import tqdm

APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from massbank_rdf.db.kg.database import KgDatabase  # noqa: E402
from massbank_rdf.db.massbank.database import MassBankDatabase  # noqa: E402
from massbank_rdf.db.massbank.tables.massbank_record import MassBankRecord  # noqa: E402
from massbank_rdf.gui.settings.endpoint_settings import (  # noqa: E402
    create_kg_lookup_service_from_endpoint_settings,
)
from massbank_rdf.services.kg.common import (  # noqa: E402
    extract_inchikey_value,
    normalize_inchikey_values,
    normalize_short_inchikey_values,
    to_short_inchikey,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a standalone KG SQLite database for MassBank InChIKeys. "
            "The database links to massbank.sqlite3 by normalized InChIKey."
        ),
    )
    parser.add_argument(
        "--massbank-db-path",
        type=Path,
        default=MassBankDatabase.DEFAULT_DB_PATH,
        help="Path to the existing MassBank SQLite database.",
    )
    parser.add_argument(
        "--kg-db-path",
        type=Path,
        default=KgDatabase.DEFAULT_DB_PATH,
        help="Path to the KG SQLite database to build.",
    )
    parser.add_argument(
        "--endpoint-settings",
        type=Path,
        default=None,
        help="Path to endpoint settings JSON. Defaults to GUI settings.",
    )
    parser.add_argument(
        "--max-inchikeys",
        type=int,
        default=None,
        help="Maximum number of unique MassBank InChIKeys to query.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help=(
            "Number of InChIKeys per SPARQL request batch. "
            "The default is conservative for comprehensive extraction."
        ),
    )
    parser.add_argument(
        "--sparql-limit",
        type=int,
        default=None,
        help=(
            "Optional SPARQL LIMIT per KG source and batch. "
            "Omit this for comprehensive KG extraction."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="SPARQL request timeout in seconds.",
    )
    parser.add_argument(
        "--no-recreate",
        action="store_true",
        help="Do not drop existing KG tables before importing.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an interrupted build by skipping InChIKeys whose "
            "kg_inchikeys.queried_at is already set. Implies --no-recreate."
        ),
    )
    parser.add_argument(
        "--kg-json-dir",
        type=Path,
        default=None,
        help=(
            "Directory for raw KG lookup batch JSON files. Defaults to "
            "<kg-db-dir>/kg_lookup_batches."
        ),
    )
    parser.add_argument(
        "--no-save-kg-json",
        action="store_true",
        help="Do not save raw KG lookup results as per-batch JSON files.",
    )
    parser.add_argument(
        "--use-short-inchikey",
        action="store_true",
        help=(
            "Query KG endpoints by the 14-character connectivity block and "
            "store metadata per short InChIKey."
        ),
    )
    return parser.parse_args()


RETRYABLE_KG_EXCEPTIONS = (
    HTTPError,
    URLError,
    TimeoutError,
    SocketTimeout,
    SPARQLWrapperException,
)


def chunked(values: list[str], batch_size: int) -> Iterable[list[str]]:
    batch_size = max(1, int(batch_size))
    for start in range(0, len(values), batch_size):
        yield values[start:start + batch_size]


def dataframe_to_json_records(df: pd.DataFrame) -> list[dict[str, object]]:
    if df is None or df.empty:
        return []
    clean_df = df.astype(object).where(pd.notna(df), None)
    return clean_df.to_dict(orient="records")


def save_kg_batch_json(
    *,
    output_dir: Path,
    batch_index: int,
    batch: list[str],
    data: dict[str, pd.DataFrame],
    queried_at: datetime,
    suffix: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix_part = f"_{suffix}" if suffix else ""
    output_path = output_dir / f"kg_batch_{batch_index:06d}{suffix_part}.json"
    payload = {
        "batch_index": batch_index,
        "inchikeys": batch,
        "queried_at": queried_at.isoformat(),
        "sources": {
            source_name: dataframe_to_json_records(frame)
            for source_name, frame in data.items()
        },
    }
    output_path.write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    )
    return output_path


def import_batch_kg_data(
    *,
    service,
    kg_db: KgDatabase,
    summary_by_inchikey: pd.DataFrame,
    batch: list[str],
    sparql_limit: int | None,
    queried_at: datetime,
    batch_index: int,
    kg_json_dir: Path | None,
    json_suffix: str | None = None,
    use_short_inchikey: bool = False,
) -> None:
    data = service.search_by_inchikeys(
        batch,
        limit=sparql_limit,
        use_short_inchikey=use_short_inchikey,
    )
    if kg_json_dir is not None:
        save_kg_batch_json(
            output_dir=kg_json_dir,
            batch_index=batch_index,
            batch=batch,
            data=data,
            queried_at=queried_at,
            suffix=json_suffix,
        )

    batch_summary = summary_by_inchikey.loc[
        summary_by_inchikey.index.intersection(batch)
    ].reset_index(drop=True)
    kg_db.import_kg_dataframes(
        data,
        inchikey_summary_df=batch_summary,
        queried_at=queried_at,
        replace_for_inchikeys=batch,
    )


def import_batch_with_timeout_fallback(
    *,
    service,
    kg_db: KgDatabase,
    summary_by_inchikey: pd.DataFrame,
    batch: list[str],
    sparql_limit: int | None,
    queried_at: datetime,
    batch_index: int,
    kg_json_dir: Path | None,
    use_short_inchikey: bool = False,
) -> None:
    try:
        import_batch_kg_data(
            service=service,
            kg_db=kg_db,
            summary_by_inchikey=summary_by_inchikey,
            batch=batch,
            sparql_limit=sparql_limit,
            queried_at=queried_at,
            batch_index=batch_index,
            kg_json_dir=kg_json_dir,
            use_short_inchikey=use_short_inchikey,
        )
        return
    except RETRYABLE_KG_EXCEPTIONS as error:
        if len(batch) <= 1:
            record_failed_inchikey(
                kg_db=kg_db,
                summary_by_inchikey=summary_by_inchikey,
                inchikey=batch[0],
                queried_at=queried_at,
                error=error,
            )
            return

        print(
            "KG batch failed after retries; retrying one InChIKey at a time: "
            + ", ".join(batch),
            flush=True,
        )

    for retry_index, inchikey in enumerate(batch, start=1):
        try:
            import_batch_kg_data(
                service=service,
                kg_db=kg_db,
                summary_by_inchikey=summary_by_inchikey,
                batch=[inchikey],
                sparql_limit=sparql_limit,
                queried_at=queried_at,
                batch_index=batch_index,
                kg_json_dir=kg_json_dir,
                json_suffix=f"retry_{retry_index:04d}",
                use_short_inchikey=use_short_inchikey,
            )
        except RETRYABLE_KG_EXCEPTIONS as error:
            record_failed_inchikey(
                kg_db=kg_db,
                summary_by_inchikey=summary_by_inchikey,
                inchikey=inchikey,
                queried_at=queried_at,
                error=error,
            )


def record_failed_inchikey(
    *,
    kg_db: KgDatabase,
    summary_by_inchikey: pd.DataFrame,
    inchikey: str,
    queried_at: datetime,
    error: Exception,
) -> None:
    print(
        f"Skipping InChIKey after individual KG lookup failure: "
        f"{inchikey} ({type(error).__name__}: {error})",
        flush=True,
    )
    failure_summary = summary_by_inchikey.loc[
        summary_by_inchikey.index.intersection([inchikey])
    ].reset_index(drop=True)
    kg_db.record_lookup_failure(
        inchikey,
        inchikey_summary_df=failure_summary,
        failed_at=queried_at,
        error=error,
    )


def load_massbank_inchikey_summary(
    db: MassBankDatabase,
) -> pd.DataFrame:
    stmt = (
        select(
            MassBankRecord.inchikey,
            func.count(MassBankRecord.id).label("massbank_record_count"),
            func.min(MassBankRecord.accession_id).label("example_accession_id"),
            func.min(MassBankRecord.name).label("example_name"),
            func.min(MassBankRecord.formula).label("example_formula"),
        )
        .where(MassBankRecord.inchikey.is_not(None))
        .group_by(MassBankRecord.inchikey)
        .order_by(MassBankRecord.inchikey)
    )

    with db.engine.connect() as conn:
        summary = pd.read_sql(stmt, conn)

    if summary.empty:
        return pd.DataFrame(
            columns=[
                "inchikey",
                "massbank_record_count",
                "example_accession_id",
                "example_name",
                "example_formula",
            ]
        )

    summary["inchikey"] = summary["inchikey"].apply(extract_inchikey_value)
    summary = summary.dropna(subset=["inchikey"])
    summary["inchikey"] = summary["inchikey"].astype(str)

    return (
        summary.groupby("inchikey", as_index=False)
        .agg(
            massbank_record_count=("massbank_record_count", "sum"),
            example_accession_id=("example_accession_id", "first"),
            example_name=("example_name", "first"),
            example_formula=("example_formula", "first"),
        )
        .sort_values("inchikey")
        .reset_index(drop=True)
    )


def build_short_inchikey_summary(
    full_summary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate MassBank metadata by short key and return full-key mappings."""
    if full_summary.empty:
        empty_summary = full_summary.copy()
        mappings = pd.DataFrame(columns=["inchikey", "short_inchikey"])
        return empty_summary, mappings

    data = full_summary.copy()
    data["short_inchikey"] = data["inchikey"].apply(to_short_inchikey)
    data = data.dropna(subset=["short_inchikey"])
    mappings = (
        data[["inchikey", "short_inchikey"]]
        .drop_duplicates()
        .sort_values(["short_inchikey", "inchikey"])
        .reset_index(drop=True)
    )
    summary = (
        data.groupby("short_inchikey", as_index=False)
        .agg(
            massbank_record_count=("massbank_record_count", "sum"),
            example_accession_id=("example_accession_id", "first"),
            example_name=("example_name", "first"),
            example_formula=("example_formula", "first"),
        )
        .rename(columns={"short_inchikey": "inchikey"})
        .sort_values("inchikey")
        .reset_index(drop=True)
    )
    return summary, mappings


def build_sqlite(
    *,
    massbank_db_path: str | Path | None = None,
    kg_db_path: str | Path | None = None,
    endpoint_settings: str | Path | None = None,
    max_inchikeys: int | None = None,
    batch_size: int = 1,
    sparql_limit: int | None = None,
    timeout: int = 300,
    recreate: bool = True,
    resume: bool = False,
    kg_json_dir: str | Path | None = None,
    save_kg_json: bool = True,
    use_short_inchikey: bool = False,
) -> None:
    """Build KG SQLite database from MassBank InChIKeys and KG endpoints."""
    massbank_db = MassBankDatabase(massbank_db_path)
    kg_db = KgDatabase(
        kg_db_path,
        use_short_inchikey=use_short_inchikey,
    )
    resolved_kg_json_dir = (
        Path(kg_json_dir)
        if kg_json_dir is not None
        else kg_db.db_path.parent / "kg_lookup_batches"
    ) if save_kg_json else None

    if resume:
        recreate = False

    if recreate:
        kg_db.recreate_tables()
    else:
        kg_db.create_tables()

    full_summary = load_massbank_inchikey_summary(massbank_db)
    mappings: pd.DataFrame | None = None
    if use_short_inchikey:
        summary, mappings = build_short_inchikey_summary(full_summary)
        inchikeys = normalize_short_inchikey_values(
            summary["inchikey"].tolist()
        )
    else:
        summary = full_summary
        inchikeys = normalize_inchikey_values(summary["inchikey"].tolist())

    if max_inchikeys is not None:
        inchikeys = inchikeys[: max(0, int(max_inchikeys))]
        summary = summary[summary["inchikey"].isin(inchikeys)].reset_index(drop=True)
        if mappings is not None:
            mappings = mappings[
                mappings["short_inchikey"].isin(inchikeys)
            ].reset_index(drop=True)

    kg_db.upsert_massbank_inchikey_summary(summary)
    if mappings is not None:
        kg_db.replace_inchikey_short_mappings(mappings)

    total_inchikey_count = len(inchikeys)
    if resume:
        queried_inchikeys = kg_db.get_queried_inchikeys()
        failed_inchikeys = kg_db.get_failed_inchikeys()
        queried_inchikeys.update(failed_inchikeys)
        inchikey_id_by_value = kg_db.get_inchikey_id_map(inchikeys)
        max_candidate_id = max(inchikey_id_by_value.values(), default=0)
        metadata_progress_id = kg_db.get_max_metadata_kg_inchikey_id()

        if (
            len(queried_inchikeys) >= total_inchikey_count
            and metadata_progress_id < max_candidate_id
        ):
            kg_db.clear_queried_at_after_kg_inchikey_id(metadata_progress_id)
            inchikeys = [
                inchikey
                for inchikey in inchikeys
                if inchikey_id_by_value.get(inchikey, 0) > metadata_progress_id
            ]
            skipped_count = total_inchikey_count - len(inchikeys)
            print(
                "Resume enabled: detected stale queried_at markers; "
                f"using metadata progress kg_inchikey_id={metadata_progress_id}. "
                f"Skipped {skipped_count} InChIKeys.",
                flush=True,
            )
        else:
            inchikeys = [
                inchikey
                for inchikey in inchikeys
                if inchikey not in queried_inchikeys
            ]
            skipped_count = total_inchikey_count - len(inchikeys)
            print(
                f"Resume enabled: skipped {skipped_count} already queried "
                f"InChIKeys.",
                flush=True,
            )

    queried_at = datetime.utcnow()

    print(
        f"Loaded {total_inchikey_count} unique MassBank "
        f"{'short ' if use_short_inchikey else ''}InChIKeys; "
        f"{len(inchikeys)} remain to query.",
        flush=True,
    )
    if not inchikeys:
        print(f"Wrote KG SQLite database to: {kg_db.db_path}", flush=True)
        return

    service = create_kg_lookup_service_from_endpoint_settings(
        Path(endpoint_settings) if endpoint_settings is not None else None,
        timeout=timeout,
    )

    batches = list(chunked(inchikeys, batch_size))
    summary_by_inchikey = summary.set_index("inchikey", drop=False)

    progress = tqdm(
        enumerate(batches, start=1),
        total=len(batches),
        desc="Querying KG batches",
        unit="batch",
    )

    for batch_index, batch in progress:
        progress.set_postfix(inchikeys=len(batch))
        import_batch_with_timeout_fallback(
            service=service,
            kg_db=kg_db,
            summary_by_inchikey=summary_by_inchikey,
            batch=batch,
            sparql_limit=sparql_limit,
            queried_at=queried_at,
            batch_index=batch_index,
            kg_json_dir=resolved_kg_json_dir,
            use_short_inchikey=use_short_inchikey,
        )

    print(f"Wrote KG SQLite database to: {kg_db.db_path}", flush=True)
    if resolved_kg_json_dir is not None:
        print(f"Wrote KG batch JSON files to: {resolved_kg_json_dir}", flush=True)


def main() -> None:
    args = parse_args()
    build_sqlite(
        massbank_db_path=args.massbank_db_path,
        kg_db_path=args.kg_db_path,
        endpoint_settings=args.endpoint_settings,
        max_inchikeys=args.max_inchikeys,
        batch_size=args.batch_size,
        sparql_limit=args.sparql_limit,
        timeout=args.timeout,
        recreate=not args.no_recreate and not args.resume,
        resume=args.resume,
        kg_json_dir=args.kg_json_dir,
        save_kg_json=not args.no_save_kg_json,
        use_short_inchikey=args.use_short_inchikey,
    )


if __name__ == "__main__":
    main()
