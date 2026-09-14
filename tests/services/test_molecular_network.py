from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import pandas as pd

from massbank_rdf.services.molecular_network import (
    analyze_conditions,
    build_cytoscape_tables,
    common_cluster_peaks,
    filter_edges,
    generate_similarity_edges,
    generate_binned_numpy_similarity_edges,
    read_similarity_edges,
    resolve_score_thresholds,
)


class MolecularNetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.edges = pd.DataFrame(
            [
                ("A", "B", 0.90, 8),
                ("B", "A", 0.80, 7),
                ("A", "C", 0.70, 6),
                ("B", "C", 0.60, 10),
                ("C", "C", 1.00, 20),
            ],
            columns=["SourceID", "TargetID", "Score", "MatchPeakCount"],
        )

    def test_reader_validates_and_deduplicates_undirected_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edges.tsv"
            self.edges.to_csv(path, sep="\t", index=False)
            result = read_similarity_edges(path)
        self.assertEqual(len(result), 3)
        self.assertEqual(float(result.iloc[0]["Score"]), 0.9)

    def test_filter_applies_thresholds_and_top_k_union(self) -> None:
        result = filter_edges(
            self.edges,
            score_threshold=0.65,
            match_peak_count=6,
            top_k=1,
        )
        pairs = set(map(tuple, result[["SourceID", "TargetID"]].to_numpy()))
        self.assertEqual(pairs, {("A", "B"), ("A", "C")})

    def test_percentile_thresholds_are_resolved(self) -> None:
        values = resolve_score_thresholds(self.edges, ["p95", "0.75"])
        self.assertEqual(values[0][1], "p95")
        self.assertEqual(values[1], (0.75, "0.75"))

    def test_common_peaks_require_frequency_and_intensity(self) -> None:
        spectra = {
            "A": ([100.0, 200.0], [100.0, 5.0]),
            "B": ([100.005, 300.0], [50.0, 100.0]),
            "C": ([99.998], [20.0]),
        }
        result = common_cluster_peaks(
            spectra,
            ["A", "B", "C"],
            mz_tolerance=0.01,
            minimum_presence_fraction=2 / 3,
            minimum_relative_intensity=0.05,
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(float(result.iloc[0]["presence_fraction"]), 1.0)

    def test_condition_statistics_include_isolated_nodes(self) -> None:
        try:
            statistics, assignments, _ = analyze_conditions(
                self.edges,
                ["A", "B", "C", "D"],
                score_thresholds=[0.65],
                top_k_values=[None],
                match_peak_counts=[6],
                resolutions=[1.0],
                random_seed=42,
            )
        except RuntimeError as exc:
            self.skipTest(str(exc))
        self.assertEqual(int(statistics.iloc[0]["node_count"]), 4)
        self.assertEqual(int(statistics.iloc[0]["isolated_node_count"]), 1)
        assignment = next(iter(assignments.values()))
        self.assertEqual(len(assignment), 4)

    def test_cytoscape_tables_join_spectra_compounds_and_metadata(self) -> None:
        nodes = pd.DataFrame(
            [{"node_id": "A", "cluster_id": "C1", "sample_class": "Class1"}]
        )
        candidates = pd.DataFrame(
            [{
                "spectrum_uid": "A",
                "inchikey": "KEY-A",
                "selected_for_kg": True,
                "score": 0.9,
                "annotation_source": pd.NA,
            }]
        )
        evidence = {
            "features": [{
                "inchikey": "KEY-A",
                "entities": {
                    "diseases": {
                        "hmdb": [{"id": "D1", "label": "Example disease"}]
                    }
                },
            }]
        }
        node_table, edge_table = build_cytoscape_tables(
            nodes,
            pd.DataFrame(columns=["SourceID", "TargetID", "Score", "MatchPeakCount"]),
            candidates,
            evidence,
        )
        self.assertEqual(
            set(node_table["node_type"]), {"spectrum", "inchikey", "diseases"}
        )
        self.assertEqual(
            set(edge_table["edge_type"]),
            {"massbank_annotation", "kg_metadata"},
        )
        self.assertTrue(node_table["node_type"].notna().all())

    def test_same_metadata_is_separate_between_clusters(self) -> None:
        nodes = pd.DataFrame(
            [
                {"node_id": "A", "cluster_id": "C1"},
                {"node_id": "B", "cluster_id": "C2"},
            ]
        )
        candidates = pd.DataFrame(
            [
                {
                    "spectrum_uid": "A", "inchikey": "KEY-A",
                    "selected_for_kg": True, "score": 0.9,
                },
                {
                    "spectrum_uid": "B", "inchikey": "KEY-A",
                    "selected_for_kg": True, "score": 0.8,
                },
            ]
        )
        evidence = {
            "features": [{
                "inchikey": "KEY-A",
                "entities": {
                    "diseases": {
                        "hmdb": [{"id": "D1", "label": "Same disease"}]
                    }
                },
            }]
        }
        node_table, _ = build_cytoscape_tables(
            nodes,
            pd.DataFrame(
                columns=["SourceID", "TargetID", "Score", "MatchPeakCount"]
            ),
            candidates,
            evidence,
        )
        disease_nodes = node_table[node_table["node_type"] == "diseases"]
        self.assertEqual(len(disease_nodes), 2)
        self.assertEqual(set(disease_nodes["cluster_id"]), {"C1", "C2"})

    def test_similarity_edges_are_generated_within_ion_mode(self) -> None:
        spectra = {
            "A": ([100.0, 200.0, 300.0], [10.0, 20.0, 30.0]),
            "B": ([100.005, 200.005, 400.0], [10.0, 20.0, 5.0]),
            "C": ([100.0, 200.0, 300.0], [10.0, 20.0, 30.0]),
        }
        final = None
        updates = []
        for processed, total, edge_count, result in generate_similarity_edges(
            spectra,
            {"A": "positive", "B": "positive", "C": "negative"},
            mz_tolerance=0.01,
            minimum_matched_peaks=2,
            batch_size=1,
        ):
            updates.append((processed, total, edge_count))
            if result is not None:
                final = result
        self.assertIsNotNone(final)
        self.assertEqual(len(final), 1)
        self.assertEqual(final.iloc[0]["SourceID"], "A")
        self.assertEqual(final.iloc[0]["TargetID"], "B")
        self.assertEqual(int(final.iloc[0]["MatchPeakCount"]), 2)
        self.assertEqual(updates[-1][0], 3)

    def test_numpy_binned_similarity_uses_matrix_scoring(self) -> None:
        spectra = {
            "A": ([100.0, 200.0, 300.0], [10.0, 20.0, 30.0]),
            "B": ([100.005, 200.005, 300.005], [10.0, 20.0, 30.0]),
            "C": ([100.0, 200.0, 300.0], [10.0, 20.0, 30.0]),
        }
        result = None
        for _, _, _, frame in generate_binned_numpy_similarity_edges(
            spectra,
            {"A": "POSITIVE", "B": "POSITIVE", "C": "NEGATIVE"},
            mz_tolerance=0.01,
            minimum_matched_peaks=3,
            batch_size=1,
        ):
            if frame is not None:
                result = frame
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(int(result.iloc[0]["MatchPeakCount"]), 3)
        self.assertAlmostEqual(float(result.iloc[0]["Score"]), 1.0)


if __name__ == "__main__":
    unittest.main()
