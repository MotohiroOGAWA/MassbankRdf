from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

import pandas as pd

from demo.msp_kg_zip_analysis.plot_metadata_count_histogram import (
    common_bin_edges,
    extract_result_zip,
    plot_histogram,
    spectrum_metadata_counts,
)


class TestMspKgZipHistogram(unittest.TestCase):
    def test_extract_and_count_every_spectrum_with_unique_inchikeys(self) -> None:
        annotations = pd.DataFrame(
            [
                {
                    "spectrum_uid": "sample::1",
                    "source_file": "sample.msp",
                    "sample_class": "Class1",
                },
                {
                    "spectrum_uid": "sample::2",
                    "source_file": "sample.msp",
                    "sample_class": "Class1",
                },
            ]
        )
        candidates = pd.DataFrame(
            [
                {
                    "spectrum_uid": "sample::1",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "kg_metadata_count": 10,
                    "selected_for_kg": True,
                    "combined_rank": 1,
                    "score": 0.9,
                },
                {
                    "spectrum_uid": "sample::1",
                    "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                    "kg_metadata_count": 10,
                    "selected_for_kg": True,
                    "combined_rank": 1,
                    "score": 0.8,
                },
                {
                    "spectrum_uid": "sample::1",
                    "inchikey": "CCCCCCCCCCCCCC-DDDDDDDDDD-E",
                    "kg_metadata_count": 30,
                    "selected_for_kg": True,
                    "combined_rank": 2,
                    "score": 0.7,
                },
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "result.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "massbank_candidates_by_spectrum.csv",
                    candidates.to_csv(index=False),
                )
                archive.writestr(
                    "spectrum_inchikey_annotations.csv",
                    annotations.to_csv(index=False),
                )
            extracted = extract_result_zip(archive_path, root / "extracted")
            top = spectrum_metadata_counts(extracted, aggregation="top")
            summed = spectrum_metadata_counts(extracted, aggregation="sum")

        self.assertEqual(top["kg_metadata_count"].tolist(), [10.0, 0.0])
        self.assertEqual(summed["kg_metadata_count"].tolist(), [40.0, 0.0])

    def test_plot_histogram_writes_png_when_matplotlib_is_available(self) -> None:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib is not installed")
        frame_a = pd.DataFrame({"kg_metadata_count": [0, 1, 2, 3]})
        frame_b = pd.DataFrame({"kg_metadata_count": [1, 2, 4, 8]})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "histogram.png"
            plot_histogram(
                [frame_a, frame_b],
                ["First", "Second"],
                output,
                bin_width=2,
                aggregation="top",
                x_max=4,
            )
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)

    def test_x_max_is_the_last_common_bin_edge(self) -> None:
        edges = common_bin_edges(
            [pd.Series([0, 10, 100]).to_numpy()],
            bin_width=5,
            x_max=20,
        )
        self.assertEqual(edges[-1], 20)
        self.assertEqual(edges.tolist(), [0, 5, 10, 15, 20])


if __name__ == "__main__":
    unittest.main()
