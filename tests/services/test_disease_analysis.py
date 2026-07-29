from __future__ import annotations

import unittest

import pandas as pd

from massbank_rdf.services.disease_analysis import (
    analyze_disease_class_enrichment,
    disease_inchikey_map,
    local_related_disease_names,
    sample_classes_from_results,
)


KEY = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"


class TestDiseaseAnalysis(unittest.TestCase):
    def test_extracts_unique_disease_names_and_inchikeys(self) -> None:
        evidence = {
            "features": [
                {
                    "inchikey": KEY,
                    "entities": {
                        "diseases": {
                            "hmdb": [
                                {"label": "Alzheimer's disease"},
                                {"label": "Alzheimer's disease"},
                            ]
                        }
                    },
                }
            ]
        }
        result = disease_inchikey_map(evidence)
        self.assertEqual(result, {"Alzheimer's disease": {KEY}})

    def test_japanese_alias_selects_existing_english_disease(self) -> None:
        result = local_related_disease_names(
            "アルツハイマーに関連する疾患",
            ["Alzheimer's disease", "Diabetes mellitus"],
        )
        self.assertEqual(result, ["Alzheimer's disease"])

    def test_spectrum_level_class_enrichment_and_fdr(self) -> None:
        annotations = pd.DataFrame(
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
        candidates = pd.DataFrame(
            [
                {
                    "spectrum_uid": f"RP::{index}",
                    "source_file": "rp.msp",
                    "sample_class": "RP",
                    "inchikey": KEY,
                    "accession_id": f"MB-{index}",
                    "selected_for_kg": True,
                    "score": 0.9,
                }
                for index in range(6)
            ]
            + [
                {
                    "spectrum_uid": "WT::0",
                    "source_file": "wt.msp",
                    "sample_class": "WT",
                    "inchikey": KEY,
                    "accession_id": "MB-WT",
                    "selected_for_kg": False,
                    "score": 0.8,
                }
            ]
        )
        statistics, spectra = analyze_disease_class_enrichment(
            disease_names=["Alzheimer's disease"],
            target_class="rp",
            disease_to_inchikeys={"Alzheimer's disease": {KEY}},
            annotation_df=annotations,
            candidate_df=candidates,
        )

        row = statistics.iloc[0]
        self.assertEqual(row["sample_class"], "RP")
        self.assertEqual(row["class_spectra"], 6)
        self.assertEqual(row["other_spectra"], 0)
        self.assertTrue(row["significant_in_class"])
        self.assertEqual(len(spectra), 6)

    def test_collects_sample_classes(self) -> None:
        annotations = pd.DataFrame({"sample_class": ["WT", "RP", "WT"]})
        self.assertEqual(
            sample_classes_from_results(annotations, pd.DataFrame()),
            ["RP", "WT"],
        )


if __name__ == "__main__":
    unittest.main()
