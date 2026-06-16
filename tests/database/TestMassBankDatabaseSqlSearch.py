from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from massbank_rdf.db.massbank.database import MassBankDatabase
from massbank_rdf.db.massbank.tables.massbank_record import MassBankRecord
from massbank_rdf.db.massbank.tables.massbank_peak_record import MassBankPeakRecord
from massbank_rdf.db.massbank.tables.vocabulary import (
    IonMode,
    MSType,
    PrecursorType,
)


class TestMassBankDatabaseSqlSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_massbank.sqlite3"

        self.db = MassBankDatabase(db_path=self.db_path)
        self.db.recreate_tables()

        self._insert_test_data()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _insert_test_data(self) -> None:
        """Insert small MassBank-like test dataset."""
        with self.db.session() as session:
            session.add_all(
                [
                    PrecursorType(precursor_type="[M+H]+"),
                    MSType(ms_type="MS2"),
                    IonMode(ion_mode="POSITIVE"),
                    IonMode(ion_mode="NEGATIVE"),
                ]
            )
            session.flush()

            matched_record = MassBankRecord(
                accession_id="REC_MATCH",
                name="Matched compound",
                smiles="CCO",
                inchikey="MATCHEDINCHIKEY0000000000",
                formula="C2H6O",
                precursor_mz=100.0,
                precursor_type="[M+H]+",
                ms_type="MS2",
                ion_mode="POSITIVE",
                collision_energy="40%",
                retention_time="1.0 min",
            )

            weak_record = MassBankRecord(
                accession_id="REC_WEAK",
                name="Weak compound",
                smiles="CCC",
                inchikey="WEAKINCHIKEY000000000000",
                formula="C3H8",
                precursor_mz=100.0,
                precursor_type="[M+H]+",
                ms_type="MS2",
                ion_mode="POSITIVE",
                collision_energy="40%",
                retention_time="2.0 min",
            )

            negative_record = MassBankRecord(
                accession_id="REC_NEGATIVE",
                name="Negative compound",
                smiles="CCCC",
                inchikey="NEGINCHIKEY0000000000000",
                formula="C4H10",
                precursor_mz=100.0,
                precursor_type="[M+H]+",
                ms_type="MS2",
                ion_mode="NEGATIVE",
                collision_energy="40%",
                retention_time="3.0 min",
            )

            session.add_all([matched_record, weak_record, negative_record])
            session.flush()

            session.add_all(
                [
                    # Strong match: query peaks are close to these peaks.
                    MassBankPeakRecord(
                        massbank_record_id=matched_record.id,
                        peak_index=0,
                        seq=1,
                        mz=60.000,
                        intensity=100.0,
                        relative_intensity=999.0,
                    ),
                    MassBankPeakRecord(
                        massbank_record_id=matched_record.id,
                        peak_index=1,
                        seq=2,
                        mz=80.000,
                        intensity=50.0,
                        relative_intensity=500.0,
                    ),

                    # Weak match: only one peak matches.
                    MassBankPeakRecord(
                        massbank_record_id=weak_record.id,
                        peak_index=0,
                        seq=1,
                        mz=60.000,
                        intensity=100.0,
                        relative_intensity=999.0,
                    ),
                    MassBankPeakRecord(
                        massbank_record_id=weak_record.id,
                        peak_index=1,
                        seq=2,
                        mz=150.000,
                        intensity=50.0,
                        relative_intensity=500.0,
                    ),

                    # Negative mode record: same peaks as matched record,
                    # but should be filtered out when ion_mode="POSITIVE".
                    MassBankPeakRecord(
                        massbank_record_id=negative_record.id,
                        peak_index=0,
                        seq=1,
                        mz=60.000,
                        intensity=100.0,
                        relative_intensity=999.0,
                    ),
                    MassBankPeakRecord(
                        massbank_record_id=negative_record.id,
                        peak_index=1,
                        seq=2,
                        mz=80.000,
                        intensity=50.0,
                        relative_intensity=500.0,
                    ),
                ]
            )

            session.commit()

    def test_search_record_ids_by_cosine_similarity_sql_returns_top_ids(self) -> None:
        query_mz = np.array([60.000, 80.000])
        query_intensity = np.array([100.0, 50.0])

        df = self.db.search_record_ids_by_cosine_similarity_sql(
            mz_list=query_mz,
            intensity_list=query_intensity,
            top_n=2,
            mz_tolerance=0.01,
            min_matched_peaks=1,
            ion_mode="POSITIVE",
        )

        self.assertFalse(df.empty)
        self.assertIn("id", df.columns)
        self.assertIn("cosine_score", df.columns)
        self.assertIn("matched_peak_count", df.columns)

        top_record_id = int(df.iloc[0]["id"])
        top_record = self.db.get_record_by_id(top_record_id)

        self.assertIsNotNone(top_record)
        self.assertEqual(top_record.accession_id, "REC_MATCH")
        self.assertAlmostEqual(float(df.iloc[0]["cosine_score"]), 1.0, places=6)
        self.assertEqual(int(df.iloc[0]["matched_peak_count"]), 2)

    def test_search_records_by_cosine_similarity_sql_dataframe_returns_record_columns(self) -> None:
        query_mz = np.array([60.000, 80.000])
        query_intensity = np.array([100.0, 50.0])

        df = self.db.search_records_by_cosine_similarity_sql_dataframe(
            mz_list=query_mz,
            intensity_list=query_intensity,
            top_n=5,
            mz_tolerance=0.01,
            min_matched_peaks=1,
            ion_mode="POSITIVE",
        )

        self.assertFalse(df.empty)

        expected_columns = {
            "rank",
            "id",
            "cosine_score",
            "matched_peak_count",
            "accession_id",
            "name",
            "smiles",
            "inchikey",
            "formula",
            "precursor_mz",
            "precursor_type",
            "ms_type",
            "ion_mode",
        }

        self.assertTrue(expected_columns.issubset(set(df.columns)))
        self.assertEqual(df.iloc[0]["accession_id"], "REC_MATCH")
        self.assertEqual(df.iloc[0]["name"], "Matched compound")

    def test_search_respects_min_matched_peaks(self) -> None:
        query_mz = np.array([60.000, 80.000])
        query_intensity = np.array([100.0, 50.0])

        df = self.db.search_records_by_cosine_similarity_sql_dataframe(
            mz_list=query_mz,
            intensity_list=query_intensity,
            top_n=10,
            mz_tolerance=0.01,
            min_matched_peaks=2,
            ion_mode="POSITIVE",
        )

        self.assertFalse(df.empty)

        accession_ids = set(df["accession_id"].tolist())

        self.assertIn("REC_MATCH", accession_ids)
        self.assertNotIn("REC_WEAK", accession_ids)

    def test_search_respects_ion_mode_filter(self) -> None:
        query_mz = np.array([60.000, 80.000])
        query_intensity = np.array([100.0, 50.0])

        df = self.db.search_records_by_cosine_similarity_sql_dataframe(
            mz_list=query_mz,
            intensity_list=query_intensity,
            top_n=10,
            mz_tolerance=0.01,
            min_matched_peaks=1,
            ion_mode="NEGATIVE",
        )

        self.assertFalse(df.empty)
        self.assertEqual(df.iloc[0]["accession_id"], "REC_NEGATIVE")
        self.assertTrue((df["ion_mode"] == "NEGATIVE").all())

    def test_search_respects_precursor_mz_filter(self) -> None:
        query_mz = np.array([60.000, 80.000])
        query_intensity = np.array([100.0, 50.0])

        df = self.db.search_records_by_cosine_similarity_sql_dataframe(
            mz_list=query_mz,
            intensity_list=query_intensity,
            top_n=10,
            mz_tolerance=0.01,
            min_matched_peaks=1,
            precursor_mz=100.0,
            precursor_tolerance=0.001,
        )

        self.assertFalse(df.empty)
        self.assertTrue((df["precursor_mz"] == 100.0).all())

        empty_df = self.db.search_records_by_cosine_similarity_sql_dataframe(
            mz_list=query_mz,
            intensity_list=query_intensity,
            top_n=10,
            mz_tolerance=0.01,
            min_matched_peaks=1,
            precursor_mz=200.0,
            precursor_tolerance=0.001,
        )

        self.assertTrue(empty_df.empty)

    def test_get_records_by_ids_dataframe_preserves_order(self) -> None:
        match_id = self.db.get_record_id("REC_MATCH")
        weak_id = self.db.get_record_id("REC_WEAK")

        self.assertIsNotNone(match_id)
        self.assertIsNotNone(weak_id)

        df = self.db.get_records_by_ids_dataframe([weak_id, match_id])

        self.assertFalse(df.empty)
        self.assertEqual(df.iloc[0]["accession_id"], "REC_WEAK")
        self.assertEqual(df.iloc[1]["accession_id"], "REC_MATCH")

    def test_search_returns_empty_dataframe_for_no_valid_query_peaks(self) -> None:
        query_mz = np.array([60.000, 80.000])
        query_intensity = np.array([0.0, -1.0])

        df = self.db.search_records_by_cosine_similarity_sql_dataframe(
            mz_list=query_mz,
            intensity_list=query_intensity,
            top_n=10,
            mz_tolerance=0.01,
            min_matched_peaks=1,
        )

        self.assertTrue(df.empty)

    def test_validate_spectrum_arrays_raises_for_length_mismatch(self) -> None:
        query_mz = np.array([60.000, 80.000])
        query_intensity = np.array([100.0])

        with self.assertRaises(ValueError):
            self.db.search_record_ids_by_cosine_similarity_sql(
                mz_list=query_mz,
                intensity_list=query_intensity,
            )


if __name__ == "__main__":
    unittest.main()