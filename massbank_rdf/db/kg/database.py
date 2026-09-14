from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, TypeVar

import pandas as pd
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from massbank_rdf.services.kg.common import (
    extract_inchikey_value,
    to_short_inchikey,
)

from .tables.basetb import Base
from .tables.kg_metadata import (
    HmdbBiospecimen,
    HmdbDisease,
    HmdbMetabolite,
    HmdbMetaboliteBiospecimen,
    HmdbMetaboliteDisease,
    HmdbMetaboliteInchikey,
    HmdbMetabolitePathway,
    HmdbPathway,
    KgInchikey,
    KgLookupFailure,
    KnapsackActivity,
    KnapsackActivityCategory,
    KnapsackActivityFunction,
    KnapsackRecord,
    KnapsackRecordActivity,
    KnapsackRecordActivityCategory,
    KnapsackRecordActivityFunction,
    KnapsackRecordInchikey,
    KnapsackRecordLink,
    KnapsackRecordTargetSpecies,
    KnapsackTargetSpecies,
    PubChemCompound,
    PubChemCompoundDescriptor,
    PubChemCompoundInchikey,
    PubChemCompoundPathway,
    PubChemDescriptorType,
    PubChemPathway,
)

ModelT = TypeVar("ModelT")


class KgDatabase:
    """Database access class for the normalized KG metadata SQLite database.

    The KG database is independent from MassBankDatabase. It links back to
    MassBank records by the normalized InChIKey string stored in kg_inchikeys.
    """

    DEFAULT_DB_PATH = (
        Path(__file__).resolve().parents[3]
        / "data"
        / "db"
        / "kg.sqlite3"
    )

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        echo: bool = False,
        use_short_inchikey: bool = False,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else self.DEFAULT_DB_PATH
        self.use_short_inchikey = bool(use_short_inchikey)
        self.engine = self._create_engine(self.db_path, echo=echo)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
        )

    @staticmethod
    def _create_engine(
        db_path: Path,
        *,
        echo: bool = False,
    ) -> Engine:
        db_path.parent.mkdir(parents=True, exist_ok=True)

        return create_engine(
            f"sqlite:///{db_path}",
            echo=echo,
            future=True,
        )

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_tables(self) -> None:
        Base.metadata.drop_all(self.engine)

    def recreate_tables(self) -> None:
        self.drop_tables()
        self.create_tables()

    def session(self) -> Session:
        return self.SessionLocal()

    def _normalize_inchikey_key(self, value: object) -> str | None:
        if self.use_short_inchikey:
            return to_short_inchikey(str(value)) if value is not None else None
        return extract_inchikey_value(value)

    def replace_inchikey_short_mappings(
        self,
        mappings: pd.DataFrame,
    ) -> None:
        """Replace the full-to-short InChIKey mapping table."""
        required = {"inchikey", "short_inchikey"}
        missing = required.difference(mappings.columns)
        if missing:
            raise ValueError(f"mappings is missing columns: {sorted(missing)}")

        rows = [
            {
                "inchikey": extract_inchikey_value(row["inchikey"]),
                "short_inchikey": to_short_inchikey(row["short_inchikey"]),
            }
            for _, row in mappings.iterrows()
        ]
        rows = [
            row
            for row in rows
            if row["inchikey"] is not None and row["short_inchikey"] is not None
        ]

        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS inchikey_short_inchikeys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inchikey TEXT NOT NULL UNIQUE,
                    short_inchikey TEXT NOT NULL,
                    FOREIGN KEY (short_inchikey) REFERENCES kg_inchikeys(inchikey)
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE INDEX IF NOT EXISTS idx_inchikey_short_inchikeys_short
                ON inchikey_short_inchikeys(short_inchikey)
                """
            )
            conn.exec_driver_sql("DELETE FROM inchikey_short_inchikeys")
            if rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO inchikey_short_inchikeys (
                            inchikey, short_inchikey
                        ) VALUES (:inchikey, :short_inchikey)
                        """
                    ),
                    rows,
                )

    def upsert_massbank_inchikey_summary(
        self,
        summary_df: pd.DataFrame,
        *,
        queried_at: datetime | None = None,
    ) -> None:
        """Upsert kg_inchikeys from a MassBank-derived InChIKey summary."""
        if summary_df.empty:
            return

        required = {"inchikey"}
        missing = required.difference(summary_df.columns)
        if missing:
            raise ValueError(f"summary_df is missing columns: {sorted(missing)}")

        with self.session() as session:
            self._upsert_massbank_inchikey_summary(session, summary_df, queried_at=queried_at)
            session.commit()

        # KG metadata scores are derived from the normalized relationship
        # tables and must be rebuilt lazily after an import.
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE IF EXISTS kg_metadata_scores")

    def import_kg_dataframes(
        self,
        data: dict[str, pd.DataFrame],
        *,
        inchikey_summary_df: pd.DataFrame | None = None,
        queried_at: datetime | None = None,
        replace_for_inchikeys: Iterable[str] | None = None,
    ) -> None:
        """Import KG lookup DataFrames into normalized source tables.

        Expected data keys are pubchem_compound, pubchem_pathway, hmdb, and
        knapsack_activity. Multi-value fields returned as pipe-separated strings
        are split into one row per entity or relationship.
        """
        source_frames = {
            source: frame.copy()
            for source, frame in data.items()
            if frame is not None
        }

        inchikeys = self._collect_inchikeys(source_frames.values())
        if replace_for_inchikeys is not None:
            inchikeys.update(
                value
                for value in (
                    self._normalize_inchikey_key(item)
                    for item in replace_for_inchikeys
                )
                if value is not None
            )

        with self.session() as session:
            if inchikey_summary_df is not None and not inchikey_summary_df.empty:
                self._upsert_massbank_inchikey_summary(
                    session,
                    inchikey_summary_df,
                    queried_at=queried_at,
                )
            else:
                self._ensure_inchikey_rows(session, sorted(inchikeys), queried_at=queried_at)

            inchikey_id_by_value = self._get_inchikey_id_map(session, sorted(inchikeys))
            self._replace_source_rows(session, inchikey_id_by_value.values())

            self._insert_pubchem_compound_rows(
                session,
                source_frames.get("pubchem_compound", pd.DataFrame()),
                inchikey_id_by_value,
            )
            self._insert_pubchem_pathway_rows(
                session,
                source_frames.get("pubchem_pathway", pd.DataFrame()),
                inchikey_id_by_value,
            )
            self._insert_hmdb_rows(
                session,
                source_frames.get("hmdb", pd.DataFrame()),
                inchikey_id_by_value,
            )
            self._insert_knapsack_activity_rows(
                session,
                source_frames.get("knapsack_activity", pd.DataFrame()),
                inchikey_id_by_value,
            )

            session.commit()

        with self.engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE IF EXISTS kg_metadata_scores")

    def inchikeys_to_dataframe(self) -> pd.DataFrame:
        stmt = select(KgInchikey).order_by(KgInchikey.inchikey)
        with self.engine.connect() as conn:
            return pd.read_sql(stmt, conn)

    def table_to_dataframe(self, table_name: str) -> pd.DataFrame:
        table_by_name = {
            "kg_inchikeys": KgInchikey,
            "kg_lookup_failures": KgLookupFailure,
            "pubchem_compounds": PubChemCompound,
            "pubchem_compound_inchikeys": PubChemCompoundInchikey,
            "pubchem_descriptor_types": PubChemDescriptorType,
            "pubchem_compound_descriptors": PubChemCompoundDescriptor,
            "pubchem_pathways": PubChemPathway,
            "pubchem_compound_pathways": PubChemCompoundPathway,
            "hmdb_metabolites": HmdbMetabolite,
            "hmdb_metabolite_inchikeys": HmdbMetaboliteInchikey,
            "hmdb_pathways": HmdbPathway,
            "hmdb_metabolite_pathways": HmdbMetabolitePathway,
            "hmdb_diseases": HmdbDisease,
            "hmdb_metabolite_diseases": HmdbMetaboliteDisease,
            "hmdb_biospecimens": HmdbBiospecimen,
            "hmdb_metabolite_biospecimens": HmdbMetaboliteBiospecimen,
            "knapsack_records": KnapsackRecord,
            "knapsack_record_inchikeys": KnapsackRecordInchikey,
            "knapsack_activities": KnapsackActivity,
            "knapsack_record_activities": KnapsackRecordActivity,
            "knapsack_activity_categories": KnapsackActivityCategory,
            "knapsack_record_activity_categories": KnapsackRecordActivityCategory,
            "knapsack_activity_functions": KnapsackActivityFunction,
            "knapsack_record_activity_functions": KnapsackRecordActivityFunction,
            "knapsack_target_species": KnapsackTargetSpecies,
            "knapsack_record_target_species": KnapsackRecordTargetSpecies,
            "knapsack_record_links": KnapsackRecordLink,
        }
        table = table_by_name[table_name]
        stmt = select(table)
        with self.engine.connect() as conn:
            return pd.read_sql(stmt, conn)

    def get_queried_inchikeys(self) -> set[str]:
        """Return InChIKeys whose KG lookup has completed at least once."""
        stmt = select(KgInchikey.inchikey).where(KgInchikey.queried_at.is_not(None))

        with self.session() as session:
            return set(session.scalars(stmt).all())

    def get_failed_inchikeys(self) -> set[str]:
        """Return InChIKeys recorded as KG lookup failures."""
        stmt = select(KgLookupFailure.value_inchikey)

        with self.session() as session:
            return set(session.scalars(stmt).all())

    def record_lookup_failure(
        self,
        inchikey: str,
        *,
        inchikey_summary_df: pd.DataFrame | None = None,
        failed_at: datetime | None = None,
        error: Exception | None = None,
    ) -> None:
        """Record a failed KG lookup and mark the InChIKey as completed."""
        normalized = self._normalize_inchikey_key(inchikey)
        if normalized is None:
            return

        failed_at = failed_at or datetime.utcnow()

        with self.session() as session:
            if inchikey_summary_df is not None and not inchikey_summary_df.empty:
                self._upsert_massbank_inchikey_summary(
                    session,
                    inchikey_summary_df,
                    queried_at=None,
                )
            else:
                self._ensure_inchikey_rows(
                    session,
                    [normalized],
                    queried_at=None,
                )

            inchikey_id_by_value = self._get_inchikey_id_map(session, [normalized])
            kg_inchikey_id = inchikey_id_by_value.get(normalized)
            if kg_inchikey_id is None:
                session.commit()
                return

            session.execute(
                delete(KgLookupFailure).where(
                    KgLookupFailure.kg_inchikey_id == kg_inchikey_id
                )
            )

            error_type = type(error).__name__ if error is not None else None
            error_message = str(error) if error is not None else None

            session.add(
                KgLookupFailure(
                    kg_inchikey_id=kg_inchikey_id,
                    value_inchikey=normalized,
                    error_type=error_type,
                    error_message=error_message,
                    failed_at=failed_at,
                )
            )

            kg_inchikey = session.get(KgInchikey, kg_inchikey_id)
            if kg_inchikey is not None:
                kg_inchikey.queried_at = failed_at

            session.commit()

    def get_inchikey_id_map(
        self,
        inchikeys: Iterable[str],
    ) -> dict[str, int]:
        """Return kg_inchikeys.id values for normalized InChIKeys."""
        normalized = [
            value
            for value in (self._normalize_inchikey_key(item) for item in inchikeys)
            if value is not None
        ]

        with self.session() as session:
            return self._get_inchikey_id_map(session, normalized)

    def get_max_metadata_kg_inchikey_id(self) -> int:
        """Return the furthest kg_inchikey_id present in source link tables."""
        tables = [
            PubChemCompoundInchikey,
            HmdbMetaboliteInchikey,
            KnapsackRecordInchikey,
        ]

        max_ids: list[int] = []
        with self.session() as session:
            for table in tables:
                value = session.scalar(select(func.max(table.kg_inchikey_id)))
                if value is not None:
                    max_ids.append(int(value))

        return max(max_ids, default=0)

    def clear_queried_at_after_kg_inchikey_id(
        self,
        kg_inchikey_id: int,
    ) -> None:
        """Clear stale completion markers after a metadata-derived progress id."""
        with self.session() as session:
            session.execute(
                update(KgInchikey)
                .where(KgInchikey.id > int(kg_inchikey_id))
                .values(queried_at=None)
            )
            session.commit()

    def _upsert_massbank_inchikey_summary(
        self,
        session: Session,
        summary_df: pd.DataFrame,
        *,
        queried_at: datetime | None,
    ) -> None:
        rows = summary_df.copy()
        rows["inchikey"] = rows["inchikey"].apply(self._normalize_inchikey_key)
        rows = rows.dropna(subset=["inchikey"])

        existing = {
            row.inchikey: row
            for row in session.scalars(
                select(KgInchikey).where(KgInchikey.inchikey.in_(rows["inchikey"].tolist()))
            ).all()
        }

        for _, row in rows.iterrows():
            inchikey = str(row["inchikey"])
            kg_inchikey = existing.get(inchikey)
            if kg_inchikey is None:
                kg_inchikey = KgInchikey(inchikey=inchikey)
                session.add(kg_inchikey)
                existing[inchikey] = kg_inchikey

            kg_inchikey.massbank_record_count = self._optional_int(row.get("massbank_record_count")) or 0
            kg_inchikey.example_accession_id = self._optional_str(row.get("example_accession_id"))
            kg_inchikey.example_name = self._optional_str(row.get("example_name"))
            kg_inchikey.example_formula = self._optional_str(row.get("example_formula"))
            if queried_at is not None:
                kg_inchikey.queried_at = queried_at

        session.flush()

    def _ensure_inchikey_rows(
        self,
        session: Session,
        inchikeys: list[str],
        *,
        queried_at: datetime | None,
    ) -> None:
        if not inchikeys:
            return

        existing = set(
            session.scalars(
                select(KgInchikey.inchikey).where(KgInchikey.inchikey.in_(inchikeys))
            ).all()
        )

        for inchikey in inchikeys:
            if inchikey not in existing:
                session.add(KgInchikey(inchikey=inchikey, queried_at=queried_at))

        if queried_at is not None:
            for kg_inchikey in session.scalars(
                select(KgInchikey).where(KgInchikey.inchikey.in_(inchikeys))
            ).all():
                kg_inchikey.queried_at = queried_at

        session.flush()

    def _get_inchikey_id_map(
        self,
        session: Session,
        inchikeys: list[str],
    ) -> dict[str, int]:
        if not inchikeys:
            return {}

        rows = session.execute(
            select(KgInchikey.inchikey, KgInchikey.id).where(KgInchikey.inchikey.in_(inchikeys))
        ).all()

        return {inchikey: int(row_id) for inchikey, row_id in rows}

    def _replace_source_rows(
        self,
        session: Session,
        kg_inchikey_ids: Iterable[int],
    ) -> None:
        ids = list(kg_inchikey_ids)
        if not ids:
            return

        for table in [
            PubChemCompoundInchikey,
            HmdbMetaboliteInchikey,
            KnapsackRecordInchikey,
        ]:
            session.execute(delete(table).where(table.kg_inchikey_id.in_(ids)))

    def _collect_inchikeys(
        self,
        frames: Iterable[pd.DataFrame],
    ) -> set[str]:
        inchikeys: set[str] = set()
        for frame in frames:
            if frame.empty or "value_inchikey" not in frame.columns:
                continue
            for value in frame["value_inchikey"].tolist():
                inchikey = self._normalize_inchikey_key(value)
                if inchikey is not None:
                    inchikeys.add(inchikey)
        return inchikeys

    def _insert_pubchem_compound_rows(
        self,
        session: Session,
        df: pd.DataFrame,
        inchikey_id_by_value: dict[str, int],
    ) -> None:
        df = self._prepare_frame(df, ["value_inchikey", "pubchem_compound", "descriptorType", "descriptor_value"])
        for _, row in df.iterrows():
            inchikey = self._normalize_inchikey_key(row.get("value_inchikey"))
            kg_inchikey_id = inchikey_id_by_value.get(inchikey) if inchikey is not None else None
            compound_uri = self._optional_str(row.get("pubchem_compound"))
            if kg_inchikey_id is None or compound_uri is None:
                continue

            compound = self._get_or_create(session, PubChemCompound, {"uri": compound_uri})
            self._get_or_create(
                session,
                PubChemCompoundInchikey,
                {
                    "kg_inchikey_id": kg_inchikey_id,
                    "pubchem_compound_id": compound.id,
                },
            )

            descriptor_type_uri = self._optional_str(row.get("descriptorType"))
            descriptor_value = self._optional_str(row.get("descriptor_value"))
            if descriptor_type_uri is None or descriptor_value is None:
                continue

            descriptor_type = self._get_or_create(
                session,
                PubChemDescriptorType,
                {"uri": descriptor_type_uri},
            )
            self._get_or_create(
                session,
                PubChemCompoundDescriptor,
                {
                    "pubchem_compound_id": compound.id,
                    "descriptor_type_id": descriptor_type.id,
                    "descriptor_value": descriptor_value,
                },
            )

    def _insert_pubchem_pathway_rows(
        self,
        session: Session,
        df: pd.DataFrame,
        inchikey_id_by_value: dict[str, int],
    ) -> None:
        df = self._prepare_frame(df, ["value_inchikey", "pubchem_compound", "pathway", "pathway_label", "pathway_organism"])
        for _, row in df.iterrows():
            inchikey = self._normalize_inchikey_key(row.get("value_inchikey"))
            kg_inchikey_id = inchikey_id_by_value.get(inchikey) if inchikey is not None else None
            compound_uri = self._optional_str(row.get("pubchem_compound"))
            pathway_uri = self._optional_str(row.get("pathway"))
            if kg_inchikey_id is None or compound_uri is None:
                continue

            compound = self._get_or_create(session, PubChemCompound, {"uri": compound_uri})
            self._get_or_create(
                session,
                PubChemCompoundInchikey,
                {
                    "kg_inchikey_id": kg_inchikey_id,
                    "pubchem_compound_id": compound.id,
                },
            )

            if pathway_uri is None:
                continue

            pathway = self._get_or_create(
                session,
                PubChemPathway,
                {"uri": pathway_uri},
                defaults={
                    "label": self._optional_str(row.get("pathway_label")),
                    "organism_uri": self._optional_str(row.get("pathway_organism")),
                },
            )
            self._get_or_create(
                session,
                PubChemCompoundPathway,
                {
                    "pubchem_compound_id": compound.id,
                    "pubchem_pathway_id": pathway.id,
                },
            )

    def _insert_hmdb_rows(
        self,
        session: Session,
        df: pd.DataFrame,
        inchikey_id_by_value: dict[str, int],
    ) -> None:
        columns = [
            "value_inchikey", "hmdb_metabolite", "hmdb_accession", "hmdb_label",
            "hmdb_formula", "hmdb_avg_mw", "hmdb_mono_mw", "hmdb_smiles",
            "hmdb_inchi", "hmdb_pathway", "hmdb_pathway_label", "hmdb_disease",
            "hmdb_disease_label", "hmdb_biospecimen",
        ]
        df = self._prepare_frame(df, columns)
        for _, row in df.iterrows():
            inchikey = self._normalize_inchikey_key(row.get("value_inchikey"))
            kg_inchikey_id = inchikey_id_by_value.get(inchikey) if inchikey is not None else None
            metabolite_uri = self._optional_str(row.get("hmdb_metabolite"))
            if kg_inchikey_id is None or metabolite_uri is None:
                continue

            metabolite = self._get_or_create(
                session,
                HmdbMetabolite,
                {"uri": metabolite_uri},
                defaults={
                    "accession": self._optional_str(row.get("hmdb_accession")),
                    "label": self._optional_str(row.get("hmdb_label")),
                    "formula": self._optional_str(row.get("hmdb_formula")),
                    "average_molecular_weight": self._optional_str(row.get("hmdb_avg_mw")),
                    "monoisotopic_molecular_weight": self._optional_str(row.get("hmdb_mono_mw")),
                    "smiles": self._optional_str(row.get("hmdb_smiles")),
                    "inchi": self._optional_str(row.get("hmdb_inchi")),
                },
            )
            self._get_or_create(
                session,
                HmdbMetaboliteInchikey,
                {
                    "kg_inchikey_id": kg_inchikey_id,
                    "hmdb_metabolite_id": metabolite.id,
                },
            )

            pathway_labels = self._split_value(row.get("hmdb_pathway_label"))
            for index, pathway_uri in enumerate(self._split_value(row.get("hmdb_pathway"))):
                pathway = self._get_or_create(
                    session,
                    HmdbPathway,
                    {"uri": pathway_uri},
                    defaults={"label": self._value_at(pathway_labels, index)},
                )
                self._get_or_create(
                    session,
                    HmdbMetabolitePathway,
                    {
                        "hmdb_metabolite_id": metabolite.id,
                        "hmdb_pathway_id": pathway.id,
                    },
                )

            disease_labels = self._split_value(row.get("hmdb_disease_label"))
            for index, disease_uri in enumerate(self._split_value(row.get("hmdb_disease"))):
                disease = self._get_or_create(
                    session,
                    HmdbDisease,
                    {"uri": disease_uri},
                    defaults={"label": self._value_at(disease_labels, index)},
                )
                self._get_or_create(
                    session,
                    HmdbMetaboliteDisease,
                    {
                        "hmdb_metabolite_id": metabolite.id,
                        "hmdb_disease_id": disease.id,
                    },
                )

            for biospecimen_name in self._split_value(row.get("hmdb_biospecimen")):
                biospecimen = self._get_or_create(
                    session,
                    HmdbBiospecimen,
                    {"name": biospecimen_name},
                )
                self._get_or_create(
                    session,
                    HmdbMetaboliteBiospecimen,
                    {
                        "hmdb_metabolite_id": metabolite.id,
                        "hmdb_biospecimen_id": biospecimen.id,
                    },
                )

    def _insert_knapsack_activity_rows(
        self,
        session: Session,
        df: pd.DataFrame,
        inchikey_id_by_value: dict[str, int],
    ) -> None:
        columns = [
            "value_inchikey", "knapsack_id", "molecular_entity_name",
            "molecular_formula", "value_mw", "activity_record_label",
            "activity_category", "activity_function", "activity_target_species",
            "activity", "activity_label", "rdfs_seealso", "foaf_homepage",
        ]
        df = self._prepare_frame(df, columns)
        for _, row in df.iterrows():
            inchikey = self._normalize_inchikey_key(row.get("value_inchikey"))
            kg_inchikey_id = inchikey_id_by_value.get(inchikey) if inchikey is not None else None
            knapsack_id = self._optional_str(row.get("knapsack_id"))
            if kg_inchikey_id is None or knapsack_id is None:
                continue

            record = self._get_or_create(
                session,
                KnapsackRecord,
                {"knapsack_id": knapsack_id},
                defaults={
                    "molecular_entity_name": self._optional_str(row.get("molecular_entity_name")),
                    "molecular_formula": self._optional_str(row.get("molecular_formula")),
                    "molecular_weight": self._optional_str(row.get("value_mw")),
                    "activity_record_label": self._optional_str(row.get("activity_record_label")),
                },
            )
            self._get_or_create(
                session,
                KnapsackRecordInchikey,
                {
                    "kg_inchikey_id": kg_inchikey_id,
                    "knapsack_record_id": record.id,
                },
            )

            activity_uri = self._optional_str(row.get("activity"))
            if activity_uri is not None:
                activity = self._get_or_create(
                    session,
                    KnapsackActivity,
                    {"uri": activity_uri},
                    defaults={"label": self._optional_str(row.get("activity_label"))},
                )
                self._get_or_create(
                    session,
                    KnapsackRecordActivity,
                    {
                        "knapsack_record_id": record.id,
                        "knapsack_activity_id": activity.id,
                    },
                )

            for category_name in self._split_value(row.get("activity_category")):
                category = self._get_or_create(
                    session,
                    KnapsackActivityCategory,
                    {"name": category_name},
                )
                self._get_or_create(
                    session,
                    KnapsackRecordActivityCategory,
                    {
                        "knapsack_record_id": record.id,
                        "category_id": category.id,
                    },
                )

            for function_name in self._split_value(row.get("activity_function")):
                function = self._get_or_create(
                    session,
                    KnapsackActivityFunction,
                    {"name": function_name},
                )
                self._get_or_create(
                    session,
                    KnapsackRecordActivityFunction,
                    {
                        "knapsack_record_id": record.id,
                        "function_id": function.id,
                    },
                )

            for species_name in self._split_value(row.get("activity_target_species")):
                species = self._get_or_create(
                    session,
                    KnapsackTargetSpecies,
                    {"name": species_name},
                )
                self._get_or_create(
                    session,
                    KnapsackRecordTargetSpecies,
                    {
                        "knapsack_record_id": record.id,
                        "target_species_id": species.id,
                    },
                )

            for url in self._split_value(row.get("rdfs_seealso")):
                self._get_or_create(
                    session,
                    KnapsackRecordLink,
                    {
                        "knapsack_record_id": record.id,
                        "link_type": "rdfs:seeAlso",
                        "url": url,
                    },
                )

            for url in self._split_value(row.get("foaf_homepage")):
                self._get_or_create(
                    session,
                    KnapsackRecordLink,
                    {
                        "knapsack_record_id": record.id,
                        "link_type": "foaf:homepage",
                        "url": url,
                    },
                )

    def _get_or_create(
        self,
        session: Session,
        model: type[ModelT],
        lookup: dict[str, object],
        *,
        defaults: dict[str, object] | None = None,
    ) -> ModelT:
        conditions = []
        for field_name, value in lookup.items():
            column = getattr(model, field_name)
            conditions.append(column.is_(None) if value is None else column == value)

        instance = session.scalar(select(model).where(*conditions))
        values = {**lookup, **(defaults or {})}
        if instance is None:
            instance = model(**values)
            session.add(instance)
            session.flush()
            return instance

        self._fill_missing_values(instance, defaults or {})
        return instance

    @staticmethod
    def _fill_missing_values(instance: object, values: dict[str, object]) -> None:
        for field_name, value in values.items():
            if value is None:
                continue
            current_value = getattr(instance, field_name)
            if current_value is None or current_value == "":
                setattr(instance, field_name, value)

    @staticmethod
    def _prepare_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        df = df.copy()
        for column in columns:
            if column not in df.columns:
                df[column] = None
        return df[columns].drop_duplicates()

    @staticmethod
    def _split_value(value: object) -> list[str]:
        text = KgDatabase._optional_str(value)
        if text is None:
            return []
        return [part.strip() for part in text.split("|") if part.strip()]

    @staticmethod
    def _value_at(values: list[str], index: int) -> str | None:
        if index < len(values):
            return values[index]
        return None

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None or pd.isna(value):
            return None
        return int(value)
