from __future__ import annotations

import gradio as gr


def render_workflow_item_html() -> str:
    """Render workflow item shown on the Home page."""
    return """
    <section class="massbank-tool-grid">
        <div class="massbank-tool-item">
            <h3>
                <a href="/kg/">Knowledge Graph Search</a>
            </h3>
            <p>
                Search RDF-based knowledge graph information related to compounds,
                spectra, pathways, biological context, and external database evidence.
            </p>
        </div>
    </section>
    """


def create_app() -> gr.Blocks:
    with gr.Blocks(title="Knowledge Graph Search") as app:
        with gr.Group(elem_classes="massbank-page massbank-kg-page"):
            gr.HTML("")
    return app