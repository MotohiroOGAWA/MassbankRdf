from __future__ import annotations

import gradio as gr
import pandas as pd

from ....session_store import TemporarySessionStore


ANNOTATION_TAB_ID = "annotations"


def make_empty_annotation_dataframe() -> pd.DataFrame:
    """Create empty common peak annotation DataFrame."""
    return pd.DataFrame(
        columns=[
            "common_rank",
            "common_peak_id",
            "mz_mean",
            "record_count",
            "peak_count",
            "massbank_score",
            "massbank_match",
            "accession_id",
            "name",
            "inchikey",
            "formula",
            "precursor_mz",
            "precursor_type",
            "ion_mode",
        ]
    )


def create_annotation_tab() -> gr.Dataframe:
    """Create annotation tab components."""
    return gr.Dataframe(
        label="Common peak annotations",
        value=make_empty_annotation_dataframe(),
        interactive=False,
        wrap=True,
    )


def build_annotation_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "common_peak_session_id",
):
    """Build callback for loading common peak annotations."""

    def _load_annotations(
        request: gr.Request,
    ) -> tuple[
        pd.DataFrame,
        gr.update,
    ]:
        session_id = request.request.cookies.get(session_cookie_name)

        if not session_id:
            return (
                make_empty_annotation_dataframe(),
                gr.update(selected=ANNOTATION_TAB_ID),
            )

        payload = session_store.get(session_id)

        if payload is None or not isinstance(payload, dict):
            return (
                make_empty_annotation_dataframe(),
                gr.update(selected=ANNOTATION_TAB_ID),
            )

        annotation_df = payload.get("peak_annotations_df")

        if annotation_df is None:
            annotation_df = make_empty_annotation_dataframe()
        elif not isinstance(annotation_df, pd.DataFrame):
            annotation_df = pd.DataFrame(annotation_df)

        return (
            annotation_df,
            gr.update(selected=ANNOTATION_TAB_ID),
        )

    return _load_annotations