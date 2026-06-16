from __future__ import annotations

from pathlib import Path

import gradio as gr
import numpy as np
import pandas as pd

from massbank_rdf.gui.session_store import TemporarySessionStore


EXAMPLE_PEAKS_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "single_record_peaks.txt"
)

EXAMPLE_PEAKS_TEXT = EXAMPLE_PEAKS_PATH.read_text(
    encoding="utf-8",
    errors="replace",
)


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


def _parse_peak_text_to_numpy(text: str) -> np.ndarray:
    """Parse whitespace/tab-separated mz intensity text into a numpy array.

    Expected format:
        mz intensity
        mz intensity
        ...

    Returns
    -------
    np.ndarray
        Shape: [N, 2]
        Column 0: mz
        Column 1: intensity
    """
    if not text or not text.strip():
        raise gr.Error("Please paste peak text.")

    rows: list[list[float]] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        if not stripped:
            continue

        # Allow whitespace, tab, and comma-separated text.
        normalized = stripped.replace(",", " ")
        items = normalized.split()

        if len(items) < 2:
            raise gr.Error(
                f"Invalid peak line at line {line_number}.\n"
                f"Expected: mz intensity\n"
                f"Line: {line}"
            )

        try:
            mz = float(items[0])
            intensity = float(items[1])
        except ValueError as e:
            raise gr.Error(
                f"Failed to parse peak values at line {line_number}.\n"
                f"Expected numeric mz and intensity.\n"
                f"Line: {line}"
            ) from e

        rows.append([mz, intensity])

    if not rows:
        raise gr.Error("No valid peak rows were found.")

    peak_array = np.asarray(rows, dtype=np.float64)

    if peak_array.ndim != 2 or peak_array.shape[1] != 2:
        raise gr.Error(
            f"Invalid peak array shape: {peak_array.shape}. "
            "Expected shape is [N, 2]."
        )

    return peak_array


def _peak_array_to_dataframe(peak_array: np.ndarray) -> pd.DataFrame:
    """Convert peak numpy array to DataFrame for display."""
    return pd.DataFrame(
        {
            "peak_index": np.arange(len(peak_array), dtype=np.int64),
            "mz": peak_array[:, 0],
            "intensity": peak_array[:, 1],
        }
    )


def create_app(
    session_store: TemporarySessionStore,
) -> gr.Blocks:

    def _run_search_and_save_to_session(
        spectrum_text: str,
        request: gr.Request,
    ) -> str:
        """Parse peak text and save result DataFrame to session store."""
        session_id = request.request.cookies.get("kg_session_id")

        if not session_id:
            raise gr.Error("Session ID was not found. Please reload the page.")

        peak_array = _parse_peak_text_to_numpy(spectrum_text)
        result_df = _peak_array_to_dataframe(peak_array)

        session_store.set(
            session_id=session_id,
            value={
                "result_df": result_df,
                "summary": {
                    "peak_count": len(result_df),
                    "min_mz": float(result_df["mz"].min()),
                    "max_mz": float(result_df["mz"].max()),
                    "max_intensity": float(result_df["intensity"].max()),
                },
            },
        )

        return "OK"

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
                        Upload or paste peak data as whitespace-separated
                        m/z and intensity pairs.
                    </p>
                </section>
                """
            )

            with gr.Group(elem_classes="massbank-form-panel"):
                gr.HTML("<h3>Input Peaks</h3>")

                example_button = gr.Button(
                    "Load Example",
                    elem_id="massbank-example-button",
                )

                spectrum_text = gr.Textbox(
                    label="Peak text",
                    lines=16,
                    placeholder=EXAMPLE_PEAKS_TEXT,
                )

                run_button = gr.Button(
                    "Run",
                    elem_id="massbank-basic-search-button",
                )

            status_box = gr.Textbox(
                visible=False,
            )

            example_button.click(
                fn=lambda: EXAMPLE_PEAKS_TEXT,
                inputs=[],
                outputs=spectrum_text,
            )

            run_button.click(
                fn=_run_search_and_save_to_session,
                inputs=spectrum_text,
                outputs=status_box,
            ).then(
                fn=None,
                inputs=status_box,
                outputs=[],
                js="""
                (status) => {
                    if (status === "OK") {
                        window.location.href = "/kg/result/";
                    }
                }
                """,
            )

    return app