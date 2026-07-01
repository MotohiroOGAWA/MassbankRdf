from __future__ import annotations

import json
from typing import Any

import pandas as pd


PREFIXES = {
    "pc_c": "http://rdf.ncbi.nlm.nih.gov/pubchem/compound/",
    "pc_p": "http://rdf.ncbi.nlm.nih.gov/pubchem/pathway/",
    "pc_tax": "http://rdf.ncbi.nlm.nih.gov/pubchem/taxonomy/",
    "cheminf": "http://semanticscience.org/resource/",
    "hmdb_res": "https://hmdb.ca/resource/",
    "hmdb_met": "https://hmdb.ca/metabolites/",
    "ks_act": "http://purl.jp/knapsack/activity#",
}

SOURCES = {
    "pc": "PubChem",
    "hmdb": "HMDB",
    "ks": "KNApSAcK",
}


def _df_to_records(
    df: pd.DataFrame | Any,
) -> list[dict[str, Any]]:
    """Convert DataFrame-like value to JSON-safe records."""
    if df is None:
        return []

    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)

    if df.empty:
        return []

    safe_df = df.copy()
    safe_df = safe_df.where(pd.notnull(safe_df), None)

    return safe_df.to_dict(orient="records")


def _dedup_keep_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove exact duplicated rows while preserving order."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for row in rows:
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(row)

    return result


def _compact_uri(value: Any, prefix_key: str) -> Any:
    if value is None:
        return None

    text = str(value)
    prefix = PREFIXES[prefix_key]

    if text.startswith(prefix):
        return text[len(prefix):]

    return text


def _split_pipe(value: Any) -> list[str]:
    if value is None:
        return []

    parts = [
        part.strip()
        for part in str(value).split("|")
    ]
    return [part for part in parts if part]


def _append_unique(items: list[Any], value: Any) -> None:
    if value is None or value == "":
        return

    if value not in items:
        items.append(value)


def _clean_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if value not in (None, "", [], {})
    }


def _get_value_inchikey(row: dict[str, Any]) -> str | None:
    """Get InChIKey value from common possible columns."""
    for key in ["value_inchikey", "inchikey"]:
        value = row.get(key)
        if value:
            return str(value)
    return None


def _group_pubchem_compounds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        compound_id = _compact_uri(row.get("pubchem_compound"), "pc_c")
        if not compound_id:
            continue

        if compound_id not in grouped:
            grouped[compound_id] = {
                "id": compound_id,
                "descriptors": {},
            }

        descriptor_type = _compact_uri(row.get("descriptorType"), "cheminf")
        descriptor_value = row.get("descriptor_value")

        if descriptor_type and descriptor_value not in (None, ""):
            values = grouped[compound_id]["descriptors"].setdefault(
                descriptor_type,
                [],
            )
            _append_unique(values, descriptor_value)

    return list(grouped.values())


