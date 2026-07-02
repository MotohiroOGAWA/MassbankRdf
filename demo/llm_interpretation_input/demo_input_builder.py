from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from massbank_rdf.db.massbank.database import MassBankDatabase
from massbank_rdf.services.kg.kg_lookup_service import KgLookupService
from massbank_rdf.services.kg.common import (
    extract_inchikey_value,
    normalize_inchikey_values,
)
from massbank_rdf.services.kg.query_builders.pubchem_query_builder import (
    build_pubchem_compound_query,
    build_pubchem_pathway_query,
)
from massbank_rdf.services.kg.query_builders.hmdb_query_builder import (
    build_hmdb_query,
)
from massbank_rdf.services.kg.query_builders.knapsack_query_builder import (
    build_knapsack_activity_query,
)

from massbank_rdf.services.llm_interpretation.kg_evidence_builder import (
    PREFIXES,
    SOURCES,
    build_kg_evidence_from_kg_data,
)

from massbank_rdf.models import MSPRecord


KG_TABLE_KEYS = [
    "pubchem_compound",
    "pubchem_pathway",
    "hmdb",
    "knapsack_activity",
]

DEFAULT_PATHWAY_PER_INCHIKEY_LIMIT = 100

# Human-readable labels for the PubChem descriptor types requested in
# build_pubchem_compound_query. Labels are taken from the CHEMINF ontology
# (verified via EBI OLS):
#   CHEMINF_000335 = molecular formula (PubChem)
#   CHEMINF_000376 = canonical SMILES (OEChem)
#   CHEMINF_000113 = InChI descriptor
#   CHEMINF_000334 = molecular weight (PubChem)
CHEMINF_DESCRIPTOR_LABELS = {
    "CHEMINF_000335": "Molecular Formula",
    "CHEMINF_000376": "Canonical SMILES",
    "CHEMINF_000113": "InChI",
    "CHEMINF_000334": "Molecular Weight",
}


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
    pathway_per_inchikey_limit: int = DEFAULT_PATHWAY_PER_INCHIKEY_LIMIT,
) -> dict[str, Any]:
    """Build JSON-safe demo input for a future LLM interpretation function.

    The returned object contains:
    - original input text, parsed metadata, and parsed peaks
    - MassBank search result records
    - compact KG evidence JSON for downstream LLM interpretation
    - an LLM-friendly reshaped view of the KG evidence
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

    if kg_lookup_service is not None:
        kg_evidence = build_kg_evidence_with_pathway_limit(
            kg_lookup_service,
            massbank_result_df,
            inchikey_column="inchikey",
            top_n=top_n,
            kg_n=kg_n,
            limit=kg_limit,
            pathway_per_inchikey_limit=pathway_per_inchikey_limit,
        )
    else:
        kg_evidence = build_kg_evidence_from_kg_data(_empty_kg_tables())

    kg_evidence_llm = reshape_kg_evidence_for_llm(
        kg_evidence,
        massbank_result_df,
        inchikey_column="inchikey",
    )

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
            "pathway_per_inchikey_limit": int(pathway_per_inchikey_limit),
        },
        "massbank_records": _df_to_records(massbank_result_df),
        "kg_evidence": kg_evidence,
        "kg_evidence_llm": kg_evidence_llm,
    }


def fetch_kg_data_with_pathway_limit(
    kg_lookup_service: KgLookupService,
    inchikeys: list[str],
    *,
    limit: int | None = 100,
    pathway_per_inchikey_limit: int = DEFAULT_PATHWAY_PER_INCHIKEY_LIMIT,
) -> dict[str, pd.DataFrame]:
    """Fetch KG tables, capping PubChem pathways per InChIKey.

    Non-pathway sources (PubChem compound, HMDB, KNApSAcK) are fetched with the
    usual combined queries. PubChem pathways are fetched one InChIKey at a time
    so each InChIKey can return up to ``pathway_per_inchikey_limit`` pathways,
    instead of sharing a single combined ``LIMIT`` where one compound could use
    up the whole budget.
    """
    inchikeys = normalize_inchikey_values(inchikeys)

    if not inchikeys:
        return _empty_kg_tables()

    pubchem_client = kg_lookup_service.pubchem_client
    hmdb_client = kg_lookup_service.hmdb_client
    knapsack_client = kg_lookup_service.knapsack_client

    compound_df = pubchem_client.select(
        build_pubchem_compound_query(inchikeys, limit=limit)
    )
    hmdb_df = hmdb_client.select(
        build_hmdb_query(inchikeys, limit=limit)
    )
    knapsack_df = knapsack_client.select(
        build_knapsack_activity_query(
            inchikeys,
            use_from_graph=knapsack_client.use_from_graph,
            graph_iri=knapsack_client.graph_iri or "",
            limit=limit,
        )
    )
    pathway_df = _fetch_pubchem_pathways_per_inchikey(
        pubchem_client,
        inchikeys,
        pathway_per_inchikey_limit=pathway_per_inchikey_limit,
    )

    return {
        "pubchem_compound": _normalize_value_inchikey_column(compound_df),
        "pubchem_pathway": _normalize_value_inchikey_column(pathway_df),
        "hmdb": _normalize_value_inchikey_column(hmdb_df),
        "knapsack_activity": _normalize_value_inchikey_column(knapsack_df),
    }


def _fetch_pubchem_pathways_per_inchikey(
    pubchem_client: Any,
    inchikeys: list[str],
    *,
    pathway_per_inchikey_limit: int,
) -> pd.DataFrame:
    """Fetch PubChem pathways one InChIKey at a time and concatenate them."""
    pathway_columns = [
        "value_inchikey",
        "pubchem_compound",
        "pathway",
        "pathway_label",
        "pathway_organism",
    ]

    frames: list[pd.DataFrame] = []

    for inchikey in inchikeys:
        query = build_pubchem_pathway_query(
            [inchikey],
            limit=pathway_per_inchikey_limit,
        )
        frames.append(pubchem_client.select(query))

    non_empty = [frame for frame in frames if not frame.empty]

    if not non_empty:
        return pd.DataFrame(columns=pathway_columns)

    return pd.concat(non_empty, ignore_index=True)


def build_kg_evidence_with_pathway_limit(
    kg_lookup_service: KgLookupService,
    massbank_records: pd.DataFrame,
    *,
    inchikey_column: str = "inchikey",
    top_n: int = 10,
    kg_n: int = 3,
    limit: int | None = 100,
    pathway_per_inchikey_limit: int = DEFAULT_PATHWAY_PER_INCHIKEY_LIMIT,
) -> dict[str, Any]:
    """Build compact KG evidence with a per-InChIKey PubChem pathway limit."""
    inchikeys = kg_lookup_service.extract_inchikeys_from_massbank_records(
        massbank_records,
        inchikey_column=inchikey_column,
        top_n=top_n,
        kg_n=kg_n,
    )
    kg_data = fetch_kg_data_with_pathway_limit(
        kg_lookup_service,
        inchikeys,
        limit=limit,
        pathway_per_inchikey_limit=pathway_per_inchikey_limit,
    )
    return build_kg_evidence_from_kg_data(kg_data)


def _normalize_value_inchikey_column(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize the ``value_inchikey`` column to a bare InChIKey string."""
    df = df.copy()

    if "value_inchikey" in df.columns:
        df["value_inchikey"] = df["value_inchikey"].apply(extract_inchikey_value)

    return df


