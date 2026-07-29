from __future__ import annotations

import gradio as gr


DEFAULT_MINIMUM_SIMILARITY = 0.5


def create_minimum_similarity_input() -> gr.Number:
    """Create the shared MassBank candidate similarity cutoff input."""
    return gr.Number(
        label="Minimum cosine similarity",
        value=DEFAULT_MINIMUM_SIMILARITY,
        minimum=0,
        maximum=1,
        info=(
            "Candidates with similarity <= this value are removed. "
            "Remaining InChIKeys are ordered by similarity rank + "
            "precomputed KG metadata-count rank."
        ),
    )
