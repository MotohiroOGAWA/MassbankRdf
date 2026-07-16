from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from data.db.build_short_inchikey_databases import (
    build_short_inchikey_databases,
)
from data.db.build_kg_1nf_sqlite import build_1nf_database
from massbank_rdf.db.kg.build_sqlite import build_short_inchikey_summary
from massbank_rdf.db.kg.database import KgDatabase


FULL_A = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"
FULL_B = "AAAAAAAAAAAAAA-DDDDDDDDDD-E"
SHORT = "AAAAAAAAAAAAAA"


class TestShortInchikeyDatabaseBuilder(unittest.TestCase):
    def test_massbank_summary_is_aggregated_by_short_key(self) -> None:
        full_summary = pd.DataFrame(
            [
                {
                    "inchikey": FULL_A,
                    "massbank_record_count": 2,
                    "example_accession_id": "A1",
                    "example_name": "first",
                    "example_formula": "C1",
                },
                {
                    "inchikey": FULL_B,
                    "massbank_record_count": 3,
                    "example_accession_id": "A2",
                    "example_name": "second",
                    "example_formula": "C1",
                },
            ]
        )

        summary, mappings = build_short_inchikey_summary(full_summary)

        self.assertEqual(summary["inchikey"].tolist(), [SHORT])
        self.assertEqual(summary["massbank_record_count"].tolist(), [5])
        self.assertEqual(len(mappings), 2)
        self.assertEqual(set(mappings["short_inchikey"]), {SHORT})

    def test_short_database_import_links_full_sparql_results_to_short(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "short.sqlite3"
            db = KgDatabase(db_path, use_short_inchikey=True)
            db.create_tables()
            summary = pd.DataFrame(
                [{"inchikey": SHORT, "massbank_record_count": 2}]
            )
            data = {
                "pubchem_compound": pd.DataFrame(
                    [
                        {
                            "value_inchikey": FULL_A,
                            "pubchem_compound": "compound:1",
                        },
                        {
                            "value_inchikey": FULL_B,
                            "pubchem_compound": "compound:2",
                        },
                    ]
                ),
                "pubchem_pathway": pd.DataFrame(),
                "hmdb": pd.DataFrame(),
                "knapsack_activity": pd.DataFrame(),
            }

            db.import_kg_dataframes(
                data,
                inchikey_summary_df=summary,
                replace_for_inchikeys=[SHORT],
            )
            db.replace_inchikey_short_mappings(
                pd.DataFrame(
                    [
                        {"inchikey": FULL_A, "short_inchikey": SHORT},
                        {"inchikey": FULL_B, "short_inchikey": SHORT},
                    ]
                )
            )

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT inchikey FROM kg_inchikeys").fetchall(),
                [(SHORT,)],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM pubchem_compound_inchikeys"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM inchikey_short_inchikeys"
                ).fetchone()[0],
                2,
            )
            conn.close()

            one_nf_path = Path(directory) / "short_1nf.sqlite3"
            build_1nf_database(db_path, one_nf_path, overwrite=False)
            one_nf = sqlite3.connect(one_nf_path)
            self.assertEqual(
                one_nf.execute("SELECT inchikey FROM kg_inchikeys").fetchall(),
                [(SHORT,)],
            )
            self.assertEqual(
                one_nf.execute(
                    "SELECT COUNT(*) FROM inchikey_short_inchikeys"
                ).fetchone()[0],
                2,
            )
            one_nf.close()

    @patch("data.db.build_short_inchikey_databases.build_1nf_database")
    @patch("data.db.build_short_inchikey_databases.build_sqlite")
    def test_wrapper_queries_short_before_building_1nf(
        self,
        build_sqlite_mock,
        build_1nf_mock,
    ) -> None:
        build_short_inchikey_databases(
            massbank_db_path=Path("massbank.sqlite3"),
            short_db=Path("short.sqlite3"),
            short_1nf_db=Path("short_1nf.sqlite3"),
            save_kg_json=False,
        )

        self.assertTrue(build_sqlite_mock.call_args.kwargs["use_short_inchikey"])
        build_1nf_mock.assert_called_once_with(
            Path("short.sqlite3"),
            Path("short_1nf.sqlite3"),
            overwrite=True,
        )


if __name__ == "__main__":
    unittest.main()
