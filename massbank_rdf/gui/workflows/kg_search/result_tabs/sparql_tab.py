from __future__ import annotations

from typing import Any

import pandas as pd
import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.kg.common import normalize_inchikey_values


def _empty_query_text() -> str:
    """Create empty query text."""
    return ""

def _normalize_max_massbank_inchikey(
    value: Any,
) -> int | None:
    """Normalize max MassBank InChIKey setting.

    None or '-' means no limit.
    """
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if value == "" or value == "-":
            return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    return number

def _extract_inchikeys_from_massbank_df(
    massbank_df: pd.DataFrame,
    *,
    max_massbank_inchikey: int | None = None,
) -> list[str]:
    """Extract normalized InChIKeys from MassBank display DataFrame.

    The order follows the MassBank result table order.
    If max_massbank_inchikey is None, all unique InChIKeys are used.
    """
    if massbank_df is None or massbank_df.empty:
        return []

    if "inchikey" not in massbank_df.columns:
        return []

    values = massbank_df["inchikey"].dropna().astype(str).tolist()
    inchikeys = normalize_inchikey_values(values)

    if max_massbank_inchikey is None:
        return inchikeys

    return inchikeys[:max_massbank_inchikey]


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
    fallback_max_massbank_inchikey: int | None = None,
    limit: int = 100,
    session_cookie_name: str = "kg_session_id",
):
    """Build callback for creating SPARQL queries and running KG lookup.

    This callback:
      1. Reads MassBank display result from session.
      2. Extracts InChIKeys.
      3. Runs KG lookup with return_query=True.
      4. Converts KG lookup tables to compact KG evidence JSON.
      5. Stores kg_evidence and kg_queries in session.
      6. Shows generated SPARQL queries in the SPARQL tab.
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
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )

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

        if payload.get("kg_precomputed"):
            inchikeys = payload.get("kg_inchikeys", [])
            queries = payload.get("kg_queries", {})
            if not isinstance(inchikeys, list):
                inchikeys = []
            if not isinstance(queries, dict):
                queries = {}
            status = (
                "KG lookup was completed during MSP batch processing.\n\n"
                f"Unique InChIKeys: {len(inchikeys):,}\n"
                "The queries below are grouped by KG lookup chunk."
            )
            return (
                status,
                _get_query(queries, "pubchem_compound"),
                _get_query(queries, "pubchem_pathway"),
                _get_query(queries, "hmdb"),
                _get_query(queries, "knapsack_activity"),
                gr.update(selected="sparql"),
            )

        massbank_df = payload.get("massbank_display_df")

        if massbank_df is None:
            massbank_df = payload.get("result_df")

        if massbank_df is None:
            massbank_df = pd.DataFrame()
        elif not isinstance(massbank_df, pd.DataFrame):
            massbank_df = pd.DataFrame(massbank_df)

        summary = payload.get("summary", {})

        if not isinstance(summary, dict):
            summary = {}

        max_massbank_inchikey = _normalize_max_massbank_inchikey(
            summary.get("max_massbank_inchikey")
        )

        if max_massbank_inchikey is None:
            max_massbank_inchikey = fallback_max_massbank_inchikey

        inchikeys = _extract_inchikeys_from_massbank_df(
            massbank_df,
            max_massbank_inchikey=max_massbank_inchikey,
        )
        use_short_inchikey = bool(summary.get("use_short_inchikey", False))

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
            limit_label = (
                str(max_massbank_inchikey)
                if max_massbank_inchikey is not None
                else "all"
            )

            status = (
                "KG lookup service is not configured yet.\n\n"
                f"Max MassBank InChIKey for KG: {limit_label}\n"
                f"InChIKey matching: {'short (connectivity)' if use_short_inchikey else 'full'}\n"
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

        kg_evidence, kg_queries = kg_lookup_service.search_evidence_by_inchikeys(
            inchikeys,
            limit=limit,
            return_query=True,
            use_short_inchikey=use_short_inchikey,
        )

        payload["kg_inchikeys"] = inchikeys
        payload["kg_evidence"] = kg_evidence
        payload["kg_queries"] = kg_queries
        payload.pop("kg_data", None)
        session_store.set(session_id, payload)

        limit_label = (
            str(max_massbank_inchikey)
            if max_massbank_inchikey is not None
            else "all"
        )

        status = (
            "SPARQL queries were generated and KG lookup was executed.\n\n"
            f"Max MassBank InChIKey for KG: {limit_label}\n"
            f"InChIKey matching: {'short (connectivity)' if use_short_inchikey else 'full'}\n"
            f"Used InChIKeys: {', '.join(inchikeys)}"
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
