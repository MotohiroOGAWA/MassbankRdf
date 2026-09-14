from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile

import pandas as pd


MSP_TEMPLATE = """Name: {name}
IONMODE: POSITIVE
Num Peaks: 6
100.000 100
150.000 80
200.000 60
250.000 50
300.000 40
350.000 30
"""


class MolecularNetworkCliTest(unittest.TestCase):
    def test_cli_generates_cytoscape_tables_without_gui(self) -> None:
        app_root = Path(__file__).resolve().parents[2]
        script = (
            app_root
            / "demo"
            / "molecular_network_cli"
            / "build_cytoscape_network.py"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.msp"
            second = root / "second.msp"
            output = root / "output"
            first.write_text(
                MSP_TEMPLATE.format(name="First"), encoding="utf-8"
            )
            second.write_text(
                MSP_TEMPLATE.format(name="Second"), encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(first),
                    str(second),
                    "--output-dir",
                    str(output),
                    "--score-thresholds",
                    "p95",
                    "--match-peak-counts",
                    "6",
                    "--top-k-values",
                    "10",
                    "--resolutions",
                    "1.0",
                ],
                cwd=app_root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            nodes = pd.read_csv(output / "node.tsv", sep="\t")
            edges = pd.read_csv(output / "edge.tsv", sep="\t")
            statistics = pd.read_csv(
                output / "network_condition_statistics.csv"
            )
        self.assertEqual(set(nodes["node_type"]), {"spectrum"})
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges.iloc[0]["edge_type"], "spectrum_similarity")
        self.assertEqual(int(edges.iloc[0]["match_peak_count"]), 6)
        self.assertEqual(len(statistics), 1)

    def test_two_stage_cli_adds_saved_massbank_and_kg_metadata(self) -> None:
        app_root = Path(__file__).resolve().parents[2]
        build_script = (
            app_root / "demo" / "molecular_network_cli" / "build_network.py"
        )
        annotate_script = (
            app_root / "demo" / "molecular_network_cli" / "annotate_network.py"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.msp"
            second = root / "second.msp"
            network = root / "network"
            annotated = root / "annotated"
            archive = root / "msp_kg_result.zip"
            first.write_text(MSP_TEMPLATE.format(name="First"), encoding="utf-8")
            second.write_text(MSP_TEMPLATE.format(name="Second"), encoding="utf-8")
            built = subprocess.run(
                [
                    sys.executable, str(build_script), str(first), str(second),
                    "--output-dir", str(network),
                    "--score-thresholds", "p95",
                    "--match-peak-counts", "6",
                    "--top-k-values", "10",
                    "--resolutions", "1.0",
                ],
                cwd=app_root, text=True, capture_output=True, check=False,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertIn("[1/5]", built.stderr)
            self.assertIn("[5/5] All output files written.", built.stderr)
            annotations = pd.DataFrame(
                [
                    {
                        "spectrum_uid": "first.msp::1",
                        "source_file": "first.msp",
                        "sample_class": "Class1",
                    },
                    {
                        "spectrum_uid": "second.msp::1",
                        "source_file": "second.msp",
                        "sample_class": "Class2",
                    },
                ]
            )
            candidates = pd.DataFrame(
                [{
                    "spectrum_uid": "first.msp::1",
                    "source_file": "first.msp",
                    "sample_class": "Class1",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "selected_for_kg": True,
                    "score": 0.9,
                    "accession_id": "TEST0001",
                }]
            )
            evidence = {
                "metadata": {},
                "features": [{
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "entities": {
                        "diseases": {
                            "hmdb": [{"id": "D1", "label": "Test disease"}]
                        }
                    },
                }],
            }
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr(
                    "spectrum_inchikey_annotations.csv",
                    annotations.to_csv(index=False),
                )
                output.writestr(
                    "massbank_candidates_by_spectrum.csv",
                    candidates.to_csv(index=False),
                )
                output.writestr("kg_evidence.json", json.dumps(evidence))
            result = subprocess.run(
                [
                    sys.executable, str(annotate_script),
                    "--network-dir", str(network),
                    "--msp-kg-result", str(archive),
                    "--output-dir", str(annotated),
                ],
                cwd=app_root, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("[1/6]", result.stderr)
            self.assertIn("[6/6] All output files written.", result.stderr)
            nodes = pd.read_csv(annotated / "node.tsv", sep="\t")
            edges = pd.read_csv(annotated / "edge.tsv", sep="\t")
        self.assertEqual(
            set(nodes["node_type"]), {"spectrum", "inchikey", "diseases"}
        )
        self.assertIn("massbank_annotation", set(edges["edge_type"]))
        self.assertIn("kg_metadata", set(edges["edge_type"]))


if __name__ == "__main__":
    unittest.main()
