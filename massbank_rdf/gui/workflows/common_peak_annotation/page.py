from __future__ import annotations

import gradio as gr


def render_workflow_item_html() -> str:
    """Render workflow item shown on the Home page."""
    return """
    <section class="massbank-tool-grid">
        <div class="massbank-tool-item">
            <h3>
                <a href="/common-peak/">Common Peak Annotation</a>
            </h3>
            <p>
                Extract common MS/MS product-ion peaks across multiple records,
                search MassBank using highly shared peaks, and annotate common m/z
                values with candidate compounds.
            </p>
        </div>
    </section>
    """


def create_app() -> gr.Blocks:
    """Create Common Peak Annotation landing page."""
    with gr.Blocks(title="Common Peak Annotation") as app:
        with gr.Group(elem_classes="massbank-page massbank-common-peak-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a>
                    <span>/</span>
                    <span>Common Peak Annotation</span>
                </div>

                <section class="massbank-page-heading">
                    <h1>Common Peak Annotation</h1>
                    <p>
                        Extract common MS/MS peaks from multiple records and
                        annotate shared m/z values using MassBank search hits.
                    </p>
                </section>

                <section class="massbank-demo-box">
                    <h3>Workflow</h3>
                    <ol>
                        <li>Input multiple MSP records.</li>
                        <li>Detect common m/z peaks across records.</li>
                        <li>Rank common peaks by the number of records sharing them.</li>
                        <li>Search MassBank using the top common peaks.</li>
                        <li>Annotate common m/z values using MassBank hit records.</li>
                    </ol>
                </section>

                <section class="massbank-demo-box">
                    <h3>Start</h3>
                    <p>
                        <a href="/common-peak/input/">Open Common Peak Annotation</a>
                    </p>
                </section>
                """
            )

    return app