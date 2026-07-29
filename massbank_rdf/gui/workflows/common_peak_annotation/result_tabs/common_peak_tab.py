from __future__ import annotations

from typing import Any

import gradio as gr
import pandas as pd

from ....session_store import TemporarySessionStore
from .....services.common_peak_annotation.common_peak_finder import (
    PeakRecord,
    find_common_peaks,
)


COMMON_PEAK_TAB_ID = "common_peaks"


def make_empty_common_peak_dataframe() -> pd.DataFrame:
    """Create empty common peak DataFrame for display."""
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
        ]
    )


def create_common_peak_tab() -> gr.Dataframe:
    """Create common peak tab components."""
    return gr.Dataframe(
        label="Common peaks",
        value=make_empty_common_peak_dataframe(),
        interactive=False,
        wrap=True,
    )


def _make_common_peak_display_dataframe(
    common_peaks_df: pd.DataFrame,
) -> pd.DataFrame:
    """Create common peak DataFrame for display.

    Internal columns such as record_indices and record_names are kept in
    payload["common_peaks_df"], but hidden from the Gradio table.
    """
    if common_peaks_df is None or common_peaks_df.empty:
        return make_empty_common_peak_dataframe()

    display_df = common_peaks_df.copy()

    display_df = display_df.drop(
        columns=[
            "record_indices",
            "record_names",
        ],
        errors="ignore",
    )

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
    ]

    ordered_columns: list[str] = []

    for column in first_columns:
        if column in display_df.columns:
            ordered_columns.append(column)

    for column in display_df.columns:
        if column not in ordered_columns:
            ordered_columns.append(column)

    return display_df[ordered_columns]


def _parse_peak_text_to_peak_records(
    peak_text: str,
) -> list[PeakRecord]:
    """Parse peak text to PeakRecord list.

    A blank line separates records.
    Each non-empty line must contain:
        mz intensity
    """
    records: list[PeakRecord] = []

    if not peak_text or not peak_text.strip():
        return records

    record_blocks = [
        block.strip()
        for block in peak_text.strip().split("\n\n")
        if block.strip()
    ]

    for record_index, block in enumerate(record_blocks):
        peaks: list[tuple[float, float]] = []

        for line in block.splitlines():
            stripped = line.strip()

            if not stripped:
                continue

            items = stripped.replace(",", " ").split()

            if len(items) < 2:
                continue

            try:
                mz = float(items[0])
                intensity = float(items[1])
            except ValueError:
                continue

            peaks.append((mz, intensity))

        if peaks:
            records.append(
                PeakRecord(
                    record_index=record_index,
                    name=f"record_{record_index}",
                    peaks=peaks,
                )
            )

    return records


def _format_common_peak_status(
    *,
    payload: dict[str, Any],
    records_count: int,
    common_peaks_df: pd.DataFrame,
) -> str:
    """Format common peak status text."""
    summary = payload.get("summary", {})

    if not isinstance(summary, dict):
        summary = {}

    return (
        "Common peak detection finished.\n\n"
        f"Input records: {records_count}\n"
        f"Common peaks: {len(common_peaks_df)}\n\n"
        "[Common peak annotation settings]\n"
        f"m/z tolerance: {summary.get('mz_tolerance', '-')}\n"
        f"Common peak N: {summary.get('common_peak_n', '-')}\n"
        f"Max MassBank InChIKey: {summary.get('max_massbank_inchikey', '-')}\n"
        f"MassBank top N: {summary.get('massbank_top_n', '-')}\n"
        f"Minimum cosine similarity: {summary.get('minimum_similarity', '-')}\n"
        f"Min matched peaks: {summary.get('min_matched_peaks', '-')}\n"
        f"Ion mode: {summary.get('ion_mode', '-')}"
    )


def build_common_peak_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "common_peak_session_id",
):
    """Build callback for detecting common peaks."""

    def _load_common_peaks(
        request: gr.Request,
    ) -> tuple[
        str,
        pd.DataFrame,
        gr.update,
    ]:
        session_id = request.request.cookies.get(session_cookie_name)

        if not session_id:
            return (
                "Session ID was not found. Please go back and run again.",
                make_empty_common_peak_dataframe(),
                gr.update(selected=COMMON_PEAK_TAB_ID),
            )

        payload = session_store.get(session_id)

        if payload is None or not isinstance(payload, dict):
            return (
                "No input was found. Please go back and run again.",
                make_empty_common_peak_dataframe(),
                gr.update(selected=COMMON_PEAK_TAB_ID),
            )

        input_data = payload.get("input", {})
        summary = payload.get("summary", {})

        if not isinstance(input_data, dict):
            input_data = {}

        if not isinstance(summary, dict):
            summary = {}

        peak_text = str(
            input_data.get("peak_text", input_data.get("msp_text", ""))
        )

        try:
            mz_tolerance = float(summary.get("mz_tolerance", 0.01))
        except (TypeError, ValueError) as exc:
            return (
                f"Invalid m/z tolerance: {exc}",
                make_empty_common_peak_dataframe(),
                gr.update(selected=COMMON_PEAK_TAB_ID),
            )

        records = _parse_peak_text_to_peak_records(peak_text)

        if not records:
            return (
                "No valid peak records were found. Please go back and check input text.",
                make_empty_common_peak_dataframe(),
                gr.update(selected=COMMON_PEAK_TAB_ID),
            )

        common_peaks_df = find_common_peaks(
            records,
            mz_tolerance=mz_tolerance,
        )

        # Keep the full DataFrame internally.
        # record_indices and record_names are needed for internal use,
        # but they are not shown in the display table.
        payload["records_count"] = len(records)
        payload["common_peaks_df"] = common_peaks_df

        session_store.set(
            session_id=session_id,
            value=payload,
        )

        common_peak_display_df = _make_common_peak_display_dataframe(
            common_peaks_df
        )

        return (
            _format_common_peak_status(
                payload=payload,
                records_count=len(records),
                common_peaks_df=common_peaks_df,
            ),
            common_peak_display_df,
            gr.update(selected=COMMON_PEAK_TAB_ID),
        )

    return _load_common_peaks