def reshape_kg_evidence_for_llm(
    kg_evidence: dict[str, Any],
    massbank_records: pd.DataFrame | None = None,
    *,
    inchikey_column: str = "inchikey",
) -> dict[str, Any]:
    """Reshape compact KG evidence into an LLM-friendly, self-describing form.

    The compact evidence is optimized for token count: entities are nested by
    entity type and then by source code (``pc``/``hmdb``/``ks``), and URIs are
    stored as prefix-stripped ids that must be joined with a prefix table.

    This view instead:
    - flattens the ``entity type x source`` nesting into flat lists where every
      item carries an explicit ``source`` label (e.g. ``"PubChem"``),
    - expands compacted ids back to full URIs so no prefix table is needed,
    - maps PubChem descriptor types to human-readable labels,
    - rephrases the KNApSAcK activity counts into plain language,
    - attaches a per-InChIKey MassBank hit summary when ``massbank_records`` is
      given, so each feature is self-contained.

    The goal is a structure that a smaller / weaker LLM is less likely to
    misread. The original compact evidence is left unchanged.
    """
    features = kg_evidence.get("features", [])
    if not isinstance(features, list):
        features = []

    massbank_summaries = _build_massbank_summaries(
        massbank_records,
        inchikey_column=inchikey_column,
    )

    reshaped_features = [
        _reshape_feature(feature, massbank_summaries)
        for feature in features
        if isinstance(feature, dict)
    ]

    original_metadata = kg_evidence.get("metadata", {})
    if not isinstance(original_metadata, dict):
        original_metadata = {}

    return {
        "metadata": {
            "source": original_metadata.get("source", "massbank_rdf"),
            "feature_count": len(reshaped_features),
            "description": (
                "LLM-friendly view of KG evidence. Each entity is listed in a "
                "flat array and states its source database. URIs are fully "
                "expanded, so no prefix table lookup is needed."
            ),
        },
        "features": reshaped_features,
    }


