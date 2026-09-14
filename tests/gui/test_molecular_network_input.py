from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
import zipfile

import pandas as pd

from massbank_rdf.gui.workflows.molecular_network.input_page import (
    _reuse_msp_kg_result,
)


def _write_result_zip(path: Path, spectrum_uid: str = "sample.msp::1") -> None:
    annotations = pd.DataFrame(
        [{
            "spectrum_uid": spectrum_uid,
            "source_file": "sample.msp",
            "sample_class": "OldClass",
            "peak_count": 3,
        }]
    )
    candidates = pd.DataFrame(
        [{
            "spectrum_uid": spectrum_uid,
            "source_file": "sample.msp",
            "sample_class": "OldClass",
            "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
            "selected_for_kg": True,
        }]
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "massbank_candidates_by_spectrum.csv",
            candidates.to_csv(index=False),
        )
        archive.writestr(
            "spectrum_inchikey_annotations.csv",
            annotations.to_csv(index=False),
        )
        archive.writestr("massbank_record_summary.csv", "accession_id\n")
        archive.writestr("class_inchikey_kg_analysis.csv", "sample_class\n")
        archive.writestr(
            "kg_evidence.json",
            json.dumps({"metadata": {}, "features": []}),
        )
        archive.writestr(
            "summary.json",
            json.dumps({"workflow": "msp_kg"}),
        )
        archive.writestr(
            "workflow_config.json",
            json.dumps({"workflow": "msp_kg", "search": {}, "files": []}),
        )


class MolecularNetworkInputTest(unittest.TestCase):
    def test_completed_msp_result_is_reused_and_classes_are_updated(self) -> None:
        session_id = f"test_{uuid.uuid4().hex}"
        job_root = Path(tempfile.gettempdir()) / "massbank_rdf_msp_jobs" / session_id
        try:
            with tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "result.zip"
                _write_result_zip(archive)
                payload = _reuse_msp_kg_result(
                    str(archive),
                    session_id=session_id,
                    expected_spectrum_ids={"sample.msp::1"},
                    sample_classes={"sample.msp": "NewClass"},
                )
            self.assertTrue(payload["kg_precomputed"])
            self.assertTrue(payload["reused_msp_kg_result"])
            self.assertEqual(
                payload["massbank_detail_df"].iloc[0]["sample_class"],
                "NewClass",
            )
            self.assertTrue(Path(payload["output_archive"]).is_file())
        finally:
            shutil.rmtree(job_root, ignore_errors=True)

    def test_mismatched_spectrum_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "result.zip"
            _write_result_zip(archive)
            with self.assertRaisesRegex(ValueError, "does not match"):
                _reuse_msp_kg_result(
                    str(archive),
                    session_id=f"test_{uuid.uuid4().hex}",
                    expected_spectrum_ids={"different.msp::1"},
                    sample_classes={},
                )


if __name__ == "__main__":
    unittest.main()
