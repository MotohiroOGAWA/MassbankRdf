from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from massbank_rdf.db.massbank.database import MassBankDatabase
from massbank_rdf.services.kg.kg_lookup_service import KgLookupService

from massbank_rdf.services.llm_interpretation.kg_evidence_builder import (
    build_kg_evidence_from_kg_data,
)

from massbank_rdf.models import MSPRecord


KG_TABLE_KEYS = [
    "pubchem_compound",
    "pubchem_pathway",
    "hmdb",
    "knapsack_activity",
]


@dataclass(frozen=True)
class ParsedSpectrumInput:
    """Parsed spectrum text for MassBank search and LLM input."""

    input_text: str
    input_format: str
    metadata: dict[str, Any]
    peaks: pd.DataFrame

    @property
    def mz_list(self) -> np.ndarray:
        return self.peaks["mz"].to_numpy(dtype=float)

    @property
    def intensity_list(self) -> np.ndarray:
        return self.peaks["intensity"].to_numpy(dtype=float)


def parse_spectrum_input(
    input_text: str,
) -> ParsedSpectrumInput:
    """Parse MSP text or plain m/z intensity pairs.

    Supported peak rows:
        100.1 20
        100.1,20

    MSP metadata lines before peaks are kept in ``metadata``. Peak parsing starts
    after ``Num Peaks:`` when present; otherwise numeric two-column lines are
    parsed from the whole text.
    """
    if not input_text or not input_text.strip():
        raise ValueError("input_text must contain MSP or peak-pair text.")

    if _looks_like_msp(input_text):
        record = MSPRecord.from_msp_text(input_text)
        return ParsedSpectrumInput(
            input_text=input_text,
            input_format="msp",
            metadata=record.metadata.iloc[0].to_dict(),
            peaks=record.peaks_dataframe,
        )

    peaks = _parse_peak_lines(input_text.splitlines())

    return ParsedSpectrumInput(
        input_text=input_text,
        input_format="peak_pairs",
        metadata={},
        peaks=peaks,
    )


def build_llm_interpretation_demo_input(
    input_text: str,
    *,
    massbank_db: MassBankDatabase | None = None,
    kg_lookup_service: KgLookupService | None = None,
    top_n: int = 10,
    mz_tolerance: float = 0.01,
    min_matched_peaks: int = 1,
    ion_mode: str | None = None,
    precursor_mz: float | None = None,
    precursor_tolerance: float | None = None,
    kg_n: int = 3,
    kg_limit: int | None = 100,
) -> dict[str, Any]:
    """Build JSON-safe demo input for a future LLM interpretation function.

    The returned object contains:
    - original input text, parsed metadata, and parsed peaks
    - MassBank search result records
    - four KG table record lists keyed by KG source table name
    - compact KG evidence JSON already used by the interpretation service
    """
    parsed = parse_spectrum_input(input_text)
    db = massbank_db or MassBankDatabase()

    search_ion_mode = ion_mode
    if search_ion_mode is None:
        search_ion_mode = _metadata_value_case_insensitive(
            parsed.metadata,
            "Ion_mode",
        )

    search_precursor_mz = precursor_mz
    if search_precursor_mz is None:
        search_precursor_mz = _optional_float(
            _metadata_value_case_insensitive(parsed.metadata, "PrecursorMZ")
        )

    massbank_result_df = db.search_records_by_cosine_similarity_sql_dataframe(
        mz_list=parsed.mz_list,
        intensity_list=parsed.intensity_list,
        top_n=top_n,
        mz_tolerance=mz_tolerance,
        min_matched_peaks=min_matched_peaks,
        ion_mode=search_ion_mode,
        precursor_mz=search_precursor_mz,
        precursor_tolerance=precursor_tolerance,
    )

    kg_tables = _empty_kg_tables()

    if kg_lookup_service is not None:
        kg_tables = kg_lookup_service.search_by_massbank_records(
            massbank_result_df,
            inchikey_column="inchikey",
            top_n=top_n,
            kg_n=kg_n,
            limit=kg_limit,
        )

    kg_table_records = {
        key: _df_to_records(kg_tables.get(key))
        for key in KG_TABLE_KEYS
    }

    return {
        "input": {
            "text": parsed.input_text,
            "format": parsed.input_format,
            "metadata": _json_safe_value(parsed.metadata),
            "peaks": _df_to_records(parsed.peaks),
        },
        "search_parameters": {
            "top_n": int(top_n),
            "mz_tolerance": float(mz_tolerance),
            "min_matched_peaks": int(min_matched_peaks),
            "ion_mode": search_ion_mode,
            "precursor_mz": search_precursor_mz,
            "precursor_tolerance": precursor_tolerance,
            "kg_n": int(kg_n),
            "kg_limit": kg_limit,
        },
        "massbank_records": _df_to_records(massbank_result_df),
        "kg_tables": kg_table_records,
        "kg_evidence": build_kg_evidence_from_kg_data(kg_tables),
    }


def _looks_like_msp(
    input_text: str,
) -> bool:
    for line in input_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ":" in stripped:
            return True
    return False


def _parse_peak_lines(
    lines: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []

    for line_number, line in enumerate(lines, start=1):
        normalized = line.replace(",", " ")
        items = normalized.split()

        if len(items) < 2:
            continue

        try:
            mz = float(items[0])
            intensity = float(items[1])
        except ValueError:
            continue

        if not np.isfinite(mz) or not np.isfinite(intensity):
            continue

        rows.append(
            {
                "peak_index": len(rows),
                "mz": mz,
                "intensity": intensity,
            }
        )

    if not rows:
        raise ValueError("No valid m/z intensity peak rows were found.")

    return pd.DataFrame(rows)


def _empty_kg_tables() -> dict[str, pd.DataFrame]:
    return {
        key: pd.DataFrame()
        for key in KG_TABLE_KEYS
    }


def _df_to_records(
    df: pd.DataFrame | Any,
) -> list[dict[str, Any]]:
    if df is None:
        return []

    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)

    if df.empty:
        return []

    safe_df = df.copy()
    safe_df = safe_df.where(pd.notnull(safe_df), None)

    return _json_safe_value(safe_df.to_dict(orient="records"))


def _json_safe_value(
    value: Any,
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _json_safe_value(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _json_safe_value(item)
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            _json_safe_value(item)
            for item in value
        ]

    if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
        return None

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return float(value)

    if isinstance(value, np.bool_):
        return bool(value)

    return value


def _metadata_value_case_insensitive(
    metadata: dict[str, Any],
    key: str,
) -> str | None:
    normalized_key = key.lower().replace("_", "").replace(" ", "")

    for metadata_key, value in metadata.items():
        candidate = metadata_key.lower().replace("_", "").replace(" ", "")
        if candidate == normalized_key and value not in (None, ""):
            return str(value)

    return None


def _optional_float(
    value: Any,
) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None
