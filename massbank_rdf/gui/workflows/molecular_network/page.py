from __future__ import annotations


def render_workflow_item_html() -> str:
    return """
    <section class="massbank-tool-grid">
        <div class="massbank-tool-item">
            <h3><a href="/molecular-network/">MSP Molecular Network + KG</a></h3>
            <p>
                Build and compare weighted Leiden molecular networks, annotate
                clusters from MSP metadata, enrich unannotated clusters through
                common peaks and KG, and export Cytoscape tables.
            </p>
        </div>
    </section>
    """
