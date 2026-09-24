from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from massbank_rdf.gui.workflows.msp_kg.result_chat_tab import (
    write_metadata_enrichment_tsvs,
)
from massbank_rdf.services.metadata_enrichment import (
    analyze_all_metadata_enrichment,
    extract_metadata_entities,
)


KEY_A = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"
KEY_B = "CCCCCCCCCCCCCC-DDDDDDDDDD-E"


def kg_evidence() -> dict:
    return {
        "features": [
            {
                "inchikey": KEY_A,
                "entities": {
                    "diseases": {"hmdb": [{"label": "Disease A"}]},
                    "pathways": {"hmdb": [{"label": "Pathway A"}]},
                    "biospecimens": {"hmdb": [{"id": "Blood"}]},
                },
            },
            {
                "inchikey": KEY_B,
                "entities": {
                    "diseases": {"hmdb": [{"label": "Disease B"}]},
                    "pathways": {"pc": [{"label": "Pathway B"}]},
                    "activities": {"ks": [{"label": "Activity B"}]},
                },
            },
        ]
    }


class TestMetadataEnrichment(unittest.TestCase):
    def setUp(self) -> None:
        self.annotations = pd.DataFrame(
            [
                {
                    "spectrum_uid": f"RP::{index}",
                    "source_file": "rp.msp",
                    "sample_class": "RP",
                }
                for index in range(10)
            ]
            + [
                {
                    "spectrum_uid": f"WT::{index}",
                    "source_file": "wt.msp",
                    "sample_class": "WT",
                }
                for index in range(10)
            ]
        )
        self.candidates = pd.DataFrame(
            [
                {
                    "spectrum_uid": f"RP::{index}",
                    "inchikey": KEY_A,
                    "selected_for_kg": True,
                }
                for index in range(7)
            ]
            + [
                {
                    "spectrum_uid": f"WT::{index}",
                    "inchikey": KEY_B,
                    "selected_for_kg": True,
                }
                for index in range(7)
            ]
        )

    def test_extracts_entities_for_all_requested_metadata_types(self) -> None:
        entities, links = extract_metadata_entities(
            kg_evidence(),
            ["diseases", "pathways", "activities"],
        )
        self.assertEqual(len(entities), 5)
        self.assertEqual(set(links["metadata_type"]), {
            "diseases", "pathways", "activities",
        })

    def test_runs_every_entity_by_class_test_with_fdr(self) -> None:
        result, links = analyze_all_metadata_enrichment(
            kg_evidence=kg_evidence(),
            annotation_df=self.annotations,
            candidate_df=self.candidates,
            metadata_types=["diseases", "pathways"],
        )
        # Four unique entities, tested against both RP and WT.
        self.assertEqual(len(result), 8)
        self.assertIn("fdr_bh_global", result)
        self.assertIn("fdr_bh_by_metadata_type", result)
        self.assertIn("significant_global", result)
        disease_a_rp = result[
            (result["entity_label"] == "Disease A")
            & (result["sample_class"] == "RP")
        ].iloc[0]
        self.assertEqual(disease_a_rp["class_spectra"], 7)
        self.assertEqual(disease_a_rp["other_spectra"], 0)
        self.assertTrue(disease_a_rp["significant_global"])
        self.assertEqual(len(links), 4)

    def test_all_metadata_results_are_downloadable_as_tsv(self) -> None:
        result, links = analyze_all_metadata_enrichment(
            kg_evidence=kg_evidence(),
            annotation_df=self.annotations,
            candidate_df=self.candidates,
            metadata_types=["diseases"],
        )
        significant = result[result["significant_global"]]
        paths = write_metadata_enrichment_tsvs(result, significant, links)
        self.assertEqual(len(paths), 3)
        for path in paths:
            self.assertTrue(Path(path).is_file())
            self.assertIn("\t", Path(path).read_text(encoding="utf-8").splitlines()[0])


if __name__ == "__main__":
    unittest.main()
