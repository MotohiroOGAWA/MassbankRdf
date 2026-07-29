from __future__ import annotations

import unittest

import pandas as pd

from massbank_rdf.services.kg.candidate_ranking import (
    filter_similarity_candidates,
    rank_candidates_with_kg_metadata,
    rank_grouped_candidates_with_kg_metadata,
)


class StubScoreService:
    def __init__(self):
        self.calls = []

    def scores_for_inchikeys(self, inchikeys):
        self.calls.append(list(inchikeys))
        return pd.DataFrame(
            [
                {"inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C", "kg_metadata_count": 1},
                {"inchikey": "CCCCCCCCCCCCCC-DDDDDDDDDD-E", "kg_metadata_count": 100},
            ]
        )


class TestCandidateRanking(unittest.TestCase):
    def test_similarity_at_or_below_threshold_is_removed(self) -> None:
        source = pd.DataFrame({"score": [0.7, 0.5, 0.49]})
        result = filter_similarity_candidates(
            source,
            0.5,
            score_column="score",
        )
        self.assertEqual(result["score"].tolist(), [0.7])

    def test_rank_sum_balances_similarity_and_metadata(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "score": 0.9,
                },
                {
                    "inchikey": "CCCCCCCCCCCCCC-DDDDDDDDDD-E",
                    "score": 0.8,
                },
            ]
        )
        result = rank_candidates_with_kg_metadata(
            source,
            StubScoreService(),
        )
        first = result.iloc[0]
        second = result.iloc[1]
        self.assertEqual(first["combined_rank_sum"], 3)
        self.assertEqual(second["combined_rank_sum"], 3)
        self.assertEqual(first["score"], 0.9)
        self.assertEqual(second["kg_metadata_count"], 100)

    def test_grouped_ranking_fetches_kg_scores_once(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "spectrum_uid": "sample-a::1",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "score": 0.9,
                },
                {
                    "spectrum_uid": "sample-a::1",
                    "inchikey": "CCCCCCCCCCCCCC-DDDDDDDDDD-E",
                    "score": 0.8,
                },
                {
                    "spectrum_uid": "sample-b::1",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "score": 0.7,
                },
            ]
        )
        score_service = StubScoreService()
        result = rank_grouped_candidates_with_kg_metadata(
            source,
            score_service,
            group_column="spectrum_uid",
        )

        self.assertEqual(len(score_service.calls), 1)
        self.assertCountEqual(
            score_service.calls[0],
            [
                "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                "CCCCCCCCCCCCCC-DDDDDDDDDD-E",
            ],
        )
        self.assertEqual(len(result), 3)

    def test_grouped_ranking_can_ignore_kg_metadata_rank(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "spectrum_uid": "sample-a::1",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "score": 0.9,
                },
                {
                    "spectrum_uid": "sample-a::1",
                    "inchikey": "CCCCCCCCCCCCCC-DDDDDDDDDD-E",
                    "score": 0.8,
                },
            ]
        )
        result = rank_grouped_candidates_with_kg_metadata(
            source,
            StubScoreService(),
            group_column="spectrum_uid",
            use_kg_metadata_rank=False,
        )
        self.assertEqual(result.iloc[0]["score"], 0.9)
        self.assertEqual(result.iloc[0]["combined_rank_sum"], 1)
        self.assertEqual(
            result.iloc[0]["ranking_mode"],
            "massbank_similarity_only",
        )
        self.assertEqual(result.iloc[1]["kg_metadata_count"], 100)

    def test_missing_inchikey_has_zero_metadata_count(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "spectrum_uid": "sample-a::1",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "score": 0.9,
                },
                {
                    "spectrum_uid": "sample-a::1",
                    "inchikey": None,
                    "score": 0.8,
                },
            ]
        )
        result = rank_grouped_candidates_with_kg_metadata(
            source,
            StubScoreService(),
            group_column="spectrum_uid",
        )
        missing = result[result["inchikey"].isna()].iloc[0]
        self.assertEqual(missing["kg_metadata_count"], 0)
        self.assertTrue(pd.isna(missing["combined_rank"]))

    def test_all_missing_inchikeys_have_zero_metadata_count(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "spectrum_uid": "sample-a::1",
                    "inchikey": None,
                    "score": 0.8,
                },
            ]
        )
        result = rank_grouped_candidates_with_kg_metadata(
            source,
            StubScoreService(),
            group_column="spectrum_uid",
        )
        self.assertEqual(result.iloc[0]["kg_metadata_count"], 0)


if __name__ == "__main__":
    unittest.main()
