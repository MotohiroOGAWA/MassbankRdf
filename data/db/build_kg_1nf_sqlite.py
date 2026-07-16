from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DB = DEFAULT_BASE_DIR / "kg.sqlite3"
DEFAULT_OUTPUT_DB = DEFAULT_BASE_DIR / "kg_1nf.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a first-normal-form-like KG SQLite database from the "
            "normalized KG SQLite database. Each output source table has one "
            "row per InChIKey and multi-value cells are joined with '|'."
        )
    )
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--output-db", type=Path, default=DEFAULT_OUTPUT_DB)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output database if it already exists.",
    )
    return parser.parse_args()


def pipe_join(values: Iterable[object]) -> str | None:
    unique_values = {
        str(value).strip()
        for value in values
        if value is not None and str(value).strip()
    }
    if not unique_values:
        return None
    return "|".join(sorted(unique_values))


def fetch_inchikeys(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT inchikey FROM kg_inchikeys ORDER BY inchikey"
    ).fetchall()
    return [row["inchikey"] for row in rows]


def collect_values(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[object, ...] = (),
) -> dict[str, str]:
    values_by_inchikey: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute(query, params):
        inchikey = row["inchikey"]
        value = row["value"]
        if value is not None and str(value).strip():
            values_by_inchikey[inchikey].add(str(value).strip())
    return {
        inchikey: pipe_join(values)
        for inchikey, values in values_by_inchikey.items()
    }


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE kg_inchikeys (
            inchikey TEXT PRIMARY KEY,
            massbank_record_count INTEGER NOT NULL DEFAULT 0,
            example_accession_id TEXT,
            example_name TEXT,
            example_formula TEXT,
            queried_at TEXT
        );

        CREATE TABLE pubchem_compound_1nf (
            inchikey TEXT PRIMARY KEY,
            pubchem_compound TEXT,
            descriptor_type TEXT,
            descriptor_type_label TEXT,
            descriptor_value TEXT,
            FOREIGN KEY (inchikey) REFERENCES kg_inchikeys(inchikey)
        );

        CREATE TABLE pubchem_pathway_1nf (
            inchikey TEXT PRIMARY KEY,
            pubchem_compound TEXT,
            pathway TEXT,
            pathway_label TEXT,
            pathway_organism TEXT,
            FOREIGN KEY (inchikey) REFERENCES kg_inchikeys(inchikey)
        );

        CREATE TABLE hmdb_1nf (
            inchikey TEXT PRIMARY KEY,
            hmdb_metabolite TEXT,
            hmdb_accession TEXT,
            hmdb_label TEXT,
            hmdb_formula TEXT,
            hmdb_avg_mw TEXT,
            hmdb_mono_mw TEXT,
            hmdb_smiles TEXT,
            hmdb_inchi TEXT,
            hmdb_pathway TEXT,
            hmdb_pathway_label TEXT,
            hmdb_disease TEXT,
            hmdb_disease_label TEXT,
            hmdb_biospecimen TEXT,
            FOREIGN KEY (inchikey) REFERENCES kg_inchikeys(inchikey)
        );

        CREATE TABLE knapsack_1nf (
            inchikey TEXT PRIMARY KEY,
            knapsack_id TEXT,
            molecular_entity_name TEXT,
            molecular_formula TEXT,
            value_mw TEXT,
            activity_record_label TEXT,
            activity_category TEXT,
            activity_function TEXT,
            activity_target_species TEXT,
            activity TEXT,
            activity_label TEXT,
            rdfs_seealso TEXT,
            foaf_homepage TEXT,
            FOREIGN KEY (inchikey) REFERENCES kg_inchikeys(inchikey)
        );
        """
    )


def copy_inchikey_table(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    rows = source.execute(
        """
        SELECT
            inchikey,
            massbank_record_count,
            example_accession_id,
            example_name,
            example_formula,
            queried_at
        FROM kg_inchikeys
        ORDER BY inchikey
        """
    ).fetchall()
    target.executemany(
        """
        INSERT INTO kg_inchikeys (
            inchikey,
            massbank_record_count,
            example_accession_id,
            example_name,
            example_formula,
            queried_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [tuple(row) for row in rows],
    )


