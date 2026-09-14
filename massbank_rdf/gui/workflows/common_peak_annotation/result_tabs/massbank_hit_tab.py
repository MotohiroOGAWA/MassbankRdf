from __future__ import annotations

import gradio as gr
import pandas as pd

from ....session_store import TemporarySessionStore
from .....services.common_peak_annotation.common_peak_annotator import (
    annotate_common_peaks_with_massbank,
    normalize_optional_positive_int,
)


MASSBANK_HIT_TAB_ID = "massbank_hits"


def make_empty_massbank_hit_dataframe() -> pd.DataFrame:
    """Create empty MassBank hit DataFrame."""
    return pd.DataFrame(
        columns=[
            "match",
            "intensity_mean",
            "accession_id",
            "name",
            "inchikey",
            "smiles",
            "formula",
            "precursor_mz",
            "precursor_type",
            "ion_mode",
            "ms_type",
            "collision_energy",
            "retention_time",
            "instrument_type",
            "ionization",
            "fragmentation_mode",
            "splash",
        ]
    )


def create_massbank_hit_tab() -> gr.Dataframe:
    """Create MassBank hit tab components."""
    return gr.Dataframe(
        label="MassBank hits",
        value=make_empty_massbank_hit_dataframe(),
        interactive=False,
        wrap=True,
    )


def _normalize_ion_mode_for_db(
    ion_mode: str | None,
) -> str | None:
    """Normalize ion mode value for database search."""
    if ion_mode is None:
        return None

    value = str(ion_mode).strip()

    if not value or value == "-":
        return None

    if value.lower() == "positive":
        return "POSITIVE"

    if value.lower() == "negative":
        return "NEGATIVE"

    return value


def _calculate_selected_common_peak_intensity_mean(
    selected_common_peaks_df: pd.DataFrame,
) -> float:
    """Calculate mean intensity from selected common peaks.

    Notes
    -----
    The current MassBank hit table does not contain peak-level match details.
    Therefore, this value is calculated from the selected common peaks used
    for the MassBank search.
    """
    if selected_common_peaks_df is None or selected_common_peaks_df.empty:
        return 0.0

    if "mean_intensity" not in selected_common_peaks_df.columns:
        return 0.0

    intensity_series = pd.to_numeric(
        selected_common_peaks_df["mean_intensity"],
        errors="coerce",
    ).dropna()

    if intensity_series.empty:
        return 0.0

    return float(intensity_series.mean())


def _prepare_massbank_hit_dataframe(
    massbank_hits_df: pd.DataFrame,
    *,
    selected_common_peaks_df: pd.DataFrame,
) -> pd.DataFrame:
    """Prepare MassBank hit DataFrame for display.

    The score column is removed.
    The table is sorted by match and intensity_mean in descending order.
    """
    if massbank_hits_df is None or massbank_hits_df.empty:
        return make_empty_massbank_hit_dataframe()

    display_df = massbank_hits_df.copy()

    # Remove cosine score from the display table.
    display_df = display_df.drop(
        columns=["score"],
        errors="ignore",
    )

    # Add intensity_mean for display and sorting.
    #
    # Current MassBank search result does not keep peak-level matched
    # common peak information. Therefore this intensity_mean is calculated
    # from the selected common peaks used for the search.
    display_df["intensity_mean"] = _calculate_selected_common_peak_intensity_mean(
        selected_common_peaks_df
    )

    if "match" in display_df.columns:
        display_df["match"] = pd.to_numeric(
            display_df["match"],
            errors="coerce",
        )

    display_df["intensity_mean"] = (
        pd.to_numeric(
            display_df["intensity_mean"],
            errors="coerce",
        )
        .round(3)
    )

    sort_columns: list[str] = []

    if "match" in display_df.columns:
        sort_columns.append("match")

    if "intensity_mean" in display_df.columns:
        sort_columns.append("intensity_mean")

    if sort_columns:
        display_df = display_df.sort_values(
            by=sort_columns,
            ascending=[False] * len(sort_columns),
        ).reset_index(drop=True)

    first_columns = [
        "match",
        "intensity_mean",
        "accession_id",
        "name",
        "inchikey",
        "smiles",
        "formula",
        "precursor_mz",
        "precursor_type",
        "ion_mode",
        "ms_type",
        "collision_energy",
        "retention_time",
        "instrument_type",
        "ionization",
        "fragmentation_mode",
        "splash",
    ]

    ordered_columns: list[str] = []

    for column in first_columns:
        if column in display_df.columns:
            ordered_columns.append(column)

    for column in display_df.columns:
        if column not in ordered_columns:
            ordered_columns.append(column)

    return display_df[ordered_columns]


