from __future__ import annotations

import json
from typing import Any

import pandas as pd


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


def _to_columnar(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert record rows to columnar table."""
    columns: list[str] = []
    seen: set[str] = set()

    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(key)

    table_rows = [
        [row.get(column, None) for column in columns]
        for row in rows
    ]

    return {
        "columns": columns,
        "rows": table_rows,
    }


def _group_activities(
    activities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Group activities by source, category, and function_label."""
    original_count = len(activities)
    grouped: dict[tuple[Any, Any, Any], dict[str, Any]] = {}

    for activity in activities:
        key = (
            activity.get("source"),
            activity.get("category"),
            activity.get("function_label"),
        )
        target_species = activity.get("target_species")

        if key not in grouped:
            grouped[key] = {
                "source": activity.get("source"),
                "category": activity.get("category"),
                "function_label": activity.get("function_label"),
                "target_species": [],
            }

        if target_species not in grouped[key]["target_species"]:
            grouped[key]["target_species"].append(target_species)

    grouped_rows = list(grouped.values())

    for row in grouped_rows:
        row["target_species"].sort(key=lambda value: (value is None, str(value)))

    grouped_rows = sorted(
        grouped_rows,
        key=lambda row: (
            str(row.get("category")),
            str(row.get("function_label")),
            str(row.get("source")),
        ),
    )

    return grouped_rows, original_count


def _get_value_inchikey(row: dict[str, Any]) -> str | None:
    """Get InChIKey value from common possible columns."""
    for key in ["value_inchikey", "inchikey"]:
        value = row.get(key)
        if value:
            return str(value)
    return None


def build_kg_evidence_from_kg_data(
    kg_data: dict[str, Any],
) -> dict[str, Any]:
    """Build compact KG evidence JSON from KG result tables.

    Input keys:
        pubchem_compound
        pubchem_pathway
        hmdb
        knapsack_activity
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
        compounds: list[dict[str, Any]] = []
        pathways: list[dict[str, Any]] = []
        diseases: list[dict[str, Any]] = []
        biospecimens: list[dict[str, Any]] = []
        organisms: list[dict[str, Any]] = []
        activities: list[dict[str, Any]] = []

        for row in pubchem_compound_rows:
            if _get_value_inchikey(row) != inchikey:
                continue

            compounds.append(
                {
                    "source": "PubChem",
                    "compound": row.get("pubchem_compound"),
                    "descriptor_type": row.get("descriptorType"),
                    "descriptor_value": row.get("descriptor_value"),
                }
            )

        for row in pubchem_pathway_rows:
            if _get_value_inchikey(row) != inchikey:
                continue

            pathways.append(
                {
                    "source": "PubChem",
                    "pathway": row.get("pathway"),
                    "label": row.get("pathway_label"),
                    "organism": row.get("pathway_organism"),
                }
            )

            if row.get("pathway_organism"):
                organisms.append(
                    {
                        "source": "PubChem",
                        "organism": row.get("pathway_organism"),
                        "label": row.get("pathway_organism"),
                    }
                )

        for row in hmdb_rows:
            if _get_value_inchikey(row) != inchikey:
                continue

            compounds.append(
                {
                    "source": "HMDB",
                    "compound": row.get("hmdb_metabolite"),
                    "accession": row.get("hmdb_accession"),
                    "label": row.get("hmdb_label"),
                    "formula": row.get("hmdb_formula"),
                    "average_mw": row.get("hmdb_avg_mw"),
                    "monoisotopic_mw": row.get("hmdb_mono_mw"),
                    "smiles": row.get("hmdb_smiles"),
                    "inchi": row.get("hmdb_inchi"),
                }
            )

            if row.get("hmdb_pathway") or row.get("hmdb_pathway_label"):
                pathways.append(
                    {
                        "source": "HMDB",
                        "pathway": row.get("hmdb_pathway"),
                        "label": row.get("hmdb_pathway_label"),
                    }
                )

            if row.get("hmdb_disease") or row.get("hmdb_disease_label"):
                diseases.append(
                    {
                        "source": "HMDB",
                        "disease": row.get("hmdb_disease"),
                        "label": row.get("hmdb_disease_label"),
                    }
                )

            if row.get("hmdb_biospecimen"):
                biospecimens.append(
                    {
                        "source": "HMDB",
                        "biospecimen": row.get("hmdb_biospecimen"),
                    }
                )

        for row in knapsack_rows:
            if _get_value_inchikey(row) != inchikey:
                continue

            compounds.append(
                {
                    "source": "KNApSAcK",
                    "knapsack_id": row.get("knapsack_id"),
                    "name": row.get("molecular_entity_name"),
                    "formula": row.get("molecular_formula"),
                    "molecular_weight": row.get("value_mw"),
                    "record": row.get("knapsack_record"),
                    "see_also": row.get("rdfs_seealso"),
                    "homepage": row.get("foaf_homepage"),
                }
            )

            activities.append(
                {
                    "source": "KNApSAcK",
                    "category": row.get("activity_category"),
                    "function_label": row.get("activity_function")
                    or row.get("activity_label"),
                    "target_species": row.get("activity_target_species"),
                }
            )

        compounds = _dedup_keep_order(compounds)
        diseases = _dedup_keep_order(diseases)
        pathways = _dedup_keep_order(pathways)
        biospecimens = _dedup_keep_order(biospecimens)
        organisms = _dedup_keep_order(organisms)

        grouped_activities, original_activity_count = _group_activities(
            activities
        )

        feature = {
            "inchikey": inchikey,
            "summary": {
                "compounds": len(compounds),
                "diseases": len(diseases),
                "pathways": len(pathways),
                "biospecimens": len(biospecimens),
                "organisms": len(organisms),
                "activities": {
                    "rows_original": original_activity_count,
                    "rows_grouped": len(grouped_activities),
                },
            },
            "entities": {
                "compounds": _to_columnar(compounds),
                "diseases": _to_columnar(diseases),
                "pathways": _to_columnar(pathways),
                "biospecimens": _to_columnar(biospecimens),
                "organisms": _to_columnar(organisms),
                "activities": _to_columnar(grouped_activities),
            },
        }

        features.append(feature)

    return {
        "metadata": {
            "source": "massbank_rdf_gui",
            "feature_count": len(features),
            "note": (
                "KG evidence generated from GUI KG result tables. "
                "Entity tables are stored in columnar form."
            ),
        },
        "features": features,
    }


def columnar_to_records(
    table: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert columnar table to records."""
    columns = table.get("columns", [])
    rows = table.get("rows", [])

    return [
        dict(zip(columns, row))
        for row in rows
    ]


def rehydrate_feature(
    feature: dict[str, Any],
) -> dict[str, Any]:
    """Convert columnar feature entities to record-style entities."""
    entities = feature.get("entities", {})

    return {
        "inchikey": feature.get("inchikey"),
        "summary": feature.get("summary"),
        "entities": {
            name: columnar_to_records(table)
            for name, table in entities.items()
        },
    }