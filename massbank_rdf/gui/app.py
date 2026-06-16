from __future__ import annotations

import gradio as gr

from .workflows.kg_search.page import render_workflow_item_html as render_kg_workflow_item_html
from .workflows.common_peak_annotation.page import render_workflow_item_html as render_common_peak_annotation_workflow_item_html


def create_app() -> gr.Blocks:
    with gr.Blocks(title="MassBank RDF") as app:
        with gr.Group(elem_classes="massbank-page massbank-home"):
            gr.HTML(
                """
                <section class="massbank-hero">
                    <div class="massbank-title-block">
                        <div class="massbank-kicker">MassBank RDF Portal</div>
                        <h1>MassBank RDF</h1>
                        <p>
                            MassBank RDF provides tools for spectrum search,
                            MassBank record inspection, and knowledge graph based
                            exploration of compounds, spectra, and biological context.
                        </p>
                    </div>
                </section>
                """
            )

            gr.HTML(
                """
                <section class="massbank-section">
                    <h2>Available Workflows</h2>
                    <div class="massbank-rule"></div>
                </section>
                """
            )

            gr.HTML(render_kg_workflow_item_html())
            gr.HTML(render_common_peak_annotation_workflow_item_html())

    return app