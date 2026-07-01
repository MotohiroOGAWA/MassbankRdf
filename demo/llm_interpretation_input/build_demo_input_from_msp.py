from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from massbank_rdf.db.massbank.database import MassBankDatabase

from demo.llm_interpretation_input.demo_input_builder import KG_TABLE_KEYS
from massbank_rdf.models import MSPRecord

def _build_kg_lookup_service():
    from massbank_rdf.gui.settings.endpoint_settings import (
        create_kg_lookup_service_from_endpoint_settings,
    )

    return create_kg_lookup_service_from_endpoint_settings()


def build_demo_data_from_msp_file(
    input_file: str | Path,
    output_dir: str | Path,
    *,
    run_kg_lookup: bool = True,
    top_n: int = 10,
    mz_tolerance: float = 0.01,
    min_matched_peaks: int = 1,
    kg_n: int = 3,
    kg_limit: int | None = 100,
    precursor_tolerance: float | None = None,
) -> dict[str, Any]:
    """Build and save demo input data from one MSP record.

    Saved outputs include:
    - MSP metadata as pandas DataFrame and peaks as numpy array
    - MassBank search result records as pandas DataFrame
    - KG lookup result tables as pandas DataFrames
    """
    input_path = Path(input_file).resolve()
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    msp_record = MSPRecord.from_msp_file(input_path)
    msp_manifest = msp_record.save(output_path / "msp_record")

    precursor_mz = _optional_float(msp_record.get_metadata_value("PrecursorMZ"))
    ion_mode = msp_record.get_metadata_value("Ion_mode")

    db = MassBankDatabase()
    massbank_records = db.search_records_by_cosine_similarity_sql_dataframe(
        mz_list=msp_record.mz_list,
        intensity_list=msp_record.intensity_list,
        top_n=top_n,
        mz_tolerance=mz_tolerance,
        min_matched_peaks=min_matched_peaks,
        ion_mode=ion_mode,
        precursor_mz=precursor_mz,
        precursor_tolerance=precursor_tolerance,
    )
    massbank_manifest = _save_dataframe(
        massbank_records,
        output_path / "massbank_records",
    )

    kg_tables = _empty_kg_tables()
    if run_kg_lookup:
        kg_lookup_service = _build_kg_lookup_service()
        kg_tables = kg_lookup_service.search_by_massbank_records(
            massbank_records,
            inchikey_column="inchikey",
            top_n=top_n,
            kg_n=kg_n,
            limit=kg_limit,
        )

    kg_manifest = _save_kg_tables(
        kg_tables,
        output_path / "kg_tables",
    )

    manifest = {
        "input_file": str(input_path),
        "output_dir": str(output_path),
        "search_parameters": {
            "top_n": int(top_n),
            "mz_tolerance": float(mz_tolerance),
            "min_matched_peaks": int(min_matched_peaks),
            "ion_mode": ion_mode,
            "precursor_mz": precursor_mz,
            "precursor_tolerance": precursor_tolerance,
            "kg_n": int(kg_n),
            "kg_limit": kg_limit,
            "run_kg_lookup": bool(run_kg_lookup),
        },
        "msp_record": msp_manifest,
        "massbank_records": massbank_manifest,
        "kg_tables": kg_manifest,
    }

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"input: {input_path}")
    print(f"output_dir: {output_path}")
    print(f"msp_peaks: {msp_record.peaks.shape[0]}")
    print(f"massbank_records: {len(massbank_records)}")
    print(f"kg_lookup: {'enabled' if run_kg_lookup else 'disabled'}")
    print(f"manifest: {manifest_path}")

    return manifest


def _save_dataframe(
    df: pd.DataFrame,
    path_without_suffix: str | Path,
) -> dict[str, Any]:
    base_path = Path(path_without_suffix)
    base_path.parent.mkdir(parents=True, exist_ok=True)

    for stale_path in [
        base_path.with_suffix(".pkl"),
        base_path.with_suffix(".csv"),
    ]:
        stale_path.unlink(missing_ok=True)

    tsv_path = base_path.with_suffix(".tsv")
    df.to_csv(tsv_path, sep="\t", index=False)

    return {
        "tsv": str(tsv_path),
        "rows": int(len(df)),
        "columns": list(df.columns),
    }


def _save_kg_tables(
    kg_tables: dict[str, pd.DataFrame],
    output_dir: str | Path,
) -> dict[str, Any]:
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {}
    for key in KG_TABLE_KEYS:
        table = kg_tables.get(key)
        if table is None:
            table = pd.DataFrame()
        manifest[key] = _save_dataframe(table, base_dir / key)

    return manifest


def _empty_kg_tables() -> dict[str, pd.DataFrame]:
    return {
        key: pd.DataFrame()
        for key in KG_TABLE_KEYS
    }


def _optional_float(
    value: Any,
) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build demo input files from one MSP record.",
    )
    parser.add_argument(
        "--input-file",
        required=True,
        help="MSP input file path.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where MSP, MassBank, and KG tables are saved.",
    )
    parser.add_argument(
        "--run-kg-lookup",
        dest="run_kg_lookup",
        action="store_true",
        default=True,
        help="Run real KG/SPARQL lookup using GUI endpoint settings. This is the default.",
    )
    parser.add_argument(
        "--skip-kg-lookup",
        dest="run_kg_lookup",
        action="store_false",
        help="Skip KG/SPARQL lookup and save empty KG tables.",
    )
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--mz-tolerance", type=float, default=0.01)
    parser.add_argument("--min-matched-peaks", type=int, default=1)
    parser.add_argument("--kg-n", type=int, default=3)
    parser.add_argument("--kg-limit", type=int, default=100)
    parser.add_argument("--precursor-tolerance", type=float, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_demo_data_from_msp_file(
        input_file=args.input_file,
        output_dir=args.output_dir,
        run_kg_lookup=args.run_kg_lookup,
        top_n=args.top_n,
        mz_tolerance=args.mz_tolerance,
        min_matched_peaks=args.min_matched_peaks,
        kg_n=args.kg_n,
        kg_limit=args.kg_limit,
        precursor_tolerance=args.precursor_tolerance,
    )


if __name__ == "__main__":
    main()