def _reshape_feature(
    feature: dict[str, Any],
    massbank_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entities = feature.get("entities", {})
    if not isinstance(entities, dict):
        entities = {}

    summary = feature.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}

    inchikey = feature.get("inchikey")
    normalized_inchikey = extract_inchikey_value(inchikey)

    reshaped: dict[str, Any] = {
        "inchikey": inchikey,
    }

    massbank_summary = massbank_summaries.get(normalized_inchikey)
    if massbank_summary:
        reshaped["massbank"] = massbank_summary

    reshaped.update({
        "summary": _reshape_summary(summary),
        "compounds": _reshape_compounds(entities.get("compounds", {})),
        "pathways": _reshape_pathways(entities.get("pathways", {})),
        "diseases": _reshape_labeled(entities.get("diseases", {}), "hmdb_res"),
        "biospecimens": _reshape_labeled(
            entities.get("biospecimens", {}), "hmdb_res"
        ),
        "organisms": _reshape_organisms(entities.get("organisms", {})),
        "activities": _reshape_activities(entities.get("activities", {})),
    })

    return reshaped


def _build_massbank_summaries(
    massbank_records: pd.DataFrame | None,
    *,
    inchikey_column: str = "inchikey",
) -> dict[str, dict[str, Any]]:
    """Summarize MassBank hits per normalized InChIKey.

    Returns a mapping ``normalized_inchikey -> summary`` where the summary
    anchors the KG evidence to the MassBank identification (compound name, best
    cosine score, adducts, ion modes, and the number of matched spectra).
    """
    if massbank_records is None:
        return {}

    if not isinstance(massbank_records, pd.DataFrame) or massbank_records.empty:
        return {}

    if inchikey_column not in massbank_records.columns:
        return {}

    summaries: dict[str, dict[str, Any]] = {}

    data = massbank_records.copy()
    data["_normalized_inchikey"] = data[inchikey_column].apply(
        extract_inchikey_value
    )

    for normalized_inchikey, group in data.groupby("_normalized_inchikey"):
        if not normalized_inchikey:
            continue

        summaries[str(normalized_inchikey)] = _summarize_massbank_group(group)

    return summaries


def _summarize_massbank_group(
    group: pd.DataFrame,
) -> dict[str, Any]:
    """Build a single MassBank hit summary from rows sharing an InChIKey."""
    sort_columns = [
        column
        for column in ["cosine_score", "matched_peak_count"]
        if column in group.columns
    ]

    if sort_columns:
        group = group.sort_values(sort_columns, ascending=False)

    best = group.iloc[0]

    summary = {
        "compound_name": _first_non_empty(group, "name"),
        "formula": _first_non_empty(group, "formula"),
        "best_accession": _clean_scalar(best.get("accession_id")),
        "best_cosine_score": _clean_scalar(best.get("cosine_score")),
        "spectrum_count": int(len(group)),
        "adducts": _unique_values(group, "precursor_type"),
        "ion_modes": _unique_values(group, "ion_mode"),
    }

    return _drop_empty(summary)


def _first_non_empty(
    group: pd.DataFrame,
    column: str,
) -> Any:
    if column not in group.columns:
        return None

    for value in group[column].tolist():
        cleaned = _clean_scalar(value)
        if cleaned not in (None, ""):
            return cleaned

    return None


def _unique_values(
    group: pd.DataFrame,
    column: str,
) -> list[Any]:
    if column not in group.columns:
        return []

    values: list[Any] = []

    for value in group[column].tolist():
        cleaned = _clean_scalar(value)
        if cleaned in (None, ""):
            continue
        if cleaned not in values:
            values.append(cleaned)

    return values


def _clean_scalar(
    value: Any,
) -> Any:
    """Convert a possibly-numpy/NaN scalar to a JSON-safe Python value."""
    if value is None:
        return None

    if isinstance(value, (list, dict, tuple)):
        return value

    if pd.isna(value):
        return None

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return float(value)

    if isinstance(value, np.bool_):
        return bool(value)

    return value


