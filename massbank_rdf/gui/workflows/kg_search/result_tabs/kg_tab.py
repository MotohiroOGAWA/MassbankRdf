from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore


def make_empty_kg_dataframe() -> pd.DataFrame:
    """Create an empty KG result table."""
    return pd.DataFrame()


def _dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert DataFrame to JSON-serializable records."""
    if df is None or df.empty:
        return []

    safe_df = df.copy()
    safe_df = safe_df.where(pd.notnull(safe_df), None)

    return safe_df.to_dict(orient="records")


def _get_kg_df(
    kg_data: dict[str, Any],
    key: str,
) -> pd.DataFrame:
    """Get one KG result DataFrame."""
    value = kg_data.get(key, pd.DataFrame())

    if isinstance(value, pd.DataFrame):
        return value

    return pd.DataFrame(value)


def _kg_data_to_json_text(
    kg_data: dict[str, Any],
    *,
    inchikeys: list[str] | None = None,
) -> str:
    """Convert KG result tables to JSON text."""
    pubchem_compound_df = _get_kg_df(kg_data, "pubchem_compound")
    pubchem_pathway_df = _get_kg_df(kg_data, "pubchem_pathway")
    hmdb_df = _get_kg_df(kg_data, "hmdb")
    knapsack_activity_df = _get_kg_df(kg_data, "knapsack_activity")

    data = {
        "inchikeys": inchikeys or [],
        "pubchem_compound": _dataframe_to_records(pubchem_compound_df),
        "pubchem_pathway": _dataframe_to_records(pubchem_pathway_df),
        "hmdb": _dataframe_to_records(hmdb_df),
        "knapsack_activity": _dataframe_to_records(knapsack_activity_df),
    }

    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )


def _write_kg_download_files(
    kg_data: dict[str, Any],
    *,
    inchikeys: list[str] | None = None,
) -> tuple[str, str]:
    """Write KG result JSON and CSV zip files for download."""
    output_dir = Path(
        tempfile.mkdtemp(prefix="massbank_rdf_kg_")
    )

    json_path = output_dir / "kg_result.json"
    zip_path = output_dir / "kg_result_csv.zip"

    kg_json_text = _kg_data_to_json_text(
        kg_data,
        inchikeys=inchikeys,
    )

    json_path.write_text(
        kg_json_text,
        encoding="utf-8",
    )

    table_map = {
        "pubchem_compound": _get_kg_df(kg_data, "pubchem_compound"),
        "pubchem_pathway": _get_kg_df(kg_data, "pubchem_pathway"),
        "hmdb": _get_kg_df(kg_data, "hmdb"),
        "knapsack_activity": _get_kg_df(kg_data, "knapsack_activity"),
    }

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, df in table_map.items():
            csv_path = output_dir / f"{name}.csv"

            if df is None:
                df = pd.DataFrame()

            df.to_csv(
                csv_path,
                index=False,
                encoding="utf-8-sig",
            )

            zf.write(
                csv_path,
                arcname=f"{name}.csv",
            )

    return str(json_path), str(zip_path)


def create_kg_tab() -> tuple[
    gr.Textbox,
    gr.Dataframe,
    gr.Dataframe,
    gr.Dataframe,
    gr.Dataframe,
    gr.File,
    gr.File,
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

    with gr.Row():
        kg_json_file = gr.File(
            label="Download KG JSON",
            interactive=False,
        )

        kg_csv_zip_file = gr.File(
            label="Download KG CSV zip",
            interactive=False,
        )

    return (
        status_text,
        pubchem_compound_table,
        pubchem_pathway_table,
        hmdb_table,
        knapsack_activity_table,
        kg_json_file,
        kg_csv_zip_file,
    )


def build_kg_display_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "kg_session_id",
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
        str | None,
        str | None,
        gr.update,
    ]:
        session_id = request.request.cookies.get(session_cookie_name)

        if not session_id:
            return (
                "Session ID was not found. Please go back and run search again.",
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                make_empty_kg_dataframe(),
                None,
                None,
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
                None,
                None,
                gr.update(selected="kg"),
            )

        kg_data = payload.get("kg_data", {})
        inchikeys = payload.get("kg_inchikeys", [])

        if not isinstance(kg_data, dict):
            kg_data = {}

        if not isinstance(inchikeys, list):
            inchikeys = []

        pubchem_compound_df = _get_kg_df(kg_data, "pubchem_compound")
        pubchem_pathway_df = _get_kg_df(kg_data, "pubchem_pathway")
        hmdb_df = _get_kg_df(kg_data, "hmdb")
        knapsack_activity_df = _get_kg_df(kg_data, "knapsack_activity")

        kg_json_file_path, kg_csv_zip_file_path = _write_kg_download_files(
            kg_data,
            inchikeys=inchikeys,
        )

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
            kg_json_file_path,
            kg_csv_zip_file_path,
            gr.update(selected="kg"),
        )

    return _load_saved_kg_result