def _group_pubchem_pathways(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        pathway_id = _compact_uri(row.get("pathway"), "pc_p")
        if not pathway_id:
            continue

        if pathway_id not in grouped:
            grouped[pathway_id] = _clean_dict(
                {
                    "id": pathway_id,
                    "label": row.get("pathway_label"),
                    "organism": _compact_uri(
                        row.get("pathway_organism"),
                        "pc_tax",
                    ),
                    "compound": _compact_uri(
                        row.get("pubchem_compound"),
                        "pc_c",
                    ),
                }
            )

    return list(grouped.values())


def _group_pubchem_organisms(pathways: list[dict[str, Any]]) -> list[dict[str, Any]]:
    organisms: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pathway in pathways:
        organism = pathway.get("organism")
        if organism and organism not in seen:
            seen.add(organism)
            organisms.append({"id": organism})

    return organisms


def _group_hmdb_compounds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        accession = row.get("hmdb_accession")
        compound_id = _compact_uri(row.get("hmdb_metabolite"), "hmdb_res")
        key = str(accession or compound_id or len(grouped))

        if key not in grouped:
            grouped[key] = _clean_dict(
                {
                    "id": compound_id,
                    "accession": accession,
                    "label": row.get("hmdb_label"),
                    "formula": row.get("hmdb_formula"),
                    "average_mw": row.get("hmdb_avg_mw"),
                    "monoisotopic_mw": row.get("hmdb_mono_mw"),
                    "smiles": row.get("hmdb_smiles"),
                    "inchi": row.get("hmdb_inchi"),
                }
            )

    return list(grouped.values())


def _group_hmdb_pathways(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pathways: list[dict[str, Any]] = []

    for row in rows:
        pathway_ids = _split_pipe(row.get("hmdb_pathway"))
        pathway_labels = _split_pipe(row.get("hmdb_pathway_label"))

        if not pathway_ids and pathway_labels:
            pathway_ids = [None] * len(pathway_labels)

        for index, pathway_id in enumerate(pathway_ids):
            label = pathway_labels[index] if index < len(pathway_labels) else None
            pathways.append(
                _clean_dict(
                    {
                        "id": _compact_uri(pathway_id, "hmdb_res")
                        if pathway_id
                        else None,
                        "label": label,
                    }
                )
            )

    return _dedup_keep_order(pathways)


def _group_hmdb_diseases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diseases: list[dict[str, Any]] = []

    for row in rows:
        disease_ids = _split_pipe(row.get("hmdb_disease"))
        disease_labels = _split_pipe(row.get("hmdb_disease_label"))

        if not disease_ids and disease_labels:
            disease_ids = [None] * len(disease_labels)

        for index, disease_id in enumerate(disease_ids):
            label = disease_labels[index] if index < len(disease_labels) else None
            diseases.append(
                _clean_dict(
                    {
                        "id": _compact_uri(disease_id, "hmdb_res")
                        if disease_id
                        else None,
                        "label": label,
                    }
                )
            )

    return _dedup_keep_order(diseases)


def _group_hmdb_biospecimens(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    biospecimens: list[dict[str, Any]] = []

    for row in rows:
        for biospecimen in _split_pipe(row.get("hmdb_biospecimen")):
            biospecimens.append({"id": _compact_uri(biospecimen, "hmdb_res")})

    return _dedup_keep_order(biospecimens)


def _group_knapsack_compounds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        knapsack_id = row.get("knapsack_id")
        key = str(knapsack_id or len(grouped))

        if key not in grouped:
            grouped[key] = _clean_dict(
                {
                    "id": knapsack_id,
                    "name": row.get("molecular_entity_name")
                    or row.get("activity_record_label"),
                    "formula": row.get("molecular_formula"),
                    "molecular_weight": row.get("value_mw"),
                    "see_also": row.get("rdfs_seealso"),
                    "homepage": row.get("foaf_homepage"),
                }
            )

    return list(grouped.values())


def _group_knapsack_activities(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    original_count = len(rows)
    grouped: dict[tuple[Any, Any, Any], dict[str, Any]] = {}

    for row in rows:
        label = row.get("activity_label") or row.get("activity_function")
        key = (
            label,
            row.get("activity_category"),
            row.get("activity_target_species"),
        )

        if key not in grouped:
            grouped[key] = _clean_dict(
                {
                    "label": label,
                    "category": _split_pipe(row.get("activity_category")),
                    "target_species": row.get("activity_target_species"),
                    "uri": [],
                }
            )

        activity_uri = _compact_uri(row.get("activity"), "ks_act")
        if activity_uri:
            grouped[key].setdefault("uri", [])
            _append_unique(grouped[key]["uri"], activity_uri)

    activities = sorted(
        grouped.values(),
        key=lambda row: (
            str(row.get("label")),
            str(row.get("target_species")),
        ),
    )

    return activities, original_count


def _count_source_entities(value: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(rows) for rows in value.values())


def build_kg_evidence_from_kg_data(
    kg_data: dict[str, Any],
) -> dict[str, Any]:
    """Build compact KG evidence JSON from KG result tables.

    The output is a static nested JSON schema. Source names and URI prefixes are
    stored once in metadata, and feature entities are grouped under source keys.
    """
    pubchem_compound_rows = _df_to_records(kg_data.get("pubchem_compound"))
    pubchem_pathway_rows = _df_to_records(kg_data.get("pubchem_pathway"))
    hmdb_rows = _df_to_records(kg_data.get("hmdb"))
    knapsack_rows = _df_to_records(kg_data.get("knapsack_activity"))

    inchikeys: list[str] = []

    for rows in [
        pubchem_compound_rows,
        pubchem_pathway_rows,
        hmdb_rows,
        knapsack_rows,
    ]:
        for row in rows:
            inchikey = _get_value_inchikey(row)
            if inchikey and inchikey not in inchikeys:
                inchikeys.append(inchikey)

    features: list[dict[str, Any]] = []

    for inchikey in inchikeys:
        pc_compound_rows = [
            row
            for row in pubchem_compound_rows
            if _get_value_inchikey(row) == inchikey
        ]
        pc_pathway_rows = [
            row
            for row in pubchem_pathway_rows
            if _get_value_inchikey(row) == inchikey
        ]
        hmdb_feature_rows = [
            row
            for row in hmdb_rows
            if _get_value_inchikey(row) == inchikey
        ]
        ks_rows = [
            row
            for row in knapsack_rows
            if _get_value_inchikey(row) == inchikey
        ]

        pc_compounds = _group_pubchem_compounds(pc_compound_rows)
        pc_pathways = _group_pubchem_pathways(pc_pathway_rows)
        pc_organisms = _group_pubchem_organisms(pc_pathways)
        hmdb_compounds = _group_hmdb_compounds(hmdb_feature_rows)
        hmdb_pathways = _group_hmdb_pathways(hmdb_feature_rows)
        hmdb_diseases = _group_hmdb_diseases(hmdb_feature_rows)
        hmdb_biospecimens = _group_hmdb_biospecimens(hmdb_feature_rows)
        ks_compounds = _group_knapsack_compounds(ks_rows)
        ks_activities, original_activity_count = _group_knapsack_activities(ks_rows)

        compounds = {
            "pc": pc_compounds,
            "hmdb": hmdb_compounds,
            "ks": ks_compounds,
        }
        pathways = {
            "pc": pc_pathways,
            "hmdb": hmdb_pathways,
        }
        diseases = {
            "hmdb": hmdb_diseases,
        }
        biospecimens = {
            "hmdb": hmdb_biospecimens,
        }
        organisms = {
            "pc": pc_organisms,
        }
        activities = {
            "ks": ks_activities,
        }

        feature = {
            "inchikey": inchikey,
            "summary": {
                "compounds": _count_source_entities(compounds),
                "diseases": _count_source_entities(diseases),
                "pathways": _count_source_entities(pathways),
                "biospecimens": _count_source_entities(biospecimens),
                "organisms": _count_source_entities(organisms),
                "activities": {
                    "rows_original": original_activity_count,
                    "rows_grouped": _count_source_entities(activities),
                },
            },
            "entities": {
                "compounds": compounds,
                "diseases": diseases,
                "pathways": pathways,
                "biospecimens": biospecimens,
                "organisms": organisms,
                "activities": activities,
            },
        }

        features.append(feature)

    return {
        "metadata": {
            "source": "massbank_rdf",
            "feature_count": len(features),
            "sources": SOURCES,
            "prefixes": PREFIXES,
            "note": (
                "KG evidence generated from KG lookup results. "
                "URI prefixes and source labels are stored in metadata; "
                "entities are grouped by source to reduce repeated text."
            ),
        },
        "features": features,
    }


def columnar_to_records(
    table: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert legacy columnar table to records."""
    columns = table.get("columns", [])
    rows = table.get("rows", [])

    return [
        dict(zip(columns, row))
        for row in rows
    ]


def rehydrate_feature(
    feature: dict[str, Any],
) -> dict[str, Any]:
    """Return feature entities as record-style JSON.

    Older payloads used columnar objects with columns/rows. New payloads store
    entities as nested JSON grouped by source. Both forms are accepted.
    """
    entities = feature.get("entities", {})
    rehydrated: dict[str, Any] = {}

    if not isinstance(entities, dict):
        entities = {}

    for name, value in entities.items():
        if isinstance(value, dict) and "columns" in value and "rows" in value:
            rehydrated[name] = columnar_to_records(value)
        else:
            rehydrated[name] = value

    return {
        "inchikey": feature.get("inchikey"),
        "summary": feature.get("summary"),
        "entities": rehydrated,
    }
