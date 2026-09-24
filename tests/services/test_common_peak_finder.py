import unittest

from massbank_rdf.services.common_peak_annotation.common_peak_finder import (
    PeakRecord,
    find_common_peaks,
)


class CommonPeakIntensityTests(unittest.TestCase):
    def test_filter_uses_each_record_maximum_before_counting(self):
        records = [
            PeakRecord(0, "a", [(10, 100), (20, 5), (30, 4)]),
            PeakRecord(1, "b", [(10, 1000), (20, 49), (30, 50)]),
        ]
        result = find_common_peaks(
            records, mz_tolerance=0.01, minimum_relative_intensity=0.05
        ).set_index("mz_mean")
        self.assertEqual(result["record_count"].to_dict(), {10: 2, 20: 1, 30: 1})
        self.assertEqual(result.loc[20, "total_intensity"], 5)
        self.assertEqual(result.loc[30, "total_intensity"], 50)

    def test_zero_disables_filter_and_empty_records_are_supported(self):
        records = [PeakRecord(0, "a", [(10, 0), (20, 1)]), PeakRecord(1, "b", [])]
        self.assertEqual(len(find_common_peaks(records, mz_tolerance=0.01)), 2)
        self.assertTrue(find_common_peaks(
            [PeakRecord(0, "a", [(10, 0)])],
            mz_tolerance=0.01, minimum_relative_intensity=0.05,
        ).empty)

    def test_invalid_threshold_is_rejected(self):
        for threshold in (-0.1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                find_common_peaks(
                    [], mz_tolerance=0.01, minimum_relative_intensity=threshold
                )
