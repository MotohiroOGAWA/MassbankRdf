from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from massbank_rdf.services.kg.common import extract_inchikey_value

from .tables.basetb import Base
from .tables.kg_metadata import (
    HmdbMetadata,
    KgInchikey,
    KgLookupFailure,
    KnapsackActivityMetadata,
    PubChemCompoundMetadata,
    PubChemPathwayMetadata,
)


class KgDatabase:
    """Database access class for KG metadata SQLite database.

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
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else self.DEFAULT_DB_PATH
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

    def import_kg_dataframes(
        self,
        data: dict[str, pd.DataFrame],
        *,
        inchikey_summary_df: pd.DataFrame | None = None,
        queried_at: datetime | None = None,
        replace_for_inchikeys: Iterable[str] | None = None,
    ) -> None:
        """Import KG lookup DataFrames using KgLookupService source names.

        Expected data keys are pubchem_compound, pubchem_pathway, hmdb, and
        knapsack_activity. The columns intentionally mirror the query builders
        under massbank_rdf.services.kg.query_builders.
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
                    extract_inchikey_value(item)
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

    def inchikeys_to_dataframe(self) -> pd.DataFrame:
        stmt = select(KgInchikey).order_by(KgInchikey.inchikey)
        with self.engine.connect() as conn:
            return pd.read_sql(stmt, conn)

    def table_to_dataframe(self, table_name: str) -> pd.DataFrame:
        table_by_name = {
            "kg_inchikeys": KgInchikey,
            "pubchem_compound_metadata": PubChemCompoundMetadata,
            "pubchem_pathway_metadata": PubChemPathwayMetadata,
            "hmdb_metadata": HmdbMetadata,
            "knapsack_activity_metadata": KnapsackActivityMetadata,
            "kg_lookup_failures": KgLookupFailure,
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
        normalized = extract_inchikey_value(inchikey)
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
            for value in (extract_inchikey_value(item) for item in inchikeys)
            if value is not None
        ]

        with self.session() as session:
            return self._get_inchikey_id_map(session, normalized)

    def get_max_metadata_kg_inchikey_id(self) -> int:
        """Return the furthest kg_inchikey_id present in KG metadata tables."""
        tables = [
            PubChemCompoundMetadata,
            PubChemPathwayMetadata,
            HmdbMetadata,
            KnapsackActivityMetadata,
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
        rows["inchikey"] = rows["inchikey"].apply(extract_inchikey_value)
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
            PubChemCompoundMetadata,
            PubChemPathwayMetadata,
            HmdbMetadata,
            KnapsackActivityMetadata,
        ]:
            session.execute(delete(table).where(table.kg_inchikey_id.in_(ids)))

    @staticmethod
    def _collect_inchikeys(frames: Iterable[pd.DataFrame]) -> set[str]:
        inchikeys: set[str] = set()
        for frame in frames:
            if frame.empty or "value_inchikey" not in frame.columns:
                continue
            for value in frame["value_inchikey"].tolist():
                inchikey = extract_inchikey_value(value)
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
        rows = []
        seen_keys: set[tuple[object, ...]] = set()
        for _, row in df.iterrows():
            inchikey = extract_inchikey_value(row.get("value_inchikey"))
            if inchikey not in inchikey_id_by_value:
                continue

            kg_inchikey_id = inchikey_id_by_value[inchikey]
            pubchem_compound = self._optional_str(row.get("pubchem_compound"))
            descriptor_type = self._optional_str(row.get("descriptorType"))
            descriptor_value = self._optional_str(row.get("descriptor_value"))
            key = (
                kg_inchikey_id,
                pubchem_compound,
                descriptor_type,
                descriptor_value,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            rows.append(PubChemCompoundMetadata(
                kg_inchikey_id=kg_inchikey_id,
                value_inchikey=inchikey,
                pubchem_compound=pubchem_compound,
                descriptor_type=descriptor_type,
                descriptor_value=descriptor_value,
            ))
        session.add_all(rows)

    def _insert_pubchem_pathway_rows(
        self,
        session: Session,
        df: pd.DataFrame,
        inchikey_id_by_value: dict[str, int],
    ) -> None:
        df = self._prepare_frame(df, ["value_inchikey", "pubchem_compound", "pathway", "pathway_label", "pathway_organism"])
        rows = []
        seen_keys: set[tuple[object, ...]] = set()
        for _, row in df.iterrows():
            inchikey = extract_inchikey_value(row.get("value_inchikey"))
            if inchikey not in inchikey_id_by_value:
                continue

            kg_inchikey_id = inchikey_id_by_value[inchikey]
            pubchem_compound = self._optional_str(row.get("pubchem_compound"))
            pathway = self._optional_str(row.get("pathway"))
            pathway_label = self._optional_str(row.get("pathway_label"))
            pathway_organism = self._optional_str(row.get("pathway_organism"))
            key = (
                kg_inchikey_id,
                pubchem_compound,
                pathway,
                pathway_label,
                pathway_organism,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            rows.append(PubChemPathwayMetadata(
                kg_inchikey_id=kg_inchikey_id,
                value_inchikey=inchikey,
                pubchem_compound=pubchem_compound,
                pathway=pathway,
                pathway_label=pathway_label,
                pathway_organism=pathway_organism,
            ))
        session.add_all(rows)

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
        rows = []
        seen_keys: set[tuple[object, ...]] = set()
        for _, row in df.iterrows():
            inchikey = extract_inchikey_value(row.get("value_inchikey"))
            if inchikey not in inchikey_id_by_value:
                continue

            kg_inchikey_id = inchikey_id_by_value[inchikey]
            hmdb_metabolite = self._optional_str(row.get("hmdb_metabolite"))
            hmdb_pathway = self._optional_str(row.get("hmdb_pathway"))
            hmdb_disease = self._optional_str(row.get("hmdb_disease"))
            hmdb_biospecimen = self._optional_str(row.get("hmdb_biospecimen"))
            key = (
                kg_inchikey_id,
                hmdb_metabolite,
                hmdb_pathway,
                hmdb_disease,
                hmdb_biospecimen,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            rows.append(HmdbMetadata(
                kg_inchikey_id=kg_inchikey_id,
                value_inchikey=inchikey,
                hmdb_metabolite=hmdb_metabolite,
                hmdb_accession=self._optional_str(row.get("hmdb_accession")),
                hmdb_label=self._optional_str(row.get("hmdb_label")),
                hmdb_formula=self._optional_str(row.get("hmdb_formula")),
                hmdb_avg_mw=self._optional_str(row.get("hmdb_avg_mw")),
                hmdb_mono_mw=self._optional_str(row.get("hmdb_mono_mw")),
                hmdb_smiles=self._optional_str(row.get("hmdb_smiles")),
                hmdb_inchi=self._optional_str(row.get("hmdb_inchi")),
                hmdb_pathway=hmdb_pathway,
                hmdb_pathway_label=self._optional_str(row.get("hmdb_pathway_label")),
                hmdb_disease=hmdb_disease,
                hmdb_disease_label=self._optional_str(row.get("hmdb_disease_label")),
                hmdb_biospecimen=hmdb_biospecimen,
            ))
        session.add_all(rows)

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
        rows = []
        seen_keys: set[tuple[object, ...]] = set()
        for _, row in df.iterrows():
            inchikey = extract_inchikey_value(row.get("value_inchikey"))
            if inchikey not in inchikey_id_by_value:
                continue

            kg_inchikey_id = inchikey_id_by_value[inchikey]
            knapsack_id = self._optional_str(row.get("knapsack_id"))
            activity = self._optional_str(row.get("activity"))
            activity_label = self._optional_str(row.get("activity_label"))
            activity_category = self._optional_str(row.get("activity_category"))
            activity_function = self._optional_str(row.get("activity_function"))
            activity_target_species = self._optional_str(row.get("activity_target_species"))
            key = (
                kg_inchikey_id,
                knapsack_id,
                activity,
                activity_label,
                activity_category,
                activity_function,
                activity_target_species,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            rows.append(KnapsackActivityMetadata(
                kg_inchikey_id=kg_inchikey_id,
                value_inchikey=inchikey,
                knapsack_id=knapsack_id,
                molecular_entity_name=self._optional_str(row.get("molecular_entity_name")),
                molecular_formula=self._optional_str(row.get("molecular_formula")),
                value_mw=self._optional_str(row.get("value_mw")),
                activity_record_label=self._optional_str(row.get("activity_record_label")),
                activity_category=activity_category,
                activity_function=activity_function,
                activity_target_species=activity_target_species,
                activity=activity,
                activity_label=activity_label,
                rdfs_seealso=self._optional_str(row.get("rdfs_seealso")),
                foaf_homepage=self._optional_str(row.get("foaf_homepage")),
            ))
        session.add_all(rows)

    @staticmethod
    def _prepare_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        df = df.copy()
        for column in columns:
            if column not in df.columns:
                df[column] = None
        return df[columns].drop_duplicates()

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