def build_massbank_hit_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "common_peak_session_id",
):
    """Build callback for MassBank search using common peaks."""

    def _load_massbank_hits(
        request: gr.Request,
    ) -> tuple[
        pd.DataFrame,
        gr.update,
    ]:
        session_id = request.request.cookies.get(session_cookie_name)

        if not session_id:
            return (
                make_empty_massbank_hit_dataframe(),
                gr.update(selected=MASSBANK_HIT_TAB_ID),
            )

        payload = session_store.get(session_id)

        if payload is None or not isinstance(payload, dict):
            return (
                make_empty_massbank_hit_dataframe(),
                gr.update(selected=MASSBANK_HIT_TAB_ID),
            )

        summary = payload.get("summary", {})

        if not isinstance(summary, dict):
            summary = {}

        common_peaks_df = payload.get("common_peaks_df")

        if common_peaks_df is None:
            common_peaks_df = pd.DataFrame()
        elif not isinstance(common_peaks_df, pd.DataFrame):
            common_peaks_df = pd.DataFrame(common_peaks_df)

        if common_peaks_df.empty:
            return (
                make_empty_massbank_hit_dataframe(),
                gr.update(selected=MASSBANK_HIT_TAB_ID),
            )

        try:
            mz_tolerance = float(summary.get("mz_tolerance", 0.01))
            common_peak_n = int(summary.get("common_peak_n", 10))
            massbank_top_n = int(summary.get("massbank_top_n", 50))
            min_matched_peaks = int(summary.get("min_matched_peaks", 1))
            minimum_similarity = float(summary.get("minimum_similarity", 0.5))
        except (TypeError, ValueError):
            return (
                make_empty_massbank_hit_dataframe(),
                gr.update(selected=MASSBANK_HIT_TAB_ID),
            )

        max_massbank_inchikey = normalize_optional_positive_int(
            summary.get("max_massbank_inchikey")
        )

        ion_mode = _normalize_ion_mode_for_db(
            summary.get("ion_mode")
        )

        annotation_result = annotate_common_peaks_with_massbank(
            common_peaks_df,
            mz_tolerance=mz_tolerance,
            common_peak_n=common_peak_n,
            max_massbank_inchikey=max_massbank_inchikey,
            massbank_top_n=massbank_top_n,
            min_matched_peaks=min_matched_peaks,
            minimum_similarity=minimum_similarity,
            ion_mode=ion_mode,
        )

        selected_common_peaks_df = annotation_result.get(
            "selected_common_peaks",
            pd.DataFrame(),
        )
        raw_massbank_hits_df = annotation_result.get(
            "massbank_hits",
            pd.DataFrame(),
        )
        peak_annotations_df = annotation_result.get(
            "peak_annotations",
            pd.DataFrame(),
        )

        massbank_hits_df = _prepare_massbank_hit_dataframe(
            raw_massbank_hits_df,
            selected_common_peaks_df=selected_common_peaks_df,
        )

        payload["selected_common_peaks_df"] = selected_common_peaks_df
        payload["massbank_hits_df"] = massbank_hits_df

        # Important:
        # Reused SPARQL tab reads payload["massbank_display_df"] and extracts inchikey.
        # This DataFrame no longer contains score.
        payload["massbank_display_df"] = massbank_hits_df

        payload["peak_annotations_df"] = peak_annotations_df

        session_store.set(
            session_id=session_id,
            value=payload,
        )

        return (
            massbank_hits_df,
            gr.update(selected=MASSBANK_HIT_TAB_ID),
        )

    return _load_massbank_hits
