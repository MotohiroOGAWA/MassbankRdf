from __future__ import annotations

from typing import Any

import pandas as pd
import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.kg.common import normalize_inchikey_values


def _empty_query_text() -> str:
    """Create empty query text."""
    return ""


def _extract_inchikeys_from_massbank_df(
    massbank_df: pd.DataFrame,
    *,
    kg_n: int = 3,
) -> list[str]:
    """Extract normalized InChIKeys from MassBank display DataFrame."""
    if massbank_df is None or massbank_df.empty:
        return []

    if "inchikey" not in massbank_df.columns:
        return []

    values = massbank_df["inchikey"].dropna().astype(str).tolist()

    return normalize_inchikey_values(values)[:kg_n]


def _get_query(
    queries: dict[str, Any],
    key: str,
) -> str:
    """Get one SPARQL query text."""
    value = queries.get(key, "")

    if value is None:
        return ""

    return str(value)


def create_sparql_tab() -> tuple[
    gr.Textbox,
    gr.Code,
    gr.Code,
    gr.Code,
    gr.Code,
]:
    """Create SPARQL tab components."""
    status_text = gr.Textbox(
        label="SPARQL status",
        lines=6,
        interactive=False,
    )

    pubchem_compound_query = gr.Code(
        label="PubChem compound SPARQL",
        value=_empty_query_text(),
        language="sql",
        lines=16,
        interactive=False,
    )

    pubchem_pathway_query = gr.Code(
        label="PubChem pathway SPARQL",
        value=_empty_query_text(),
        language="sql",
        lines=16,
        interactive=False,
    )

    hmdb_query = gr.Code(
        label="HMDB SPARQL",
        value=_empty_query_text(),
        language="sql",
        lines=16,
        interactive=False,
    )

    knapsack_activity_query = gr.Code(
        label="KNApSAcK activity SPARQL",
        value=_empty_query_text(),
        language="sql",
        lines=16,
        interactive=False,
    )

    return (
        status_text,
        pubchem_compound_query,
        pubchem_pathway_query,
        hmdb_query,
        knapsack_activity_query,
    )


def build_sparql_loader(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any | None = None,
    *,
    kg_n: int = 3,
    limit: int = 100,
):
    """Build callback for creating SPARQL queries and running KG lookup.

    This callback:
      1. Reads MassBank display result from session.
      2. Extracts InChIKeys.
      3. Runs KG lookup with return_query=True.
      4. Stores kg_data and kg_queries in session.
      5. Shows generated SPARQL queries in the SPARQL tab.
    """

    def _load_sparql_and_run_kg(
        request: gr.Request,
    ) -> tuple[
        str,
        str,
        str,
        str,
        str,
        gr.update,
    ]:
        session_id = request.request.cookies.get("kg_session_id")

        if not session_id:
            return (
                "Session ID was not found. Please go back and run search again.",
                "",
                "",
                "",
                "",
                gr.update(selected="sparql"),
            )

        payload = session_store.get(session_id)

        if payload is None or not isinstance(payload, dict):
            return (
                "No MassBank result was found. Please run MassBank search first.",
                "",
                "",
                "",
                "",
                gr.update(selected="sparql"),
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
                "",
                "",
                "",
                "",
                gr.update(selected="sparql"),
            )

        if kg_lookup_service is None:
            status = (
                "KG lookup service is not configured yet.\n\n"
                "Extracted InChIKeys:\n"
                + "\n".join(inchikeys)
            )

            payload["kg_inchikeys"] = inchikeys
            session_store.set(session_id, payload)

            return (
                status,
                "",
                "",
                "",
                "",
                gr.update(selected="sparql"),
            )

        kg_data, kg_queries = kg_lookup_service.search_by_inchikeys(
            inchikeys,
            limit=limit,
            return_query=True,
        )

        payload["kg_inchikeys"] = inchikeys
        payload["kg_data"] = kg_data
        payload["kg_queries"] = kg_queries
        session_store.set(session_id, payload)

        status = (
            "SPARQL queries were generated and KG lookup was executed.\n\n"
            f"InChIKeys: {', '.join(inchikeys)}"
        )

        return (
            status,
            _get_query(kg_queries, "pubchem_compound"),
            _get_query(kg_queries, "pubchem_pathway"),
            _get_query(kg_queries, "hmdb"),
            _get_query(kg_queries, "knapsack_activity"),
            gr.update(selected="sparql"),
        )

    return _load_sparql_and_run_kg