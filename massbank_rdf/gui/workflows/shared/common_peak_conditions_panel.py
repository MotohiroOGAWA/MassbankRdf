from __future__ import annotations

from dataclasses import dataclass, fields
import gradio as gr

from .candidate_ranking_panel import create_minimum_similarity_input


@dataclass
class CommonPeakConditionsPanel:
    mz_tolerance: gr.components.Component
    minimum_relative_intensity: gr.components.Component
    common_peak_n: gr.components.Component
    max_massbank_inchikey: gr.components.Component
    massbank_top_n: gr.components.Component
    min_matched_peaks: gr.components.Component
    minimum_similarity: gr.components.Component
    ion_mode: gr.components.Component

    @property
    def inputs(self) -> list:
        return [getattr(self, field.name) for field in fields(self)]


def create_common_peak_conditions_panel(
    *, default_max_massbank_inchikey: int | None = None,
) -> CommonPeakConditionsPanel:
    """Build the common annotation controls shared by all workflows."""
    gr.HTML("<h3>Common peak annotation conditions</h3>")

    with gr.Row():
        mz_tolerance = gr.Number(
            label="m/z tolerance",
            value=0.01,
            precision=None,
            minimum=0,
        )

        minimum_relative_intensity = gr.Number(
            label="Minimum relative intensity",
            value=0.05,
            minimum=0,
            maximum=1,
            info="Relative to each record's maximum intensity. "
            "0.05 removes peaks below 5%; 0 disables filtering.",
        )

        common_peak_n = gr.Number(
            label="Common peak N",
            value=10,
            precision=0,
            minimum=1,
        )

        max_massbank_inchikey = gr.Number(
            label="Max MassBank InChIKey",
            value=default_max_massbank_inchikey,
            precision=0,
            minimum=1,
            info="Blank means all unique InChIKeys from MassBank hits.",
        )

    with gr.Row():
        massbank_top_n = gr.Number(
            label="MassBank top N",
            value=50,
            precision=0,
            minimum=1,
        )

        min_matched_peaks = gr.Number(
            label="Min matched peaks",
            value=3,
            precision=0,
            minimum=1,
        )

        minimum_similarity = create_minimum_similarity_input()

        ion_mode = gr.Dropdown(
            label="Ion mode",
            choices=[
                "",
                "Positive",
                "Negative",
            ],
            value="Positive",
        )

    return CommonPeakConditionsPanel(mz_tolerance, minimum_relative_intensity, common_peak_n, max_massbank_inchikey, massbank_top_n, min_matched_peaks, minimum_similarity, ion_mode)
