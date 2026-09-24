from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
from typing import Iterable

import pandas as pd

from massbank_rdf.db.kg.database import KgDatabase
from massbank_rdf.services.kg.common import normalize_inchikey_values


SCORE_COLUMNS = [
    "pubchem_compound_count",
    "pubchem_descriptor_count",
    "pubchem_pathway_count",
    "hmdb_metabolite_count",
    "hmdb_pathway_count",
    "hmdb_disease_count",
    "hmdb_biospecimen_count",
    "knapsack_record_count",
    "knapsack_activity_count",
    "knapsack_category_count",
    "knapsack_function_count",
    "knapsack_target_species_count",
]


class KgMetadataScoreService:
    """Read precomputed InChIKey metadata counts from kg.sqlite3."""

    TABLE_NAME = "kg_metadata_scores"
    _build_lock = threading.Lock()

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or KgDatabase.DEFAULT_DB_PATH)

    def ensure_score_table(self) -> None:
        """Materialize the score table once for fast workflow lookups."""
        if not self.db_path.exists():
            return
        with self._build_lock:
            with sqlite3.connect(self.db_path) as conn:
                exists = conn.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = ?
                    """,
                    (self.TABLE_NAME,),
                ).fetchone()
                if exists:
                    return
                conn.executescript(_BUILD_SCORE_TABLE_SQL)

    def rebuild_score_table(self) -> None:
        """Rebuild scores after the normalized KG database changes."""
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)
        with self._build_lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(f"DROP TABLE IF EXISTS {self.TABLE_NAME}")
                conn.executescript(_BUILD_SCORE_TABLE_SQL)

    def scores_for_inchikeys(
        self,
        inchikeys: Iterable[str],
    ) -> pd.DataFrame:
        values = normalize_inchikey_values(list(inchikeys))
        columns = ["inchikey", "kg_metadata_count", *SCORE_COLUMNS]
        if not values or not self.db_path.exists():
            return pd.DataFrame(columns=columns)
        self.ensure_score_table()
        rows: list[pd.DataFrame] = []
        with sqlite3.connect(self.db_path) as conn:
            for start in range(0, len(values), 500):
                chunk = values[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows.append(
                    pd.read_sql_query(
                        f"""
                        SELECT {", ".join(columns)}
                        FROM {self.TABLE_NAME}
                        WHERE inchikey IN ({placeholders})
                        """,
                        conn,
                        params=chunk,
                    )
                )
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=columns)


_BUILD_SCORE_TABLE_SQL = f"""
CREATE TABLE {KgMetadataScoreService.TABLE_NAME} AS
WITH
pc AS (
    SELECT
        pci.kg_inchikey_id,
        COUNT(DISTINCT pci.pubchem_compound_id) AS pubchem_compound_count,
        COUNT(DISTINCT pcd.id) AS pubchem_descriptor_count,
        COUNT(DISTINCT pcp.pubchem_pathway_id) AS pubchem_pathway_count
    FROM pubchem_compound_inchikeys pci
    LEFT JOIN pubchem_compound_descriptors pcd
        ON pcd.pubchem_compound_id = pci.pubchem_compound_id
    LEFT JOIN pubchem_compound_pathways pcp
        ON pcp.pubchem_compound_id = pci.pubchem_compound_id
    GROUP BY pci.kg_inchikey_id
),
hmdb AS (
    SELECT
        hmi.kg_inchikey_id,
        COUNT(DISTINCT hmi.hmdb_metabolite_id) AS hmdb_metabolite_count,
        COUNT(DISTINCT hmp.hmdb_pathway_id) AS hmdb_pathway_count,
        COUNT(DISTINCT hmd.hmdb_disease_id) AS hmdb_disease_count,
        COUNT(DISTINCT hmb.hmdb_biospecimen_id) AS hmdb_biospecimen_count
    FROM hmdb_metabolite_inchikeys hmi
    LEFT JOIN hmdb_metabolite_pathways hmp
        ON hmp.hmdb_metabolite_id = hmi.hmdb_metabolite_id
    LEFT JOIN hmdb_metabolite_diseases hmd
        ON hmd.hmdb_metabolite_id = hmi.hmdb_metabolite_id
    LEFT JOIN hmdb_metabolite_biospecimens hmb
        ON hmb.hmdb_metabolite_id = hmi.hmdb_metabolite_id
    GROUP BY hmi.kg_inchikey_id
),
ks AS (
    SELECT
        kri.kg_inchikey_id,
        COUNT(DISTINCT kri.knapsack_record_id) AS knapsack_record_count,
        COUNT(DISTINCT kra.knapsack_activity_id) AS knapsack_activity_count,
        COUNT(DISTINCT krac.category_id) AS knapsack_category_count,
        COUNT(DISTINCT kraf.function_id) AS knapsack_function_count,
        COUNT(DISTINCT krts.target_species_id) AS knapsack_target_species_count
    FROM knapsack_record_inchikeys kri
    LEFT JOIN knapsack_record_activities kra
        ON kra.knapsack_record_id = kri.knapsack_record_id
    LEFT JOIN knapsack_record_activity_categories krac
        ON krac.knapsack_record_id = kri.knapsack_record_id
    LEFT JOIN knapsack_record_activity_functions kraf
        ON kraf.knapsack_record_id = kri.knapsack_record_id
    LEFT JOIN knapsack_record_target_species krts
        ON krts.knapsack_record_id = kri.knapsack_record_id
    GROUP BY kri.kg_inchikey_id
)
SELECT
    k.inchikey,
    (
        COALESCE(pc.pubchem_compound_count, 0)
        + COALESCE(pc.pubchem_descriptor_count, 0)
        + COALESCE(pc.pubchem_pathway_count, 0)
        + COALESCE(hmdb.hmdb_metabolite_count, 0)
        + COALESCE(hmdb.hmdb_pathway_count, 0)
        + COALESCE(hmdb.hmdb_disease_count, 0)
        + COALESCE(hmdb.hmdb_biospecimen_count, 0)
        + COALESCE(ks.knapsack_record_count, 0)
        + COALESCE(ks.knapsack_activity_count, 0)
        + COALESCE(ks.knapsack_category_count, 0)
        + COALESCE(ks.knapsack_function_count, 0)
        + COALESCE(ks.knapsack_target_species_count, 0)
    ) AS kg_metadata_count,
    COALESCE(pc.pubchem_compound_count, 0) AS pubchem_compound_count,
    COALESCE(pc.pubchem_descriptor_count, 0) AS pubchem_descriptor_count,
    COALESCE(pc.pubchem_pathway_count, 0) AS pubchem_pathway_count,
    COALESCE(hmdb.hmdb_metabolite_count, 0) AS hmdb_metabolite_count,
    COALESCE(hmdb.hmdb_pathway_count, 0) AS hmdb_pathway_count,
    COALESCE(hmdb.hmdb_disease_count, 0) AS hmdb_disease_count,
    COALESCE(hmdb.hmdb_biospecimen_count, 0) AS hmdb_biospecimen_count,
    COALESCE(ks.knapsack_record_count, 0) AS knapsack_record_count,
    COALESCE(ks.knapsack_activity_count, 0) AS knapsack_activity_count,
    COALESCE(ks.knapsack_category_count, 0) AS knapsack_category_count,
    COALESCE(ks.knapsack_function_count, 0) AS knapsack_function_count,
    COALESCE(ks.knapsack_target_species_count, 0) AS knapsack_target_species_count
FROM kg_inchikeys k
LEFT JOIN pc ON pc.kg_inchikey_id = k.id
LEFT JOIN hmdb ON hmdb.kg_inchikey_id = k.id
LEFT JOIN ks ON ks.kg_inchikey_id = k.id;

CREATE UNIQUE INDEX idx_kg_metadata_scores_inchikey
ON {KgMetadataScoreService.TABLE_NAME}(inchikey);

CREATE INDEX idx_kg_metadata_scores_total
ON {KgMetadataScoreService.TABLE_NAME}(kg_metadata_count DESC);
"""
