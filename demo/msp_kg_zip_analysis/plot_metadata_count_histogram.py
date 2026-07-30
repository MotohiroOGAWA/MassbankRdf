#!/usr/bin/env python3
"""Plot spectrum counts by KG metadata count from one or two MSP/KG ZIPs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

import numpy as np
import pandas as pd


CANDIDATE_FILE = "massbank_candidates_by_spectrum.csv"
ANNOTATION_FILE = "spectrum_inchikey_annotations.csv"
WORKFLOW_CONFIG_FILE = "workflow_config.json"
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


def extract_result_zip(zip_path: Path, output_dir: Path) -> Path:
    """Safely extract a result ZIP and return its result root."""
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError(f"Uncompressed ZIP is larger than 2 GB: {zip_path}")
        root = output_dir.resolve()
        for member in members:
            target = (output_dir / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Unsafe ZIP member path: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)

    candidates = list(output_dir.rglob(CANDIDATE_FILE))
    annotations = list(output_dir.rglob(ANNOTATION_FILE))
    if len(candidates) != 1 or len(annotations) != 1:
        raise ValueError(
            f"{zip_path} must contain exactly one {CANDIDATE_FILE} and "
            f"one {ANNOTATION_FILE}."
        )
    if candidates[0].parent != annotations[0].parent:
        raise ValueError("The candidate and annotation files have different roots.")
    return candidates[0].parent


def _as_boolean(series: pd.Series) -> pd.Series:
    return series.apply(
        lambda value: value is True
        or str(value).strip().lower() in {"true", "1", "yes"}
    )


def minimum_matched_peaks_from_result(result_root: Path) -> int | None:
    """Read the MassBank minimum matched-peak setting saved in the result."""
    config_path = result_root / WORKFLOW_CONFIG_FILE
    if not config_path.is_file():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        value = config.get("search", {}).get("min_matched_peaks")
        threshold = int(value)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return threshold if threshold > 0 else None


def spectrum_metadata_counts(
    result_root: Path,
    *,
    aggregation: str = "top",
    minimum_peak_count: int | None = None,
) -> pd.DataFrame:
    """Return a KG metadata-count value for every searchable input spectrum."""
    annotation_df = pd.read_csv(result_root / ANNOTATION_FILE)
    try:
        candidate_df = pd.read_csv(result_root / CANDIDATE_FILE)
    except pd.errors.EmptyDataError:
        candidate_df = pd.DataFrame()

    required_annotations = {"spectrum_uid", "source_file", "sample_class"}
    if not required_annotations.issubset(annotation_df.columns):
        raise ValueError(
            f"{ANNOTATION_FILE} is missing required columns: "
            f"{sorted(required_annotations - set(annotation_df.columns))}"
        )
    spectrum_columns = ["spectrum_uid", "source_file", "sample_class"]
    if "peak_count" in annotation_df:
        spectrum_columns.append("peak_count")
    spectra = annotation_df[spectrum_columns].drop_duplicates("spectrum_uid")
    threshold = (
        int(minimum_peak_count)
        if minimum_peak_count is not None
        else minimum_matched_peaks_from_result(result_root)
    )
    input_spectrum_count = len(spectra)
    excluded_too_few_peaks = 0
    if threshold is not None and "peak_count" in spectra:
        peak_counts = pd.to_numeric(spectra["peak_count"], errors="coerce")
        eligible = peak_counts >= threshold
        excluded_too_few_peaks = int((~eligible).sum())
        spectra = spectra.loc[eligible].copy()
        spectra["peak_count"] = peak_counts.loc[eligible].astype(int)

    def attach_filter_metadata(frame: pd.DataFrame) -> pd.DataFrame:
        frame.attrs.update(
            {
                "input_spectrum_count": input_spectrum_count,
                "minimum_peak_count": threshold,
                "excluded_too_few_peaks": excluded_too_few_peaks,
                "peak_filter_applied": (
                    threshold is not None and "peak_count" in annotation_df
                ),
            }
        )
        return frame

    required_candidates = {"spectrum_uid", "inchikey", "kg_metadata_count"}
    if candidate_df.empty or not required_candidates.issubset(candidate_df.columns):
        spectra["kg_metadata_count"] = 0.0
        return attach_filter_metadata(spectra)

    selected = candidate_df.copy()
    if "selected_for_kg" in selected:
        selected = selected[_as_boolean(selected["selected_for_kg"])]
    selected = selected.dropna(subset=["spectrum_uid", "inchikey"])
    selected["kg_metadata_count"] = (
        pd.to_numeric(selected["kg_metadata_count"], errors="coerce")
        .fillna(0)
        .clip(lower=0)
    )

    sort_columns: list[str] = []
    ascending: list[bool] = []
    for column, is_ascending in (
        ("combined_rank", True),
        ("combined_rank_sum", True),
        ("massbank_similarity_rank", True),
        ("score", False),
        ("candidate_rank", True),
    ):
        if column in selected:
            sort_columns.append(column)
            ascending.append(is_ascending)
    if sort_columns:
        selected = selected.sort_values(
            sort_columns,
            ascending=ascending,
            na_position="last",
            kind="stable",
        )

    # Multiple MassBank records may share one InChIKey. They must contribute once.
    selected = selected.drop_duplicates(["spectrum_uid", "inchikey"], keep="first")
    if aggregation == "top":
        values = selected.drop_duplicates("spectrum_uid", keep="first").set_index(
            "spectrum_uid"
        )["kg_metadata_count"]
    else:
        values = selected.groupby("spectrum_uid")["kg_metadata_count"].agg(
            aggregation
        )
    spectra["kg_metadata_count"] = (
        spectra["spectrum_uid"].map(values).fillna(0).astype(float)
    )
    return attach_filter_metadata(spectra)


def common_bin_edges(
    values: list[np.ndarray],
    bin_width: float,
    x_max: float | None = None,
) -> np.ndarray:
    """Build identical histogram bins for one or two datasets."""
    combined = np.concatenate(values) if values else np.array([0.0])
    finite = combined[np.isfinite(combined)]
    if finite.size == 0:
        finite = np.array([0.0])
    minimum = min(0.0, float(finite.min()))
    maximum = float(x_max) if x_max is not None else float(finite.max())
    if maximum <= minimum:
        maximum = minimum + bin_width
    edges = np.arange(
        minimum,
        maximum + bin_width,
        bin_width,
        dtype=float,
    )
    if x_max is not None:
        edges = edges[edges < maximum]
        edges = np.append(edges, maximum)
    elif edges[-1] < maximum:
        edges = np.append(edges, edges[-1] + bin_width)
    return edges


def plot_histogram(
    datasets: list[pd.DataFrame],
    labels: list[str],
    output_path: Path,
    *,
    bin_width: float,
    aggregation: str,
    x_max: float | None = None,
) -> None:
    """Plot overlapping histograms and dashed mean lines."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required. Install it with: pip install matplotlib"
        ) from exc

    colors = ["blue", "red"]
    arrays = [
        frame["kg_metadata_count"].to_numpy(dtype=float)
        for frame in datasets
    ]
    edges = common_bin_edges(arrays, bin_width, x_max=x_max)
    figure, axis = plt.subplots(figsize=(11, 7))

    for index, (values, label) in enumerate(zip(arrays, labels)):
        color = colors[index]
        mean = float(np.mean(values)) if len(values) else 0.0
        plot_values = (
            np.minimum(values, float(x_max))
            if x_max is not None
            else values
        )
        overflow_count = (
            int(np.sum(values >= float(x_max)))
            if x_max is not None
            else 0
        )
        histogram_label = f"{label} (n={len(values):,})"
        if x_max is not None:
            histogram_label += f", ≥{x_max:g}: {overflow_count:,}"
        axis.hist(
            plot_values,
            bins=edges,
            color=color,
            alpha=0.42,
            edgecolor=color,
            linewidth=0.7,
            label=histogram_label,
        )
        mean_position = min(mean, float(x_max)) if x_max is not None else mean
        axis.axvline(
            mean_position,
            color=color,
            linestyle="--",
            linewidth=2,
            label=(
                f"{label} mean = {mean:.2f}"
                + (
                    " (line clipped at x-max)"
                    if x_max is not None and mean > x_max
                    else ""
                )
            ),
        )

    axis.set_xlabel(
        f"KG metadata count per spectrum ({aggregation} selected InChIKey)"
    )
    axis.set_ylabel("Number of spectra")
    axis.set_title("Distribution of KG metadata counts across spectra")
    axis.grid(axis="y", alpha=0.2)
    if x_max is not None:
        axis.set_xlim(edges[0], float(x_max))
        ticks = list(axis.get_xticks())
        ticks = [
            tick for tick in ticks
            if edges[0] <= tick < float(x_max)
        ] + [float(x_max)]
        axis.set_xticks(ticks)
        axis.set_xticklabels(
            [
                f"≥{x_max:g}" if tick == float(x_max) else f"{tick:g}"
                for tick in ticks
            ]
        )
    axis.legend()
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=200)
    plt.close(figure)


