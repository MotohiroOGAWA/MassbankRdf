from __future__ import annotations

from pathlib import Path

import gradio as gr


def _read_uploaded_file_and_clear(
    file_path: str | None,
    current_text: str,
) -> tuple[str, gr.update]:
    """Read uploaded file text and clear the File component.

    When file_path is None, keep current_text because clearing the File
    component can trigger this function again.
    """
    if file_path is None:
        return current_text, gr.update(value=None)

    path = Path(file_path)

    if not path.exists():
        return current_text, gr.update(value=None)

    text = path.read_text(encoding="utf-8", errors="replace")

    return text, gr.update(value=None)


def create_app() -> gr.Blocks:
    with gr.Blocks(title="Knowledge Graph Search - Input") as app:
        with gr.Group(elem_classes="massbank-page massbank-kg-input-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a>
                    <span>/</span>
                    <span>Knowledge Graph Search</span>
                </div>

                <section class="massbank-page-heading">
                    <h1>Knowledge Graph Search</h1>
                    <p>
                        Upload or paste MSP/MGF spectrum data.
                        The spectrum will be used for MassBank cosine similarity search
                        and downstream knowledge graph interpretation.
                    </p>
                </section>
                """
            )

            with gr.Group(elem_classes="massbank-form-panel"):
                gr.HTML("<h3>Input Spectrum</h3>")

                spectrum_file = gr.File(
                    label="Upload MSP or MGF file",
                    file_types=[".msp", ".mgf", ".txt"],
                    type="filepath",
                )

                spectrum_text = gr.Textbox(
                    label="MSP / MGF text",
                    lines=16,
                    placeholder=(
                        "Paste MSP or MGF text here.\n\n"
                        "Example:\n"
                        "BEGIN IONS\n"
                        "PEPMASS=230.055\n"
                        "60.0554 349996.2\n"
                        "188.0334 8808.9\n"
                        "END IONS"
                    ),
                )

                run_button = gr.Button(
                    "Run",
                    elem_id="massbank-basic-search-button",
                )

            spectrum_file.change(
                fn=_read_uploaded_file_and_clear,
                inputs=[
                    spectrum_file,
                    spectrum_text,
                ],
                outputs=[
                    spectrum_text,
                    spectrum_file,
                ],
            )

            run_button.click()

    return app