from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class PeakRecord:
    """One spectrum record used for common peak detection."""

    record_index: int
    name: str
    peaks: list[tuple[float, float]]
    # (mz, intensity)


def find_common_peaks(
    records: list[PeakRecord],
    *,
    mz_tolerance: float,
    minimum_relative_intensity: float = 0.0,
) -> pd.DataFrame:
    """Find common m/z peaks across multiple records.

    Peaks below the per-record relative intensity threshold are removed first.
    A zero threshold disables filtering. Peaks are grouped by m/z tolerance.
    The output is sorted by record_count desc.
    """
    if not 0 <= minimum_relative_intensity <= 1:
        raise ValueError("Minimum relative intensity must be between 0 and 1.")

    peak_rows: list[dict[str, Any]] = []

    for record in records:
        maximum = max((intensity for _, intensity in record.peaks), default=0.0)
        for peak_index, (mz, intensity) in enumerate(record.peaks):
            if minimum_relative_intensity > 0 and (
                maximum <= 0 or intensity / maximum < minimum_relative_intensity
            ):
                continue
            peak_rows.append(
                {
                    "record_index": record.record_index,
                    "record_name": record.name,
                    "peak_index": peak_index,
                    "mz": float(mz),
                    "intensity": float(intensity),
                }
            )

    if not peak_rows:
        return _empty_common_peak_dataframe()

    peak_df = pd.DataFrame(peak_rows)
    peak_df = peak_df.sort_values("mz").reset_index(drop=True)

    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = []

    for row in peak_df.to_dict(orient="records"):
        if not current_group:
            current_group.append(row)
            continue

        current_mz_mean = sum(item["mz"] for item in current_group) / len(current_group)

        if abs(row["mz"] - current_mz_mean) <= mz_tolerance:
            current_group.append(row)
        else:
            groups.append(current_group)
            current_group = [row]

    if current_group:
        groups.append(current_group)

    common_rows: list[dict[str, Any]] = []

    for group_index, group in enumerate(groups):
        group_df = pd.DataFrame(group)

        record_indices = sorted(group_df["record_index"].unique().tolist())
        record_names = sorted(group_df["record_name"].unique().tolist())

        common_rows.append(
            {
                "common_peak_id": group_index,
                "mz_mean": float(group_df["mz"].mean()),
                "mz_min": float(group_df["mz"].min()),
                "mz_max": float(group_df["mz"].max()),
                "peak_count": int(len(group_df)),
                "record_count": int(len(record_indices)),
                "total_intensity": float(group_df["intensity"].sum()),
                "mean_intensity": float(group_df["intensity"].mean()),
                "record_indices": ",".join(map(str, record_indices)),
                "record_names": "; ".join(record_names),
            }
        )

    result_df = pd.DataFrame(common_rows)

    result_df = result_df.sort_values(
        by=[
            "record_count",
            "peak_count",
            "total_intensity",
            "mz_mean",
        ],
        ascending=[
            False,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)

    result_df["common_rank"] = range(1, len(result_df) + 1)

    first_columns = [
        "common_rank",
        "common_peak_id",
        "mz_mean",
        "record_count",
        "peak_count",
        "total_intensity",
        "mean_intensity",
        "mz_min",
        "mz_max",
        "record_indices",
        "record_names",
    ]

    return result_df[first_columns]


def _empty_common_peak_dataframe() -> pd.DataFrame:
    """Create empty common peak DataFrame."""
    return pd.DataFrame(
        columns=[
            "common_rank",
            "common_peak_id",
            "mz_mean",
            "record_count",
            "peak_count",
            "total_intensity",
            "mean_intensity",
            "mz_min",
            "mz_max",
            "record_indices",
            "record_names",
        ]
    )