def write_tables(
    datasets: list[pd.DataFrame],
    labels: list[str],
    output_dir: Path,
    x_max: float | None = None,
) -> tuple[Path, Path]:
    """Write plot source values and summary statistics."""
    detail_parts = []
    summaries = []
    for frame, label in zip(datasets, labels):
        detail = frame.copy()
        detail.insert(0, "dataset", label)
        detail_parts.append(detail)
        values = detail["kg_metadata_count"]
        summaries.append(
            {
                "dataset": label,
                "input_spectrum_count": frame.attrs.get(
                    "input_spectrum_count", len(values)
                ),
                "spectrum_count": len(values),
                "minimum_peak_count": frame.attrs.get("minimum_peak_count"),
                "excluded_too_few_peaks": frame.attrs.get(
                    "excluded_too_few_peaks", 0
                ),
                "peak_filter_applied": frame.attrs.get(
                    "peak_filter_applied", False
                ),
                "mean": values.mean() if len(values) else 0.0,
                "median": values.median() if len(values) else 0.0,
                "std": values.std(ddof=1) if len(values) > 1 else 0.0,
                "minimum": values.min() if len(values) else 0.0,
                "maximum": values.max() if len(values) else 0.0,
                "zero_metadata_spectra": int((values == 0).sum()),
                "spectra_at_or_above_x_max": (
                    int((values >= x_max).sum())
                    if x_max is not None
                    else None
                ),
            }
        )
    detail_path = output_dir / "metadata_count_by_spectrum.tsv"
    summary_path = output_dir / "metadata_count_summary.tsv"
    pd.concat(detail_parts, ignore_index=True).to_csv(
        detail_path, sep="\t", index=False
    )
    pd.DataFrame(summaries).to_csv(summary_path, sep="\t", index=False)
    return detail_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract one or two MSP/KG result ZIPs and plot the distribution "
            "of spectrum-level KG metadata counts."
        )
    )
    parser.add_argument(
        "result_zips",
        nargs="+",
        type=Path,
        help="One or two msp_kg_result.zip files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("msp_kg_metadata_histogram"),
        help="Output directory.",
    )
    parser.add_argument(
        "--output-name",
        default="metadata_count_histogram.png",
        help="Histogram PNG filename.",
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        help="Dataset label; provide once per ZIP.",
    )
    parser.add_argument(
        "--bin-width",
        type=float,
        default=10.0,
        help="Histogram bin width in KG metadata-count units.",
    )
    parser.add_argument(
        "--x-max",
        type=float,
        default=None,
        help=(
            "Maximum displayed x value. Counts greater than or equal to this "
            "value are grouped into the final bin."
        ),
    )
    parser.add_argument(
        "--aggregation",
        choices=["top", "max", "mean", "sum"],
        default="top",
        help="How multiple selected unique InChIKeys represent one spectrum.",
    )
    parser.add_argument(
        "--min-peak-count",
        type=int,
        default=None,
        help=(
            "Override the minimum input-spectrum peak count. By default, "
            "min_matched_peaks is read from workflow_config.json."
        ),
    )
    args = parser.parse_args()
    if not 1 <= len(args.result_zips) <= 2:
        parser.error("Specify one or two result ZIP files.")
    if args.bin_width <= 0:
        parser.error("--bin-width must be greater than 0.")
    if args.x_max is not None and args.x_max <= 0:
        parser.error("--x-max must be greater than 0.")
    if args.min_peak_count is not None and args.min_peak_count < 1:
        parser.error("--min-peak-count must be at least 1.")
    if args.labels and len(args.labels) != len(args.result_zips):
        parser.error("Provide --label exactly once per ZIP, or omit all labels.")
    return args


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = args.labels or [path.stem for path in args.result_zips]
    datasets: list[pd.DataFrame] = []

    with tempfile.TemporaryDirectory(prefix="msp_kg_zip_analysis_") as temporary:
        temporary_root = Path(temporary)
        for index, zip_path in enumerate(args.result_zips, start=1):
            zip_path = zip_path.resolve()
            if not zip_path.is_file():
                raise FileNotFoundError(zip_path)
            result_root = extract_result_zip(
                zip_path,
                temporary_root / f"result_{index}",
            )
            datasets.append(
                spectrum_metadata_counts(
                    result_root,
                    aggregation=args.aggregation,
                    minimum_peak_count=args.min_peak_count,
                )
            )

    histogram_path = output_dir / args.output_name
    plot_histogram(
        datasets,
        labels,
        histogram_path,
        bin_width=args.bin_width,
        aggregation=args.aggregation,
        x_max=args.x_max,
    )
    detail_path, summary_path = write_tables(
        datasets,
        labels,
        output_dir,
        x_max=args.x_max,
    )
    print(f"Histogram: {histogram_path}")
    print(f"Spectrum values: {detail_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
