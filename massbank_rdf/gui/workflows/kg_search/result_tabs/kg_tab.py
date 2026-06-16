from __future__ import annotations

from typing import Any

import pandas as pd
import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore


def make_empty_kg_dataframe() -> pd.DataFrame:
    """Create an empty KG result table."""
    return pd.DataFrame()


def create_kg_tab() -> tuple[
    gr.Textbox,
    gr.Dataframe,
    gr.Dataframe,
    gr.Dataframe,
    gr.Dataframe,
]:
    """Create KG tab components."""
    status_text = gr.Textbox(
        label="KG status",
        lines=8,
        interactive=False,
    )

    pubchem_compound_table = gr.Dataframe(
        label="PubChem compound",
        value=make_empty_kg_dataframe(),
        interactive=False,
        wrap=True,
    )

    pubchem_pathway_table = gr.Dataframe(
        label="PubChem pathway",
        value=make_empty_kg_dataframe(),
        interactive=False,
        wrap=True,
    )

    hmdb_table = gr.Dataframe(
        label="HMDB",
        value=make_empty_kg_dataframe(),
        interactive=False,
        wrap=True,
    )

    knapsack_activity_table = gr.Dataframe(
        label="KNApSAcK activity",
        value=make_empty_kg_dataframe(),
        interactive=False,
        wrap=True,
    )

    return (
        status_text,
        pubchem_compound_table,
        pubchem_pathway_table,
        hmdb_table,
        knapsack_activity_table,
    )


def _get_kg_df(
    kg_data: dict[str, Any],
    key: str,
) -> pd.DataFrame:
    """Get one KG result DataFrame."""
    value = kg_data.get(key, pd.DataFrame())

    if isinstance(value, pd.DataFrame):
        return value

    return pd.DataFrame(value)


def build_kg_display_loader(
    session_store: TemporarySessionStore,
):
    """Build callback for displaying saved KG result."""

    def _load_saved_kg_result(
        request: gr.Request,
    ) -> tuple[
        str,
        pd.DataFrame,
        pd.DataFrame,
        pd.DataFrame,
        pd.DataFrame,
        gr.update,
    ]:
        session_id = request.request.cookies.get("kg_session_id")

        if not session_id:
            return (
                "Session ID was not found. Please go back and run search again.",
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                gr.update(selected="kg"),
            )

        payload = session_store.get(session_id)

        if payload is None or not isinstance(payload, dict):
            return (
                "No KG result was found. Please run search again.",
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                gr.update(selected="kg"),
            )

        kg_data = payload.get("kg_data", {})
        inchikeys = payload.get("kg_inchikeys", [])

        if not isinstance(kg_data, dict):
            kg_data = {}

        pubchem_compound_df = _get_kg_df(kg_data, "pubchem_compound")
        pubchem_pathway_df = _get_kg_df(kg_data, "pubchem_pathway")
        hmdb_df = _get_kg_df(kg_data, "hmdb")
        knapsack_activity_df = _get_kg_df(kg_data, "knapsack_activity")

        status = (
            "KG result was loaded from the current browser session.\n\n"
            f"InChIKeys: {', '.join(inchikeys) if inchikeys else '-'}\n"
            f"PubChem compound rows: {len(pubchem_compound_df)}\n"
            f"PubChem pathway rows: {len(pubchem_pathway_df)}\n"
            f"HMDB rows: {len(hmdb_df)}\n"
            f"KNApSAcK activity rows: {len(knapsack_activity_df)}"
        )

        return (
            status,
            pubchem_compound_df,
            pubchem_pathway_df,
            hmdb_df,
            knapsack_activity_df,
            gr.update(selected="kg"),
        )

    return _load_saved_kg_result