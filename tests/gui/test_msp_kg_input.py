from __future__ import annotations

from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

import pandas as pd

from massbank_rdf.gui.workflows.msp_kg.input_page import (
    _merge_kg_evidence,
    _merge_kg_queries,
    _normalize_ion_mode,
    assign_default_sample_classes,
    inspect_uploaded_msp,
    inspect_uploaded_msps,
    load_result_payload_from_zip,
    load_llm_settings_file,
    load_workflow_config_from_zip,
    parse_msp_records,
    read_msp_input,
    write_llm_settings_file,
)
from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.msp_kg.processor import build_batch_processor


MSP_TEXT = """Name: Example
Ion_mode: POSITIVE
PrecursorMZ: 123.4
Num Peaks: 2
50.0 10
75.0 20
"""


class TestMspKgInput(unittest.TestCase):
    def test_read_msp_input_from_text(self) -> None:
        record = read_msp_input(None, MSP_TEXT)
        self.assertEqual(record.get_metadata_value("Name"), "Example")
        self.assertEqual(record.peaks.shape, (2, 2))

    def test_uploaded_file_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.msp"
            path.write_text(
                MSP_TEXT.replace("Example", "Uploaded"), encoding="utf-8"
            )
            record = read_msp_input(str(path), MSP_TEXT)
        self.assertEqual(record.get_metadata_value("Name"), "Uploaded")

    def test_non_msp_upload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.txt"
            path.write_text(MSP_TEXT, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"\.msp"):
                read_msp_input(str(path), "")

    def test_normalize_ion_mode(self) -> None:
        for value, expected in [
            ("positive", "POSITIVE"),
            ("NEG", "NEGATIVE"),
            ("+", "POSITIVE"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(_normalize_ion_mode(value), expected)

    def test_parse_multiple_msp_records(self) -> None:
        second = MSP_TEXT.replace("Example", "Second").replace(
            "PrecursorMZ: 123.4", "PrecursorMZ: 200.0"
        )
        records = parse_msp_records(f"{MSP_TEXT}\n{second}")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1].get_metadata_value("Name"), "Second")

    def test_uploaded_status_reports_record_and_peak_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.msp"
            path.write_text(f"{MSP_TEXT}\n{MSP_TEXT}", encoding="utf-8")
            status = inspect_uploaded_msp(str(path))
        self.assertEqual(
            status,
            "MSP loaded: 2 records; 2 readable spectra; 4 total peaks.",
        )

    def test_multiple_uploads_start_with_blank_sample_classes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for file_name in ("first.msp", "second.msp"):
                path = Path(directory) / file_name
                path.write_text(MSP_TEXT, encoding="utf-8")
                paths.append(str(path))
            _, classes = inspect_uploaded_msps(paths)

        self.assertEqual(classes["sample_class"].tolist(), ["", ""])

    def test_blank_sample_classes_use_file_order_labels(self) -> None:
        result = assign_default_sample_classes(
            pd.Series(["", "Treatment", None])
        )
        self.assertEqual(
            result.tolist(),
            ["Class1", "Treatment", "Class3"],
        )

    def test_upload_inspection_reports_empty_record_without_failing(self) -> None:
        empty_record = "Name: Empty\nNum Peaks: 0\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.msp"
            path.write_text(f"{MSP_TEXT}\n{empty_record}", encoding="utf-8")
            with mock.patch(
                "massbank_rdf.gui.workflows.msp_kg.input_page.gr.Warning"
            ) as warning:
                status = inspect_uploaded_msp(str(path))
        self.assertIn("2 records; 1 readable spectra", status)
        self.assertNotIn("Skipped", status)
        warning.assert_called_once_with(
            "Skipped 1 records without readable peaks."
        )

    def test_record_boundary_does_not_depend_on_num_peaks_value(self) -> None:
        first = MSP_TEXT.replace("Num Peaks: 2", "Num Peaks: 999")
        records = parse_msp_records(f"{first}\n{MSP_TEXT}")
        self.assertEqual(len(records), 2)

    def test_merge_chunked_kg_results(self) -> None:
        merged = _merge_kg_evidence(
            [
                {
                    "metadata": {"source": "test"},
                    "features": [{"inchikey": "AAA"}],
                },
                {
                    "metadata": {"source": "test"},
                    "features": [
                        {"inchikey": "AAA"},
                        {"inchikey": "BBB"},
                    ],
                },
            ]
        )
        self.assertEqual(
            [feature["inchikey"] for feature in merged["features"]],
            ["AAA", "BBB"],
        )
        self.assertEqual(merged["metadata"]["feature_count"], 2)
        self.assertEqual(merged["metadata"]["kg_chunk_count"], 2)

    def test_merge_chunked_queries_adds_chunk_labels(self) -> None:
        queries = _merge_kg_queries(
            [
                {"pubchem_compound": "SELECT first"},
                {"pubchem_compound": "SELECT second"},
            ]
        )
        self.assertIn("# Chunk 1\nSELECT first", queries["pubchem_compound"])
        self.assertIn("# Chunk 2\nSELECT second", queries["pubchem_compound"])

    def test_result_zip_restores_settings_and_matching_classes(self) -> None:
        config = {
            "schema_version": 1,
            "files": [
                {"file_name": "a.msp", "sample_class": "PR"},
                {"file_name": "missing.msp", "sample_class": "WT"},
            ],
            "search": {
                "top_n": 5,
                "mz_tolerance": 0.02,
                "min_matched_peaks": 3,
                "minimum_similarity": 0.6,
                "use_precursor_mz": False,
                "precursor_mz_column": "PRECURSOR_M/Z",
                "precursor_tolerance": 0.5,
                "use_ion_mode": True,
                "ion_mode_column": "POLARITY",
                "max_massbank_inchikey": 2,
                "use_short_inchikey": True,
            },
        }
        current = pd.DataFrame(
            [
                {"file_name": "a.msp", "sample_class": ""},
                {"file_name": "b.msp", "sample_class": "Control"},
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "result.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "workflow_config.json",
                    json.dumps(config),
                )
            loaded = load_workflow_config_from_zip(
                str(archive_path),
                current,
            )
        self.assertIn("1 matching file classes updated", loaded[0])
        self.assertEqual(loaded[1].loc[0, "sample_class"], "PR")
        self.assertEqual(loaded[1].loc[1, "sample_class"], "Control")
        self.assertEqual(loaded[2:], (
            5, 0.02, 3, 0.6, False, "PRECURSOR_M/Z", 0.5,
            True, "POLARITY", 2, True,
        ))

    def test_completed_result_zip_restores_result_payload(self) -> None:
        config = {
            "schema_version": 1,
            "workflow": "msp_kg",
            "files": [{"file_name": "a.msp", "sample_class": "PR"}],
            "search": {},
        }
        candidate = pd.DataFrame(
            [
                {
                    "spectrum_uid": "a.msp::1",
                    "source_file": "a.msp",
                    "sample_class": "PR",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "accession_id": "MSBNK-TEST-0001",
                    "score": 0.9,
                }
            ]
        )
        annotation = pd.DataFrame(
            [
                {
                    "spectrum_uid": "a.msp::1",
                    "source_file": "a.msp",
                    "sample_class": "PR",
                }
            ]
        )
        kg_evidence = {
            "metadata": {"feature_count": 1},
            "features": [
                {
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "entities": {},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "result.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("workflow_config.json", json.dumps(config))
                archive.writestr(
                    "summary.json",
                    json.dumps({"workflow": "msp_kg", "record_count": 1}),
                )
                archive.writestr("kg_evidence.json", json.dumps(kg_evidence))
                archive.writestr(
                    "massbank_candidates_by_spectrum.csv",
                    candidate.to_csv(index=False),
                )
                archive.writestr(
                    "spectrum_inchikey_annotations.csv",
                    annotation.to_csv(index=False),
                )
                archive.writestr(
                    "massbank_record_summary.csv",
                    candidate.to_csv(index=False),
                )
                archive.writestr(
                    "class_inchikey_kg_analysis.csv",
                    pd.DataFrame().to_csv(index=False),
                )
                archive.writestr("sparql/hmdb.sparql", "SELECT * WHERE {}")

            payload = load_result_payload_from_zip(str(archive_path))

        self.assertTrue(payload["kg_precomputed"])
        self.assertEqual(len(payload["massbank_detail_df"]), 1)
        self.assertEqual(payload["kg_inchikeys"], [
            "AAAAAAAAAAAAAA-BBBBBBBBBB-C"
        ])
        self.assertEqual(payload["kg_queries"]["hmdb"], "SELECT * WHERE {}")
        self.assertTrue(payload["summary"]["imported_result_zip"])

    def test_incomplete_result_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "result.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "workflow_config.json",
                    json.dumps({"workflow": "msp_kg"}),
                )
            with self.assertRaisesRegex(ValueError, "incomplete"):
                load_result_payload_from_zip(str(archive_path))

    def test_imported_result_skips_massbank_and_kg_processing(self) -> None:
        session_store = TemporarySessionStore()
        session_store.set(
            "imported-session",
            {
                "kg_precomputed": True,
                "output_directory": "Imported from result ZIP",
            },
        )
        kg_service = mock.Mock()
        processor = build_batch_processor(session_store, kg_service)
        request = SimpleNamespace(
            request=SimpleNamespace(
                cookies={"msp_kg_session_id": "imported-session"},
                query_params={},
            )
        )

        updates = list(processor(request))
        message = updates[-1][0]

        self.assertIn("already completed", message)
        self.assertIn("100.0%", updates[-1][1])
        kg_service.assert_not_called()

    def test_llm_settings_round_trip_includes_api_key(self) -> None:
        path = write_llm_settings_file(
            enabled=True,
            output_language="English",
            endpoint="https://example.openai.azure.com/",
            deployment="chat-model",
            api_version="2024-10-21",
            api_key="saved-secret",
            user_context="Test samples",
        )
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        loaded = load_llm_settings_file(path, "current-secret")

        self.assertEqual(saved["api_key"], "saved-secret")
        self.assertEqual(loaded[1], True)
        self.assertEqual(loaded[2], "English")
        self.assertEqual(loaded[3], "https://example.openai.azure.com/")
        self.assertEqual(loaded[6], "saved-secret")
        self.assertEqual(loaded[7], "Test samples")

if __name__ == "__main__":
    unittest.main()
