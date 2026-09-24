from __future__ import annotations

import math
from .common_peak_annotator import normalize_optional_positive_int


def build_common_peak_settings(
    mz_tolerance, minimum_relative_intensity, common_peak_n,
    max_massbank_inchikey, massbank_top_n, min_matched_peaks,
    minimum_similarity, ion_mode,
) -> dict:
    """Normalize and validate the shared annotation settings."""
    result = {}
    for name, value, maximum in (
        ("mz_tolerance", mz_tolerance, None),
        ("minimum_relative_intensity", minimum_relative_intensity, 1),
        ("minimum_similarity", minimum_similarity, 1),
    ):
        number = float(value)
        if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
            raise ValueError(f"Invalid {name}: {value}")
        result[name] = number
    for name, value in (("common_peak_n", common_peak_n), ("massbank_top_n", massbank_top_n), ("min_matched_peaks", min_matched_peaks)):
        number = float(value)
        if not math.isfinite(number) or number < 1 or not number.is_integer():
            raise ValueError(f"{name} must be a positive integer.")
        result[name] = int(number)
    result["max_massbank_inchikey"] = normalize_optional_positive_int(max_massbank_inchikey)
    mode = str(ion_mode or "").strip().upper()
    result["ion_mode"] = None if mode in ("", "-") else mode
    return result
