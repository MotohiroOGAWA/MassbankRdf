from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.molecular_network.processor import (
    StageProgress, _prepare_spectra, build_molecular_network_processor,
)

KEY = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"
OTHER_KEY = "CCCCCCCCCCCCCC-DDDDDDDDDD-E"
MODULE = "massbank_rdf.gui.workflows.molecular_network.processor"


def record(name, metadata=""):
    return f"Name: {name}\n{metadata}Num Peaks: 3\n100 100\n120 80\n150 60\n\n"


def job():
    documents = [{"file_name": "sample.msp", "sample_class": "A", "source_text":
                  record("known", f"InChIKey: {KEY}\n") + record("known_neighbor")
                  + record("unknown1") + record("unknown2")}]
    return {
        "summary": {"workflow": "molecular_network", "readable_spectrum_count": 4},
        "msp_batch_job": {"mz_tolerance": 0.01, "ion_mode_column": "IONMODE"},
        "molecular_network_job": {
            "documents": documents,
            "edge_tsv": "SourceID\tTargetID\tScore\tMatchPeakCount\nknown\tknown_neighbor\t0.9\t3\nunknown1\tunknown2\t0.9\t3\n",
            "score_thresholds": [0.5], "top_k_values": [10], "match_peak_counts": [1],
            "resolutions": [0.1], "random_seed": 42, "selected_score": "0.5",
            "selected_top_k": 10, "selected_resolution": 0.1,
            "common_presence_fraction": 0.5, "common_relative_intensity": 0.05,
            "common_peak_limit": 10,
            "common_peak_settings": {"mz_tolerance": 0.01, "minimum_relative_intensity": 0.05,
                "common_peak_n": 10, "massbank_top_n": 10, "min_matched_peaks": 2,
                "minimum_similarity": 0.5, "max_massbank_inchikey": None, "ion_mode": None},
        },
    }