def _reshape_summary(
    summary: dict[str, Any],
) -> dict[str, Any]:
    activities = summary.get("activities", {})
    if not isinstance(activities, dict):
        activities = {}

    rows_original = activities.get("rows_original", 0)
    rows_grouped = activities.get("rows_grouped", 0)

    return {
        "compound_count": summary.get("compounds", 0),
        "disease_count": summary.get("diseases", 0),
        "pathway_count": summary.get("pathways", 0),
        "biospecimen_count": summary.get("biospecimens", 0),
        "organism_count": summary.get("organisms", 0),
        "activity_note": (
            f"{rows_original} KNApSAcK activity rows were grouped into "
            f"{rows_grouped} unique activities. Row count alone does not "
            f"indicate evidence strength."
        ),
    }


def _iter_source_items(
    container: Any,
):
    """Yield ``(source_code, item)`` pairs from a source-keyed entity dict."""
    if not isinstance(container, dict):
        return

    for source_code, items in container.items():
        if not isinstance(items, list):
            continue

        for item in items:
            if isinstance(item, dict):
                yield source_code, item


def _reshape_compounds(
    container: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for source_code, item in _iter_source_items(container):
        record: dict[str, Any] = {"source": SOURCES.get(source_code, source_code)}

        if source_code == "pc":
            record["id"] = _expand_uri(item.get("id"), "pc_c")
            descriptors = item.get("descriptors", {})
            if isinstance(descriptors, dict) and descriptors:
                record["descriptors"] = [
                    {
                        "type": CHEMINF_DESCRIPTOR_LABELS.get(
                            descriptor_type,
                            _expand_uri(descriptor_type, "cheminf"),
                        ),
                        "values": values,
                    }
                    for descriptor_type, values in descriptors.items()
                ]
        elif source_code == "hmdb":
            record["id"] = _expand_uri(item.get("id"), "hmdb_res")
            for key in [
                "accession",
                "label",
                "formula",
                "average_mw",
                "monoisotopic_mw",
                "smiles",
                "inchi",
            ]:
                record[key] = item.get(key)
        elif source_code == "ks":
            record["id"] = item.get("id")
            for key in [
                "name",
                "formula",
                "molecular_weight",
                "see_also",
                "homepage",
            ]:
                record[key] = item.get(key)
        else:
            record.update(item)

        result.append(_drop_empty(record))

    return result


def _reshape_pathways(
    container: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for source_code, item in _iter_source_items(container):
        record: dict[str, Any] = {"source": SOURCES.get(source_code, source_code)}

        if source_code == "pc":
            record["id"] = _expand_uri(item.get("id"), "pc_p")
            record["label"] = item.get("label")
            record["organism"] = _expand_uri(item.get("organism"), "pc_tax")
            record["compound"] = _expand_uri(item.get("compound"), "pc_c")
        elif source_code == "hmdb":
            record["id"] = _expand_uri(item.get("id"), "hmdb_res")
            record["label"] = item.get("label")
        else:
            record.update(item)

        result.append(_drop_empty(record))

    return result


def _reshape_labeled(
    container: Any,
    prefix_key: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for source_code, item in _iter_source_items(container):
        record = {
            "source": SOURCES.get(source_code, source_code),
            "id": _expand_uri(item.get("id"), prefix_key),
            "label": item.get("label"),
        }
        result.append(_drop_empty(record))

    return result


def _reshape_organisms(
    container: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for source_code, item in _iter_source_items(container):
        record = {
            "source": SOURCES.get(source_code, source_code),
            "id": _expand_uri(item.get("id"), "pc_tax"),
        }
        result.append(_drop_empty(record))

    return result


def _reshape_activities(
    container: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for source_code, item in _iter_source_items(container):
        record: dict[str, Any] = {
            "source": SOURCES.get(source_code, source_code),
            "label": item.get("label"),
            "category": item.get("category"),
            "target_species": item.get("target_species"),
        }

        uris = item.get("uri")
        if isinstance(uris, list) and uris:
            record["references"] = [
                _expand_uri(uri, "ks_act")
                for uri in uris
            ]

        result.append(_drop_empty(record))

    return result


def _expand_uri(
    value: Any,
    prefix_key: str,
) -> Any:
    """Expand a prefix-stripped id back to a full URI.

    Values that are already absolute URIs or that are not plain strings are
    returned unchanged.
    """
    if value in (None, ""):
        return value

    text = str(value)

    if text.startswith("http://") or text.startswith("https://"):
        return text

    return PREFIXES[prefix_key] + text


def _drop_empty(
    record: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if value not in (None, "", [], {})
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
