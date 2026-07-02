"""Offline tests for the demo-local rehydrate helper (copied from production)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.llm_interpretation.rehydrate import (  # noqa: E402
    columnar_to_records,
    rehydrate_feature,
)


class RehydrateTests(unittest.TestCase):
    def test_columnar_to_records_zips_columns_and_rows(self) -> None:
        table = {"columns": ["a", "b"], "rows": [[1, 2], [3, 4]]}
        self.assertEqual(
            columnar_to_records(table),
            [{"a": 1, "b": 2}, {"a": 3, "b": 4}],
        )

    def test_rehydrate_feature_passes_through_nested_entities(self) -> None:
        feature = {
            "inchikey": "ABC",
            "summary": {"compounds": 1},
            "entities": {"compounds": {"pc": [{"id": "5"}]}},
        }
        result = rehydrate_feature(feature)
        self.assertEqual(result["inchikey"], "ABC")
        self.assertEqual(result["entities"]["compounds"], {"pc": [{"id": "5"}]})

    def test_rehydrate_feature_converts_columnar_entities(self) -> None:
        feature = {
            "inchikey": "XYZ",
            "entities": {"diseases": {"columns": ["id"], "rows": [["d1"]]}},
        }
        result = rehydrate_feature(feature)
        self.assertEqual(result["entities"]["diseases"], [{"id": "d1"}])


if __name__ == "__main__":
    unittest.main()
