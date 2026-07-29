from __future__ import annotations

import gradio as gr


def render_workflow_item_html() -> str:
    return """
    <section class="massbank-tool-grid">
        <div class="massbank-tool-item">
            <h3><a href="/msp-kg/">MSP Knowledge Graph Annotation</a></h3>
            <p>
                Read an MSP spectrum, find related MassBank records, and enrich
                the candidate compounds with PubChem, HMDB, and KNApSAcK
                knowledge graph evidence.
            </p>
        </div>
    </section>
    """


def create_app() -> gr.Blocks:
    with gr.Blocks(title="MSP Knowledge Graph Annotation") as app:
        with gr.Group(elem_classes="massbank-page massbank-msp-kg-page"):
            gr.HTML("")
    return app
