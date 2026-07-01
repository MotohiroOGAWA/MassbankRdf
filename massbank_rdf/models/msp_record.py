from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class MSPRecord:
    """One MSP record with pandas metadata and numpy peak data."""

    metadata: pd.DataFrame
    peaks: np.ndarray
    raw_text: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, pd.DataFrame):
            self.metadata = pd.DataFrame([dict(self.metadata)])

        if self.metadata.shape[0] != 1:
            raise ValueError("metadata must be a one-row pandas DataFrame.")

        peaks = np.asarray(self.peaks, dtype=float)
        if peaks.ndim != 2 or peaks.shape[1] != 2:
            raise ValueError("peaks must be a 2D numpy array with shape [N, 2].")
        self.peaks = peaks

    @classmethod
    def from_msp_file(
        cls,
        path: str | Path,
    ) -> "MSPRecord":
        input_path = Path(path)
        text = input_path.read_text(encoding="utf-8", errors="replace")
        return cls.from_msp_text(text)

    @classmethod
    def from_msp_text(
        cls,
        text: str,
    ) -> "MSPRecord":
        if not text or not text.strip():
            raise ValueError("MSP text must not be empty.")

        metadata: dict[str, Any] = {}
        peak_rows: list[list[float]] = []
        in_peak_block = False

        for raw_line in text.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            if in_peak_block:
                peak = _parse_peak_line(line)
                if peak is not None:
                    peak_rows.append(peak)
                continue

            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                metadata[key] = value.strip()

                if _normalize_metadata_key(key) == "numpeaks":
                    in_peak_block = True
                continue

            peak = _parse_peak_line(line)
            if peak is not None:
                peak_rows.append(peak)

        if not peak_rows:
            raise ValueError("No valid m/z intensity peak rows were found.")

        metadata_df = pd.DataFrame([metadata])
        peaks = np.asarray(peak_rows, dtype=float)
        return cls(metadata=metadata_df, peaks=peaks, raw_text=text)

    @classmethod
    def load(
        cls,
        directory: str | Path,
    ) -> "MSPRecord":
        base_dir = Path(directory)
        record_path = base_dir / "record.pkl"

        if record_path.exists():
            record = pd.read_pickle(record_path)
            if not isinstance(record, cls):
                raise TypeError("record.pkl does not contain an MSPRecord.")
            return record

        metadata_path = base_dir / "metadata.pkl"
        peaks_path = base_dir / "peaks.npy"
        raw_text_path = base_dir / "raw.msp"

        metadata = pd.read_pickle(metadata_path)
        peaks = np.load(peaks_path)
        raw_text = ""

        if raw_text_path.exists():
            raw_text = raw_text_path.read_text(encoding="utf-8", errors="replace")

        return cls(metadata=metadata, peaks=peaks, raw_text=raw_text)

    def save(
        self,
        directory: str | Path,
    ) -> dict[str, str | int]:
        base_dir = Path(directory)
        base_dir.mkdir(parents=True, exist_ok=True)

        record_pickle_path = base_dir / "record.pkl"
        metadata_pickle_path = base_dir / "metadata.pkl"
        peaks_npy_path = base_dir / "peaks.npy"
        raw_text_path = base_dir / "raw.msp"
        manifest_path = base_dir / "manifest.json"

        for stale_path in [
            base_dir / "metadata.csv",
            base_dir / "peaks.csv",
        ]:
            stale_path.unlink(missing_ok=True)

        pd.to_pickle(self, record_pickle_path)
        self.metadata.to_pickle(metadata_pickle_path)
        np.save(peaks_npy_path, self.peaks)
        raw_text_path.write_text(self.raw_text, encoding="utf-8")

        manifest: dict[str, str | int] = {
            "record_pickle": str(record_pickle_path),
            "metadata_pickle": str(metadata_pickle_path),
            "peaks_npy": str(peaks_npy_path),
            "raw_text": str(raw_text_path),
            "peak_count": int(self.peaks.shape[0]),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return manifest

    @property
    def mz_list(self) -> np.ndarray:
        return self.peaks[:, 0]

    @property
    def intensity_list(self) -> np.ndarray:
        return self.peaks[:, 1]

    @property
    def peaks_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "peak_index": np.arange(self.peaks.shape[0], dtype=int),
                "mz": self.mz_list,
                "intensity": self.intensity_list,
            }
        )

    def get_metadata_value(
        self,
        key: str,
    ) -> str | None:
        normalized_key = _normalize_metadata_key(key)

        for column in self.metadata.columns:
            if _normalize_metadata_key(column) == normalized_key:
                value = self.metadata.iloc[0][column]
                if pd.isna(value) or value == "":
                    return None
                return str(value)

        return None


def _parse_peak_line(
    line: str,
) -> list[float] | None:
    items = line.replace(",", " ").split()

    if len(items) < 2:
        return None

    try:
        mz = float(items[0])
        intensity = float(items[1])
    except ValueError:
        return None

    if not np.isfinite(mz) or not np.isfinite(intensity):
        return None

    return [mz, intensity]


def _normalize_metadata_key(
    key: Any,
) -> str:
    return str(key).lower().replace("_", "").replace(" ", "")