class ProcessorTest(unittest.TestCase):
    def run_job(self, payload, hits):
        store = TemporarySessionStore(ttl_seconds=60)
        store.set("test", payload)
        request = SimpleNamespace(request=SimpleNamespace(cookies={"molecular_network_session_id": "test"}, query_params={}))
        kg = Mock()
        kg.search_evidence_by_inchikeys.return_value = ({"metadata": {}, "features": [
            {"inchikey": OTHER_KEY, "entities": {"pathways": {"test": [{"name": "pathway"}]}}}
        ]}, {})
        with patch(f"{MODULE}.annotate_common_peaks_with_massbank", return_value={"massbank_hits": hits}) as search:
            updates = list(build_molecular_network_processor(store, kg)(request))
        result = store.get("test")
        self.addCleanup(shutil.rmtree, Path(result["output_directory"]).parent, True)
        return result, updates, search, kg

    def test_cluster_first_msp_annotation_and_cluster_only_fallback(self):
        result, updates, search, kg = self.run_job(job(), pd.DataFrame([
            {"inchikey": OTHER_KEY, "cosine_score": 0.8, "accession_id": "test"}
        ]))
        self.assertEqual(search.call_count, 1)
        self.assertEqual(set(kg.search_evidence_by_inchikeys.call_args.args[0]), {KEY, OTHER_KEY})
        self.assertEqual(kg.search_evidence_by_inchikeys.call_count, 1)
        rows = result["cluster_annotations_df"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(rows.structure_annotated_member_count), [0, 1])
        self.assertEqual(sorted(rows.annotation_coverage), [0, 0.5])
        edges = result["network_edges_df"]
        inferred = edges[edges.edge_type == "cluster_common_peak_massbank"]
        self.assertEqual(len(inferred), 1)
        self.assertTrue(inferred.iloc[0].source.startswith("cluster:"))
        self.assertEqual(len(result["spectrum_annotation_df"]), 4)
        self.assertTrue(result["network_precomputed"])
        self.assertTrue(Path(result["output_archive"]).is_file())
        self.assertTrue(all(html.count("<progress ") == 7 for _, html in updates))
        messages = [message for message, _ in updates]
        self.assertLess(next(i for i,m in enumerate(messages) if "Cluster conditions" in m),
                        next(i for i,m in enumerate(messages) if "MSP cluster annotations" in m))
        self.assertEqual(updates[-1][1].count('value="100.00"'), 7)
        self.assertIn("kg_metadata_found", rows.metadata_status.tolist())

    def test_smiles_prevents_fallback_without_inchikey(self):
        payload = job()
        payload["molecular_network_job"]["documents"][0]["source_text"] = (
            record("known", "SMILES: CCO\n") + record("known_neighbor")
            + record("unknown1", "InChI: InChI=1S/CH4/h1H4\n") + record("unknown2"))
        result, _, search, kg = self.run_job(payload, pd.DataFrame())
        search.assert_not_called()
        kg.search_evidence_by_inchikeys.assert_not_called()
        self.assertEqual(result["cluster_annotations_df"].structure_annotated_member_count.tolist(), [1, 1])

    def test_no_common_peak_hits_retains_unannotated_cluster(self):
        result, _, search, _ = self.run_job(job(), pd.DataFrame())
        self.assertEqual(search.call_count, 1)
        rows = result["cluster_annotations_df"]
        unknown = rows[rows.structure_annotated_member_count == 0].iloc[0]
        self.assertEqual(json.loads(unknown.common_peak_candidate_inchikeys), [])
        self.assertEqual(unknown.metadata_status, "no_kg_metadata")

    def test_missing_match_counts_are_computed(self):
        payload = job()
        payload["molecular_network_job"]["edge_tsv"] = "SourceID\tTargetID\tScore\nknown\tknown_neighbor\t0.9\nunknown1\tunknown2\t0.9\n"
        result, _, _, _ = self.run_job(payload, pd.DataFrame())
        edges = result["network_edges_df"]
        self.assertEqual(edges[edges.edge_type == "spectrum_similarity"].match_peak_count.tolist(), [3, 3])

    def test_zero_based_ids_include_records_without_spectra(self):
        payload = job()
        payload["molecular_network_job"]["documents"][0]["source_text"] = (
            record("2", f"InChIKey: {KEY}\n")
            + "Name: empty\nNum Peaks: 0\n\n"
            + record("last")
        )
        payload["molecular_network_job"]["edge_tsv"] = (
            "SourceID\tTargetID\tScore\tMatchPeakCount\n0\t1\t0.9\t3\n1\t2\t0.9\t3\n"
        )
        result, _, search, _ = self.run_job(payload, pd.DataFrame())
        nodes = result["spectrum_annotation_df"]
        self.assertEqual(nodes.spectrum_uid.tolist(), ["0", "1", "2"])
        self.assertEqual(nodes.msp_record_index.tolist(), [0, 1, 2])
        self.assertEqual(nodes.has_spectrum.tolist(), [True, False, True])
        edges = result["network_edges_df"]
        pairs = set(zip(edges.loc[edges.edge_type == "spectrum_similarity", "source"],
                        edges.loc[edges.edge_type == "spectrum_similarity", "target"]))
        self.assertEqual(pairs, {("spectrum:0", "spectrum:1"), ("spectrum:1", "spectrum:2")})
        search.assert_not_called()

    def test_multiple_files_count_all_records_in_upload_order(self):
        docs = [
            {"file_name": "first.msp", "sample_class": "A", "source_text": "Name: empty\nNum Peaks: 0\n\n" + record("first")},
            {"file_name": "second.msp", "sample_class": "B", "source_text": record("0")},
        ]
        nodes, spectra, aliases = _prepare_spectra(docs, ion_mode_column="IONMODE")
        self.assertEqual(nodes.node_id.tolist(), ["0", "1", "2"])
        self.assertEqual(nodes.msp_record_index.tolist(), [0, 1, 0])
        self.assertEqual(set(spectra), {"1", "2"})
        self.assertEqual(aliases["0"], "0")
        self.assertEqual(aliases["second.msp::0"], "2")

    def test_metadata_and_progress_escaping(self):
        nodes, _, _ = _prepare_spectra(job()["molecular_network_job"]["documents"], ion_mode_column="IONMODE")
        self.assertEqual(nodes.iloc[0].inchikey, KEY)
        self.assertEqual(nodes.iloc[1].compound_name, "known_neighbor")
        progress = StageProgress()
        _, html = progress.update("input", 1, "<bad>")
        self.assertNotIn("<bad>", html)
        self.assertEqual(html.count('value="100.00"'), 1)


if __name__ == "__main__":
    unittest.main()
