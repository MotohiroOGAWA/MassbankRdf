from __future__ import annotations

from typing import Any

import pandas as pd
import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.kg.common import normalize_inchikey_values


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


def _extract_inchikeys_from_massbank_df(
    massbank_df: pd.DataFrame,
    *,
    kg_n: int = 3,
) -> list[str]:
    """Extract InChIKeys from MassBank display DataFrame."""
    if massbank_df is None or massbank_df.empty:
        return []

    if "inchikey" not in massbank_df.columns:
        return []

    values = massbank_df["inchikey"].dropna().astype(str).tolist()

    return normalize_inchikey_values(values)[:kg_n]


def _get_kg_df(
    kg_data: dict[str, Any],
    key: str,
) -> pd.DataFrame:
    value = kg_data.get(key, pd.DataFrame())

    if isinstance(value, pd.DataFrame):
        return value

    return pd.DataFrame(value)


def build_kg_loader(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any | None = None,
    *,
    kg_n: int = 3,
    limit: int = 100,
):
    """Build callback for loading KG result from MassBank InChIKeys."""

    def _load_kg_result(
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
                "No MassBank result was found. Please run MassBank search first.",
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                gr.update(selected="kg"),
            )

        massbank_df = payload.get("massbank_display_df")

        if massbank_df is None:
            massbank_df = payload.get("result_df")

        if massbank_df is None:
            massbank_df = pd.DataFrame()
        elif not isinstance(massbank_df, pd.DataFrame):
            massbank_df = pd.DataFrame(massbank_df)

        inchikeys = _extract_inchikeys_from_massbank_df(
            massbank_df,
            kg_n=kg_n,
        )

        if len(inchikeys) == 0:
            return (
                "No valid InChIKey was found in MassBank result.",
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                gr.update(selected="kg"),
            )

        if kg_lookup_service is None:
            status = (
                "KG lookup service is not configured yet.\n\n"
                "Extracted InChIKeys:\n"
                + "\n".join(inchikeys)
            )

            return (
                status,
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                gr.update(selected="kg"),
            )

        kg_data = kg_lookup_service.search_by_inchikeys(
            inchikeys,
            limit=limit,
        )

        payload["kg_data"] = kg_data
        payload["kg_inchikeys"] = inchikeys
        session_store.set(session_id, payload)

        pubchem_compound_df = _get_kg_df(kg_data, "pubchem_compound")
        pubchem_pathway_df = _get_kg_df(kg_data, "pubchem_pathway")
        hmdb_df = _get_kg_df(kg_data, "hmdb")
        knapsack_activity_df = _get_kg_df(kg_data, "knapsack_activity")

        status = (
            "KG lookup finished.\n\n"
            f"InChIKeys: {', '.join(inchikeys)}\n"
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

    return _load_kg_result