def copy_inchikey_mapping_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    """Copy the optional full-to-short InChIKey mapping table."""
    exists = source.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'inchikey_short_inchikeys'
        """
    ).fetchone()

    if exists is None:
        return

    target.executescript(
        """
        CREATE TABLE inchikey_short_inchikeys (
            id INTEGER PRIMARY KEY,
            inchikey TEXT NOT NULL UNIQUE,
            short_inchikey TEXT NOT NULL,
            FOREIGN KEY (short_inchikey) REFERENCES kg_inchikeys(inchikey)
        );
        CREATE INDEX idx_inchikey_short_inchikeys_short
            ON inchikey_short_inchikeys(short_inchikey);
        """
    )
    rows = source.execute(
        """
        SELECT id, inchikey, short_inchikey
        FROM inchikey_short_inchikeys
        ORDER BY id
        """
    ).fetchall()
    target.executemany(
        """
        INSERT INTO inchikey_short_inchikeys (
            id, inchikey, short_inchikey
        ) VALUES (?, ?, ?)
        """,
        [tuple(row) for row in rows],
    )


def insert_source_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table_name: str,
    columns: list[str],
    queries_by_column: dict[str, str],
) -> None:
    values_by_column = {
        column: collect_values(source, query)
        for column, query in queries_by_column.items()
    }

    inchikeys = sorted(
        {
            inchikey
            for values in values_by_column.values()
            for inchikey in values.keys()
        }
    )
    placeholders = ", ".join("?" for _ in ["inchikey", *columns])
    column_sql = ", ".join(["inchikey", *columns])
    rows = [
        tuple([inchikey, *[values_by_column[column].get(inchikey) for column in columns]])
        for inchikey in inchikeys
    ]
    target.executemany(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
        rows,
    )


def build_pubchem_compound(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    compound_query = """
        SELECT DISTINCT k.inchikey, c.uri AS value
        FROM kg_inchikeys AS k
        JOIN pubchem_compound_inchikeys AS ci ON ci.kg_inchikey_id = k.id
        JOIN pubchem_compounds AS c ON c.id = ci.pubchem_compound_id
    """
    descriptor_join = """
        FROM kg_inchikeys AS k
        JOIN pubchem_compound_inchikeys AS ci ON ci.kg_inchikey_id = k.id
        JOIN pubchem_compound_descriptors AS d
            ON d.pubchem_compound_id = ci.pubchem_compound_id
        JOIN pubchem_descriptor_types AS t ON t.id = d.descriptor_type_id
    """
    insert_source_table(
        source,
        target,
        "pubchem_compound_1nf",
        [
            "pubchem_compound",
            "descriptor_type",
            "descriptor_type_label",
            "descriptor_value",
        ],
        {
            "pubchem_compound": compound_query,
            "descriptor_type": f"SELECT DISTINCT k.inchikey, t.uri AS value {descriptor_join}",
            "descriptor_type_label": f"SELECT DISTINCT k.inchikey, t.label AS value {descriptor_join}",
            "descriptor_value": f"SELECT DISTINCT k.inchikey, d.descriptor_value AS value {descriptor_join}",
        },
    )


def build_pubchem_pathway(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    compound_query = """
        SELECT DISTINCT k.inchikey, c.uri AS value
        FROM kg_inchikeys AS k
        JOIN pubchem_compound_inchikeys AS ci ON ci.kg_inchikey_id = k.id
        JOIN pubchem_compounds AS c ON c.id = ci.pubchem_compound_id
        JOIN pubchem_compound_pathways AS cp
            ON cp.pubchem_compound_id = ci.pubchem_compound_id
    """
    pathway_join = """
        FROM kg_inchikeys AS k
        JOIN pubchem_compound_inchikeys AS ci ON ci.kg_inchikey_id = k.id
        JOIN pubchem_compound_pathways AS cp
            ON cp.pubchem_compound_id = ci.pubchem_compound_id
        JOIN pubchem_pathways AS p ON p.id = cp.pubchem_pathway_id
    """
    insert_source_table(
        source,
        target,
        "pubchem_pathway_1nf",
        ["pubchem_compound", "pathway", "pathway_label", "pathway_organism"],
        {
            "pubchem_compound": compound_query,
            "pathway": f"SELECT DISTINCT k.inchikey, p.uri AS value {pathway_join}",
            "pathway_label": f"SELECT DISTINCT k.inchikey, p.label AS value {pathway_join}",
            "pathway_organism": f"SELECT DISTINCT k.inchikey, p.organism_uri AS value {pathway_join}",
        },
    )


def build_hmdb(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    metabolite_join = """
        FROM kg_inchikeys AS k
        JOIN hmdb_metabolite_inchikeys AS mi ON mi.kg_inchikey_id = k.id
        JOIN hmdb_metabolites AS m ON m.id = mi.hmdb_metabolite_id
    """
    pathway_join = """
        FROM kg_inchikeys AS k
        JOIN hmdb_metabolite_inchikeys AS mi ON mi.kg_inchikey_id = k.id
        JOIN hmdb_metabolite_pathways AS mp
            ON mp.hmdb_metabolite_id = mi.hmdb_metabolite_id
        JOIN hmdb_pathways AS p ON p.id = mp.hmdb_pathway_id
    """
    disease_join = """
        FROM kg_inchikeys AS k
        JOIN hmdb_metabolite_inchikeys AS mi ON mi.kg_inchikey_id = k.id
        JOIN hmdb_metabolite_diseases AS md
            ON md.hmdb_metabolite_id = mi.hmdb_metabolite_id
        JOIN hmdb_diseases AS d ON d.id = md.hmdb_disease_id
    """
    biospecimen_join = """
        FROM kg_inchikeys AS k
        JOIN hmdb_metabolite_inchikeys AS mi ON mi.kg_inchikey_id = k.id
        JOIN hmdb_metabolite_biospecimens AS mb
            ON mb.hmdb_metabolite_id = mi.hmdb_metabolite_id
        JOIN hmdb_biospecimens AS b ON b.id = mb.hmdb_biospecimen_id
    """
    insert_source_table(
        source,
        target,
        "hmdb_1nf",
        [
            "hmdb_metabolite",
            "hmdb_accession",
            "hmdb_label",
            "hmdb_formula",
            "hmdb_avg_mw",
            "hmdb_mono_mw",
            "hmdb_smiles",
            "hmdb_inchi",
            "hmdb_pathway",
            "hmdb_pathway_label",
            "hmdb_disease",
            "hmdb_disease_label",
            "hmdb_biospecimen",
        ],
        {
            "hmdb_metabolite": f"SELECT DISTINCT k.inchikey, m.uri AS value {metabolite_join}",
            "hmdb_accession": f"SELECT DISTINCT k.inchikey, m.accession AS value {metabolite_join}",
            "hmdb_label": f"SELECT DISTINCT k.inchikey, m.label AS value {metabolite_join}",
            "hmdb_formula": f"SELECT DISTINCT k.inchikey, m.formula AS value {metabolite_join}",
            "hmdb_avg_mw": f"SELECT DISTINCT k.inchikey, m.average_molecular_weight AS value {metabolite_join}",
            "hmdb_mono_mw": f"SELECT DISTINCT k.inchikey, m.monoisotopic_molecular_weight AS value {metabolite_join}",
            "hmdb_smiles": f"SELECT DISTINCT k.inchikey, m.smiles AS value {metabolite_join}",
            "hmdb_inchi": f"SELECT DISTINCT k.inchikey, m.inchi AS value {metabolite_join}",
            "hmdb_pathway": f"SELECT DISTINCT k.inchikey, p.uri AS value {pathway_join}",
            "hmdb_pathway_label": f"SELECT DISTINCT k.inchikey, p.label AS value {pathway_join}",
            "hmdb_disease": f"SELECT DISTINCT k.inchikey, d.uri AS value {disease_join}",
            "hmdb_disease_label": f"SELECT DISTINCT k.inchikey, d.label AS value {disease_join}",
            "hmdb_biospecimen": f"SELECT DISTINCT k.inchikey, b.name AS value {biospecimen_join}",
        },
    )


def build_knapsack(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    record_join = """
        FROM kg_inchikeys AS k
        JOIN knapsack_record_inchikeys AS ri ON ri.kg_inchikey_id = k.id
        JOIN knapsack_records AS r ON r.id = ri.knapsack_record_id
    """
    activity_join = """
        FROM kg_inchikeys AS k
        JOIN knapsack_record_inchikeys AS ri ON ri.kg_inchikey_id = k.id
        JOIN knapsack_record_activities AS ra
            ON ra.knapsack_record_id = ri.knapsack_record_id
        JOIN knapsack_activities AS a ON a.id = ra.knapsack_activity_id
    """
    category_join = """
        FROM kg_inchikeys AS k
        JOIN knapsack_record_inchikeys AS ri ON ri.kg_inchikey_id = k.id
        JOIN knapsack_record_activity_categories AS rc
            ON rc.knapsack_record_id = ri.knapsack_record_id
        JOIN knapsack_activity_categories AS c ON c.id = rc.category_id
    """
    function_join = """
        FROM kg_inchikeys AS k
        JOIN knapsack_record_inchikeys AS ri ON ri.kg_inchikey_id = k.id
        JOIN knapsack_record_activity_functions AS rf
            ON rf.knapsack_record_id = ri.knapsack_record_id
        JOIN knapsack_activity_functions AS f ON f.id = rf.function_id
    """
    species_join = """
        FROM kg_inchikeys AS k
        JOIN knapsack_record_inchikeys AS ri ON ri.kg_inchikey_id = k.id
        JOIN knapsack_record_target_species AS rs
            ON rs.knapsack_record_id = ri.knapsack_record_id
        JOIN knapsack_target_species AS s ON s.id = rs.target_species_id
    """
    link_join = """
        FROM kg_inchikeys AS k
        JOIN knapsack_record_inchikeys AS ri ON ri.kg_inchikey_id = k.id
        JOIN knapsack_record_links AS l ON l.knapsack_record_id = ri.knapsack_record_id
    """
    insert_source_table(
        source,
        target,
        "knapsack_1nf",
        [
            "knapsack_id",
            "molecular_entity_name",
            "molecular_formula",
            "value_mw",
            "activity_record_label",
            "activity_category",
            "activity_function",
            "activity_target_species",
            "activity",
            "activity_label",
            "rdfs_seealso",
            "foaf_homepage",
        ],
        {
            "knapsack_id": f"SELECT DISTINCT k.inchikey, r.knapsack_id AS value {record_join}",
            "molecular_entity_name": f"SELECT DISTINCT k.inchikey, r.molecular_entity_name AS value {record_join}",
            "molecular_formula": f"SELECT DISTINCT k.inchikey, r.molecular_formula AS value {record_join}",
            "value_mw": f"SELECT DISTINCT k.inchikey, r.molecular_weight AS value {record_join}",
            "activity_record_label": f"SELECT DISTINCT k.inchikey, r.activity_record_label AS value {record_join}",
            "activity_category": f"SELECT DISTINCT k.inchikey, c.name AS value {category_join}",
            "activity_function": f"SELECT DISTINCT k.inchikey, f.name AS value {function_join}",
            "activity_target_species": f"SELECT DISTINCT k.inchikey, s.name AS value {species_join}",
            "activity": f"SELECT DISTINCT k.inchikey, a.uri AS value {activity_join}",
            "activity_label": f"SELECT DISTINCT k.inchikey, a.label AS value {activity_join}",
            "rdfs_seealso": f"SELECT DISTINCT k.inchikey, l.url AS value {link_join} WHERE l.link_type = 'rdfs:seeAlso'",
            "foaf_homepage": f"SELECT DISTINCT k.inchikey, l.url AS value {link_join} WHERE l.link_type = 'foaf:homepage'",
        },
    )


def add_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX idx_pubchem_compound_1nf_compound
            ON pubchem_compound_1nf(pubchem_compound);
        CREATE INDEX idx_pubchem_pathway_1nf_pathway
            ON pubchem_pathway_1nf(pathway);
        CREATE INDEX idx_hmdb_1nf_metabolite
            ON hmdb_1nf(hmdb_metabolite);
        CREATE INDEX idx_knapsack_1nf_knapsack_id
            ON knapsack_1nf(knapsack_id);
        """
    )


def build_1nf_database(source_db: Path, output_db: Path, overwrite: bool) -> None:
    if not source_db.exists():
        raise FileNotFoundError(f"Source database does not exist: {source_db}")
    if output_db.exists():
        if not overwrite:
            raise FileExistsError(
                f"Output database already exists: {output_db}. Use --overwrite to replace it."
            )
        output_db.unlink()

    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(output_db)
    target.row_factory = sqlite3.Row
    try:
        target.execute("PRAGMA journal_mode = WAL")
        target.execute("PRAGMA synchronous = NORMAL")
        create_schema(target)
        copy_inchikey_table(source, target)
        copy_inchikey_mapping_table(source, target)
        build_pubchem_compound(source, target)
        build_pubchem_pathway(source, target)
        build_hmdb(source, target)
        build_knapsack(source, target)
        add_indexes(target)
        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()


def main() -> None:
    args = parse_args()
    build_1nf_database(args.source_db, args.output_db, args.overwrite)
    print(f"Created {args.output_db}")


if __name__ == "__main__":
    main()
