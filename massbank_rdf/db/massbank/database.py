from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text

from .tables.basetb import Base
from .tables.massbank_record import MassBankRecord
from .tables.massbank_peak_record import MassBankPeakRecord


class MassBankDatabase:
    """Database access class for MassBank SQLite database.

    Notes
    -----
    MassBankRecord.id is the primary key.
    MassBankRecord.accession_id is unique.

    MassBankPeakRecord.id is the primary key.
    MassBankPeakRecord.massbank_record_id references MassBankRecord.id.
    MassBankPeakRecord.massbank_record_id + peak_index is unique.
    """

    DEFAULT_DB_PATH = (
        Path(__file__).resolve().parents[3]
        / "data"
        / "db"
        / "massbank.sqlite3"
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
        """Create all tables."""
        Base.metadata.create_all(self.engine)

    def drop_tables(self) -> None:
        """Drop all tables."""
        Base.metadata.drop_all(self.engine)

    def recreate_tables(self) -> None:
        """Drop and create all tables."""
        self.drop_tables()
        self.create_tables()

    def session(self) -> Session:
        """Create a new SQLAlchemy session."""
        return self.SessionLocal()

    # ------------------------------------------------------------------
    # DataFrame access
    # ------------------------------------------------------------------

    # def records_to_dataframe(self) -> pd.DataFrame:
    #     """Load all MassBank records as a DataFrame."""
    #     stmt = select(MassBankRecord)

    #     with self.engine.connect() as conn:
    #         return pd.read_sql(stmt, conn)

    def records_to_dataframe(
        self,
        records: list[MassBankRecord],
    ) -> pd.DataFrame:
        """Convert MassBankRecord objects to a pandas DataFrame."""
        rows: list[dict] = []

        for record in records:
            rows.append(
                {
                    "id": record.id,
                    "accession_id": record.accession_id,
                    "name": record.name,
                    "smiles": record.smiles,
                    "inchikey": record.inchikey,
                    "formula": record.formula,
                    "precursor_mz": record.precursor_mz,
                    "precursor_type": record.precursor_type,
                    "splash": record.splash,
                    "ms_type": record.ms_type,
                    "ion_mode": record.ion_mode,
                    "collision_energy": record.collision_energy,
                    "retention_time": record.retention_time,
                    "instrument_type": record.instrument_type,
                    "ionization": record.ionization,
                    "ionization_voltage": record.ionization_voltage,
                    "fragmentation_mode": record.fragmentation_mode,
                    "ac_instrument": record.ac_instrument,
                }
            )

        return pd.DataFrame(rows)

    def peaks_to_dataframe(self) -> pd.DataFrame:
        """Load all MassBank peak records as a DataFrame."""
        stmt = select(MassBankPeakRecord)

        with self.engine.connect() as conn:
            return pd.read_sql(stmt, conn)

    def get_peaks_dataframe(
        self,
        accession_id: str,
    ) -> pd.DataFrame:
        """Get peak records for one MassBank accession_id as a DataFrame."""
        stmt = (
            select(MassBankPeakRecord)
            .join(
                MassBankRecord,
                MassBankPeakRecord.massbank_record_id == MassBankRecord.id,
            )
            .where(MassBankRecord.accession_id == accession_id)
            .order_by(MassBankPeakRecord.peak_index)
        )

        with self.engine.connect() as conn:
            return pd.read_sql(stmt, conn)

    def get_peaks_with_record_dataframe(
        self,
        accession_id: str,
    ) -> pd.DataFrame:
        """Get peaks joined with MassBank record metadata."""
        stmt = (
            select(
                MassBankRecord.accession_id,
                MassBankRecord.name,
                MassBankRecord.inchikey,
                MassBankRecord.smiles,
                MassBankRecord.formula,
                MassBankRecord.precursor_mz,
                MassBankRecord.precursor_type,
                MassBankRecord.ion_mode,
                MassBankPeakRecord.id.label("peak_id"),
                MassBankPeakRecord.peak_index,
                MassBankPeakRecord.seq,
                MassBankPeakRecord.mz,
                MassBankPeakRecord.intensity,
                MassBankPeakRecord.relative_intensity,
            )
            .join(
                MassBankPeakRecord,
                MassBankPeakRecord.massbank_record_id == MassBankRecord.id,
            )
            .where(MassBankRecord.accession_id == accession_id)
            .order_by(MassBankPeakRecord.peak_index)
        )

        with self.engine.connect() as conn:
            return pd.read_sql(stmt, conn)

    # ------------------------------------------------------------------
    # MassBankRecord access
    # ------------------------------------------------------------------

    def get_record_by_id(
        self,
        record_id: int,
    ) -> MassBankRecord | None:
        """Get one MassBank record by internal primary key id."""
        with self.session() as session:
            return session.get(MassBankRecord, record_id)
        
    def get_records_by_ids(
        self,
        record_ids: list[int],
    ) -> list[MassBankRecord]:
        """Get MassBank records by internal primary key ids.

        The returned records preserve the order of record_ids as much as possible.
        Missing ids are ignored.
        """
        if not record_ids:
            return []

        unique_ids = list(dict.fromkeys(int(record_id) for record_id in record_ids))

        stmt = select(MassBankRecord).where(
            MassBankRecord.id.in_(unique_ids)
        )

        with self.session() as session:
            records = list(session.scalars(stmt).all())

        record_by_id = {
            record.id: record
            for record in records
        }

        return [
            record_by_id[record_id]
            for record_id in unique_ids
            if record_id in record_by_id
        ]

    def get_records_by_ids_dataframe(
        self,
        record_ids: list[int],
    ) -> pd.DataFrame:
        """Get MassBank records by ids and return them as a DataFrame."""
        records = self.get_records_by_ids(record_ids)

        return self.records_to_dataframe(records)

    def get_record(
        self,
        accession_id: str,
    ) -> MassBankRecord | None:
        """Get one MassBank record by accession_id."""
        stmt = select(MassBankRecord).where(
            MassBankRecord.accession_id == accession_id
        )

        with self.session() as session:
            return session.scalar(stmt)

    def get_record_id(
        self,
        accession_id: str,
    ) -> int | None:
        """Get internal MassBankRecord.id from accession_id."""
        stmt = select(MassBankRecord.id).where(
            MassBankRecord.accession_id == accession_id
        )

        with self.session() as session:
            return session.scalar(stmt)

    def get_records(
        self,
        accession_ids: Iterable[str],
    ) -> list[MassBankRecord]:
        """Get MassBank records by accession_ids."""
        accession_ids = list(accession_ids)

        if not accession_ids:
            return []

        stmt = select(MassBankRecord).where(
            MassBankRecord.accession_id.in_(accession_ids)
        )

        with self.session() as session:
            return list(session.scalars(stmt).all())

    def get_record_ids(
        self,
        accession_ids: Iterable[str],
    ) -> dict[str, int]:
        """Get mapping from accession_id to internal record id."""
        accession_ids = list(accession_ids)

        if not accession_ids:
            return {}

        stmt = select(
            MassBankRecord.accession_id,
            MassBankRecord.id,
        ).where(
            MassBankRecord.accession_id.in_(accession_ids)
        )

        with self.session() as session:
            rows = session.execute(stmt).all()

        return {
            accession_id: record_id
            for accession_id, record_id in rows
        }

    def get_all_records(self) -> list[MassBankRecord]:
        """Get all MassBank records."""
        stmt = select(MassBankRecord)

        with self.session() as session:
            return list(session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # MassBankPeakRecord access
    # ------------------------------------------------------------------

    def get_peak_by_id(
        self,
        peak_id: int,
    ) -> MassBankPeakRecord | None:
        """Get one peak record by internal primary key id."""
        with self.session() as session:
            return session.get(MassBankPeakRecord, peak_id)

    def get_peak(
        self,
        accession_id: str,
        peak_index: int,
    ) -> MassBankPeakRecord | None:
        """Get one peak record by accession_id and peak_index.

        Since MassBankPeakRecord no longer has accession_id,
        MassBankRecord.id is first resolved from accession_id.
        """
        record_id = self.get_record_id(accession_id)

        if record_id is None:
            return None

        stmt = select(MassBankPeakRecord).where(
            MassBankPeakRecord.massbank_record_id == record_id,
            MassBankPeakRecord.peak_index == peak_index,
        )

        with self.session() as session:
            return session.scalar(stmt)

    def get_peaks(
        self,
        accession_id: str,
    ) -> list[MassBankPeakRecord]:
        """Get peak records for one MassBank accession_id."""
        record_id = self.get_record_id(accession_id)

        if record_id is None:
            return []

        stmt = (
            select(MassBankPeakRecord)
            .where(MassBankPeakRecord.massbank_record_id == record_id)
            .order_by(MassBankPeakRecord.peak_index)
        )

        with self.session() as session:
            return list(session.scalars(stmt).all())

    def get_peaks_by_record_id(
        self,
        record_id: int,
    ) -> list[MassBankPeakRecord]:
        """Get peak records by internal MassBankRecord.id."""
        stmt = (
            select(MassBankPeakRecord)
            .where(MassBankPeakRecord.massbank_record_id == record_id)
            .order_by(MassBankPeakRecord.peak_index)
        )

        with self.session() as session:
            return list(session.scalars(stmt).all())

    def get_peaks_by_accession_ids(
        self,
        accession_ids: Iterable[str],
    ) -> list[MassBankPeakRecord]:
        """Get peak records for multiple accession_ids."""
        accession_ids = list(accession_ids)

        if not accession_ids:
            return []

        stmt = (
            select(MassBankPeakRecord)
            .join(
                MassBankRecord,
                MassBankPeakRecord.massbank_record_id == MassBankRecord.id,
            )
            .where(MassBankRecord.accession_id.in_(accession_ids))
            .order_by(
                MassBankRecord.accession_id,
                MassBankPeakRecord.peak_index,
            )
        )

        with self.session() as session:
            return list(session.scalars(stmt).all())

    def get_peaks_by_accession_ids_dataframe(
        self,
        accession_ids: Iterable[str],
    ) -> pd.DataFrame:
        """Get peak records for multiple accession_ids as a DataFrame.

        The returned DataFrame includes accession_id from massbank_records.
        """
        accession_ids = list(accession_ids)

        if not accession_ids:
            return pd.DataFrame()

        stmt = (
            select(
                MassBankRecord.accession_id,
                MassBankPeakRecord.id,
                MassBankPeakRecord.massbank_record_id,
                MassBankPeakRecord.peak_index,
                MassBankPeakRecord.seq,
                MassBankPeakRecord.mz,
                MassBankPeakRecord.intensity,
                MassBankPeakRecord.relative_intensity,
            )
            .join(
                MassBankPeakRecord,
                MassBankPeakRecord.massbank_record_id == MassBankRecord.id,
            )
            .where(MassBankRecord.accession_id.in_(accession_ids))
            .order_by(
                MassBankRecord.accession_id,
                MassBankPeakRecord.peak_index,
            )
        )

        with self.engine.connect() as conn:
            return pd.read_sql(stmt, conn)

    # ------------------------------------------------------------------
    # SQL-based spectrum similarity search
    # ------------------------------------------------------------------

    def search_record_ids_by_cosine_similarity_sql(
        self,
        mz_list: np.ndarray | list[float],
        intensity_list: np.ndarray | list[float],
        *,
        top_n: int = 10,
        mz_tolerance: float = 0.01,
        min_matched_peaks: int = 1,
        ion_mode: str | None = None,
        precursor_mz: float | None = None,
        precursor_tolerance: float | None = None,
    ) -> pd.DataFrame:
        """Search similar MassBank records using SQL-based cosine similarity.

        Returns
        -------
        pandas.DataFrame
            Columns include:
            - id
            - cosine_score
            - matched_peak_count
            - dot_product
            - reference_norm_square

        Notes
        -----
        The query spectrum is inserted into a temporary SQLite table.
        Most similarity calculation is done by SQL.
        """
        query_mz, query_intensity = self._validate_spectrum_arrays(
            mz_list=mz_list,
            intensity_list=intensity_list,
        )

        if query_mz.size == 0:
            return pd.DataFrame(
                columns=[
                    "id",
                    "cosine_score",
                    "matched_peak_count",
                    "dot_product",
                    "reference_norm_square",
                ]
            )

        query_norm_square = float(np.sum(query_intensity * query_intensity))

        if query_norm_square <= 0.0:
            return pd.DataFrame(
                columns=[
                    "id",
                    "cosine_score",
                    "matched_peak_count",
                    "dot_product",
                    "reference_norm_square",
                ]
            )

        query_peaks_df = pd.DataFrame(
            {
                "query_peak_index": np.arange(query_mz.size, dtype=int),
                "mz": query_mz.astype(float),
                "intensity": query_intensity.astype(float),
                "mz_lower": query_mz.astype(float) - float(mz_tolerance),
                "mz_upper": query_mz.astype(float) + float(mz_tolerance),
            }
        )

        where_clauses: list[str] = []
        params: dict[str, int | float | str] = {
            "query_norm_square": query_norm_square,
            "top_n": int(top_n),
            "min_matched_peaks": int(min_matched_peaks),
        }

        if ion_mode is not None:
            where_clauses.append("r.ion_mode = :ion_mode")
            params["ion_mode"] = ion_mode

        if precursor_mz is not None and precursor_tolerance is not None:
            where_clauses.append(
                "r.precursor_mz BETWEEN :precursor_mz_lower AND :precursor_mz_upper"
            )
            params["precursor_mz_lower"] = float(precursor_mz - precursor_tolerance)
            params["precursor_mz_upper"] = float(precursor_mz + precursor_tolerance)

        candidate_where_sql = ""
        if where_clauses:
            candidate_where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
        WITH
        candidate_records AS (
            SELECT
                r.id
            FROM massbank_records AS r
            {candidate_where_sql}
        ),

        reference_norms AS (
            SELECT
                p.massbank_record_id AS id,
                SUM(p.intensity * p.intensity) AS reference_norm_square
            FROM massbank_peak_records AS p
            INNER JOIN candidate_records AS c
                ON c.id = p.massbank_record_id
            GROUP BY p.massbank_record_id
        ),

        matched_peak_candidates AS (
            SELECT
                p.massbank_record_id AS id,
                q.query_peak_index,
                p.peak_index AS reference_peak_index,
                q.intensity AS query_intensity,
                p.intensity AS reference_intensity,
                ABS(q.mz - p.mz) AS mz_error
            FROM query_peaks AS q
            INNER JOIN massbank_peak_records AS p
                ON p.mz BETWEEN q.mz_lower AND q.mz_upper
            INNER JOIN candidate_records AS c
                ON c.id = p.massbank_record_id
        ),

        best_match_per_query_peak AS (
            SELECT
                id,
                query_peak_index,
                reference_peak_index,
                query_intensity,
                reference_intensity,
                mz_error
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY id, query_peak_index
                        ORDER BY mz_error ASC
                    ) AS rn
                FROM matched_peak_candidates
            )
            WHERE rn = 1
        ),

        scores AS (
            SELECT
                id,
                SUM(query_intensity * reference_intensity) AS dot_product,
                COUNT(*) AS matched_peak_count
            FROM best_match_per_query_peak
            GROUP BY id
        )

        SELECT
            s.id,
            s.dot_product / SQRT(:query_norm_square * n.reference_norm_square)
                AS cosine_score,
            s.matched_peak_count,
            s.dot_product,
            n.reference_norm_square
        FROM scores AS s
        INNER JOIN reference_norms AS n
            ON n.id = s.id
        WHERE s.matched_peak_count >= :min_matched_peaks
        AND n.reference_norm_square > 0
        ORDER BY cosine_score DESC, matched_peak_count DESC
        LIMIT :top_n
        """

        with self.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS query_peaks"))

            conn.execute(
                text(
                    """
                    CREATE TEMP TABLE query_peaks (
                        query_peak_index INTEGER NOT NULL,
                        mz REAL NOT NULL,
                        intensity REAL NOT NULL,
                        mz_lower REAL NOT NULL,
                        mz_upper REAL NOT NULL
                    )
                    """
                )
            )

            query_peaks_df.to_sql(
                "query_peaks",
                conn,
                if_exists="append",
                index=False,
            )

            result_df = pd.read_sql(
                text(sql),
                conn,
                params=params,
            )

            conn.execute(text("DROP TABLE IF EXISTS query_peaks"))

        return result_df

    def get_records_by_ids_dataframe(
        self,
        record_ids: list[int] | np.ndarray,
    ) -> pd.DataFrame:
        """Get MassBank records by internal record ids as a DataFrame."""
        record_ids = [int(record_id) for record_id in list(record_ids)]

        if not record_ids:
            return pd.DataFrame()

        stmt = (
            select(MassBankRecord)
            .where(MassBankRecord.id.in_(record_ids))
        )

        with self.engine.connect() as conn:
            records_df = pd.read_sql(stmt, conn)

        if records_df.empty:
            return records_df

        order_df = pd.DataFrame(
            {
                "id": record_ids,
                "_search_order": list(range(len(record_ids))),
            }
        )

        records_df = records_df.merge(
            order_df,
            on="id",
            how="inner",
        )

        records_df = records_df.sort_values("_search_order")
        records_df = records_df.drop(columns=["_search_order"])
        records_df = records_df.reset_index(drop=True)

        return records_df

    def search_records_by_cosine_similarity_sql_dataframe(
        self,
        mz_list: np.ndarray | list[float],
        intensity_list: np.ndarray | list[float],
        *,
        top_n: int = 10,
        mz_tolerance: float = 0.01,
        min_matched_peaks: int = 1,
        ion_mode: str | None = None,
        precursor_mz: float | None = None,
        precursor_tolerance: float | None = None,
    ) -> pd.DataFrame:
        """Search MassBank records by SQL-based cosine similarity.

        This method first calculates top-N record ids by SQL,
        then fetches all MassBankRecord columns as pandas DataFrame.

        Returns
        -------
        pandas.DataFrame
            Search score columns + all MassBankRecord columns.
        """
        score_df = self.search_record_ids_by_cosine_similarity_sql(
            mz_list=mz_list,
            intensity_list=intensity_list,
            top_n=top_n,
            mz_tolerance=mz_tolerance,
            min_matched_peaks=min_matched_peaks,
            ion_mode=ion_mode,
            precursor_mz=precursor_mz,
            precursor_tolerance=precursor_tolerance,
        )

        if score_df.empty:
            return pd.DataFrame()

        record_ids = score_df["id"].astype(int).tolist()
        records_df = self.get_records_by_ids_dataframe(record_ids)

        if records_df.empty:
            return pd.DataFrame()

        result_df = score_df.merge(
            records_df,
            on="id",
            how="inner",
        )

        result_df = result_df.sort_values(
            ["cosine_score", "matched_peak_count"],
            ascending=[False, False],
        )

        result_df = result_df.reset_index(drop=True)
        result_df.insert(0, "rank", np.arange(1, len(result_df) + 1))

        return result_df

    @staticmethod
    def _validate_spectrum_arrays(
        mz_list: np.ndarray | list[float],
        intensity_list: np.ndarray | list[float],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Validate query spectrum arrays."""
        mz_array = np.asarray(mz_list, dtype=float)
        intensity_array = np.asarray(intensity_list, dtype=float)

        if mz_array.ndim != 1:
            raise ValueError("mz_list must be a 1D array.")

        if intensity_array.ndim != 1:
            raise ValueError("intensity_list must be a 1D array.")

        if mz_array.shape[0] != intensity_array.shape[0]:
            raise ValueError(
                "mz_list and intensity_list must have the same length."
            )

        mask = (
            np.isfinite(mz_array)
            & np.isfinite(intensity_array)
            & (intensity_array > 0)
        )

        mz_array = mz_array[mask]
        intensity_array = intensity_array[mask]

        return mz_array, intensity_array