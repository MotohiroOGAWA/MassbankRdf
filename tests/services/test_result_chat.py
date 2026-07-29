from __future__ import annotations

import unittest

import pandas as pd

from massbank_rdf.services.result_chat import retrieve_result_chat_evidence


INCHIKEY = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"


def evidence() -> dict:
    return {
        "features": [
            {
                "inchikey": INCHIKEY,
                "summary": {"diseases": {"hmdb": 1}},
                "entities": {
                    "diseases": {
                        "hmdb": [{"label": "Alzheimer's disease"}],
                    }
                },
            }
        ]
    }


def candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "inchikey": INCHIKEY,
                "accession_id": "MSBNK-TEST-0001",
                "spectrum_uid": "sample.msp::1",
                "source_file": "sample.msp",
                "sample_class": "PR",
                "score": 0.91,
                "kg_metadata_count": 5,
            }
        ]
    )


class TestResultChatRetrieval(unittest.TestCase):
    def test_japanese_disease_alias_retrieves_bounded_evidence(self) -> None:
        result = retrieve_result_chat_evidence(
            "この結果でアルツハイマーに関連する病気は観測されていますか？",
            kg_evidence=evidence(),
            candidate_df=candidates(),
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.scope_inchikeys, [INCHIKEY])
        self.assertEqual(len(result.context["kg_features"]), 1)
        self.assertEqual(len(result.evidence_table), 1)

    def test_follow_up_reuses_previous_inchikey_scope(self) -> None:
        other_key = "CCCCCCCCCCCCCC-DDDDDDDDDD-E"
        candidate_rows = pd.concat(
            [
                candidates(),
                pd.DataFrame(
                    [
                        {
                            "inchikey": other_key,
                            "accession_id": "MSBNK-TEST-0002",
                            "spectrum_uid": "other.msp::1",
                            "source_file": "other.msp",
                            "sample_class": "PR",
                            "score": 0.8,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        result = retrieve_result_chat_evidence(
            "その中でPRのスペクトルを表示して",
            kg_evidence=evidence(),
            candidate_df=candidate_rows,
            previous_scope=[INCHIKEY],
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.scope_inchikeys, [INCHIKEY])
        self.assertEqual(len(result.context["massbank_candidates"]), 1)
        self.assertEqual(result.context["massbank_candidates"][0]["sample_class"], "PR")

    def test_broad_request_is_refused_before_llm(self) -> None:
        result = retrieve_result_chat_evidence(
            "全データをすべて解析してください",
            kg_evidence=evidence(),
            candidate_df=candidates(),
        )
        self.assertFalse(result.accepted)
        self.assertIn("トークン", result.message)

    def test_no_match_returns_empty_evidence_without_external_guess(self) -> None:
        result = retrieve_result_chat_evidence(
            "Parkinson disease",
            kg_evidence=evidence(),
            candidate_df=candidates(),
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.context["matched_features"], [])


if __name__ == "__main__":
    unittest.main()
