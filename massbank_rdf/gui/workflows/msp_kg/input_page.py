from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
import zipfile

import gradio as gr
import pandas as pd

from massbank_rdf.db.massbank.database import MassBankDatabase
from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.shared.llm_config_panel import build_llm_config
from massbank_rdf.models import MSPRecord
from massbank_rdf.services.kg.common import normalize_inchikey_values


EXAMPLE_MSP_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "caffeine.msp"
)


def load_example_msp() -> str:
    return EXAMPLE_MSP_PATH.read_text(encoding="utf-8", errors="replace")


def split_msp_record_blocks(text: str) -> list[str]:
    """Split an MSP document at record-start Name fields."""
    if not text or not text.strip():
        raise ValueError("MSP text must not be empty.")

    blocks: list[str] = []
    current: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        starts_new_record = (
            bool(current)
            and line.lower().startswith("name:")
        )

        if starts_new_record:
            blocks.append("\n".join(current).strip())
            current = []

        if not line and not current:
            continue

        current.append(raw_line)

    if current:
        blocks.append("\n".join(current).strip())

    return [block for block in blocks if block]


def parse_msp_records(text: str) -> list[MSPRecord]:
    """Parse all spectrum-bearing records in an MSP document."""
    blocks = split_msp_record_blocks(text)
    records: list[MSPRecord] = []
    for index, block in enumerate(blocks, start=1):
        try:
            records.append(MSPRecord.from_msp_text(block))
        except ValueError as exc:
            raise ValueError(f"Failed to parse MSP record {index}: {exc}") from exc

    if not records:
        raise ValueError("No MSP records were found.")
    return records


def parse_readable_msp_records(
    text: str,
) -> tuple[list[MSPRecord], int, int]:
    """Return readable spectra, total record count, and skipped count."""
    blocks = split_msp_record_blocks(text)
    records: list[MSPRecord] = []
    for block in blocks:
        try:
            records.append(MSPRecord.from_msp_text(block))
        except ValueError:
            continue
    return records, len(blocks), len(blocks) - len(records)


def read_msp_records(
    file_path: str | None,
    pasted_text: str | None,
) -> list[MSPRecord]:
    """Read all records, preferring an uploaded MSP file."""
    if file_path:
        path = Path(file_path)
        if path.suffix.lower() != ".msp":
            raise ValueError("The uploaded file must have the .msp extension.")
        return parse_msp_records(
            path.read_text(encoding="utf-8", errors="replace")
        )

    if pasted_text and pasted_text.strip():
        return parse_msp_records(pasted_text)

    raise ValueError("Please upload an MSP file or paste MSP text.")


def read_msp_input(file_path: str | None, pasted_text: str | None) -> MSPRecord:
    """Read one MSP record, preferring an uploaded file when supplied."""
    records = read_msp_records(file_path, pasted_text)
    if len(records) != 1:
        raise ValueError(
            "This execution path currently accepts one record; "
            f"the uploaded MSP contains {len(records)} records."
        )
    return records[0]


def inspect_uploaded_msp(file_path: str | None) -> str:
    """Validate an uploaded MSP and report record and peak counts."""
    if not file_path:
        return "No MSP file is uploaded."
    try:
        path = Path(file_path)
        if path.suffix.lower() != ".msp":
            raise ValueError("The uploaded file must have the .msp extension.")
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks = split_msp_record_blocks(text)
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc

    records: list[MSPRecord] = []
    skipped: list[str] = []
    for index, block in enumerate(blocks, start=1):
        try:
            records.append(MSPRecord.from_msp_text(block))
        except ValueError as exc:
            skipped.append(f"record {index}: {exc}")

    peak_count = sum(record.peaks.shape[0] for record in records)
    status = (
        f"MSP loaded: {len(blocks):,} records; "
        f"{len(records):,} readable spectra; "
        f"{peak_count:,} total peaks."
    )
    if skipped:
        gr.Warning(
            f"Skipped {len(skipped):,} records without readable peaks."
        )
    return status


def inspect_uploaded_msps(
    file_paths: list[str] | None,
) -> tuple[str, pd.DataFrame]:
    """Inspect multiple MSP files and create an editable class table."""
    if not file_paths:
        return "No MSP files are uploaded.", pd.DataFrame(
            columns=["file_name", "sample_class", "records", "readable", "skipped"]
        )

    rows: list[dict[str, Any]] = []
    total_records = 0
    total_readable = 0
    total_skipped = 0
    for file_path in file_paths:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        records, record_count, skipped_count = parse_readable_msp_records(text)
        rows.append(
            {
                "file_name": path.name,
                "sample_class": "",
                "records": record_count,
                "readable": len(records),
                "skipped": skipped_count,
            }
        )
        total_records += record_count
        total_readable += len(records)
        total_skipped += skipped_count

    status = (
        f"MSP loaded: {len(file_paths):,} files; {total_records:,} records; "
        f"{total_readable:,} readable spectra."
    )
    if total_skipped:
        gr.Warning(
            f"Skipped {total_skipped:,} records without readable peaks."
        )
    return status, pd.DataFrame(rows)


def validate_output_name(value: str) -> str:
    """Derive a safe download folder name from a client-side path or name."""
    if not value or not value.strip():
        raise ValueError("Output name is required.")
    name = value.strip().replace("\\", "/").rstrip("/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not name:
        raise ValueError("Output name is invalid.")
    return name


def load_workflow_config_from_zip(
    archive_path: str | None,
    current_file_classes: pd.DataFrame,
) -> tuple[
    str,
    pd.DataFrame,
    str,
    int,
    float,
    int,
    bool,
    str,
    float,
    bool,
    str,
    int | None,
    bool,
]:
    """Load workflow settings and matching sample classes from a result ZIP."""
    if not archive_path:
        raise gr.Error("Please upload a result ZIP.")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            config = json.loads(
                archive.read("workflow_config.json").decode("utf-8")
            )
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise gr.Error(
            "The ZIP does not contain a valid workflow_config.json."
        ) from exc

    search = config.get("search", {})
    saved_classes = {
        str(row.get("file_name", "")): str(row.get("sample_class", ""))
        for row in config.get("files", [])
        if isinstance(row, dict)
    }
    class_df = pd.DataFrame(current_file_classes).copy()
    updated = 0
    if not class_df.empty and "file_name" in class_df and "sample_class" in class_df:
        for index, file_name in class_df["file_name"].items():
            if str(file_name) in saved_classes:
                class_df.at[index, "sample_class"] = saved_classes[str(file_name)]
                updated += 1

    max_kg = search.get("max_massbank_inchikey")
    return (
        (
            f"Configuration loaded: {updated:,} matching file classes updated. "
            "API credentials were not imported."
        ),
        class_df,
        str(config.get("output_name", "kgapp")),
        int(search.get("top_n", 10)),
        float(search.get("mz_tolerance", 0.01)),
        int(search.get("min_matched_peaks", 1)),
        bool(search.get("use_precursor_mz", True)),
        str(search.get("precursor_mz_column", "PRECURSORMZ")),
        float(search.get("precursor_tolerance", 0.01)),
        bool(search.get("use_ion_mode", True)),
        str(search.get("ion_mode_column", "IONMODE")),
        int(max_kg) if max_kg is not None else None,
        bool(search.get("use_short_inchikey", False)),
    )


def _metadata_value(record: MSPRecord, *keys: str) -> str | None:
    for key in keys:
        value = record.get_metadata_value(key)
        if value:
            return value
    return None


def _parse_optional_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _normalize_ion_mode(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper()
    if normalized in {"POSITIVE", "POS", "+"}:
        return "POSITIVE"
    if normalized in {"NEGATIVE", "NEG", "-"}:
        return "NEGATIVE"
    return normalized


def _metadata_as_dict(record: MSPRecord) -> dict[str, Any]:
    return {
        str(key): (None if value is None else str(value))
        for key, value in record.metadata.iloc[0].items()
    }


def _format_massbank_candidates(
    db: MassBankDatabase,
    result_df: pd.DataFrame,
    *,
    spectrum_index: int,
    record: MSPRecord,
) -> pd.DataFrame:
    """Attach candidate metadata and MSP provenance to one search result."""
    if result_df.empty or "id" not in result_df.columns:
        return pd.DataFrame()

    ids = result_df["id"].dropna().astype(int).tolist()
    candidate_df = db.get_records_by_ids_dataframe(ids)
    if candidate_df.empty:
        return pd.DataFrame()

    merged = result_df.merge(candidate_df, on="id", how="left")
    merged.insert(0, "candidate_rank", range(1, len(merged) + 1))
    merged.insert(0, "msp_name", _metadata_value(record, "Name") or "")
    merged.insert(0, "msp_record_index", spectrum_index)
    return merged.drop(
        columns=["id", "dot_product", "reference_norm_square"],
        errors="ignore",
    ).rename(
        columns={
            "cosine_score": "score",
            "matched_peak_count": "match",
        }
    )


def _merge_kg_evidence(
    evidence_parts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge chunked KG evidence while preserving feature order."""
    features: list[dict[str, Any]] = []
    seen: set[str] = set()
    metadata: dict[str, Any] = {}
    for evidence in evidence_parts:
        if not metadata and isinstance(evidence.get("metadata"), dict):
            metadata = dict(evidence["metadata"])
        for feature in evidence.get("features", []):
            if not isinstance(feature, dict):
                continue
            key = str(feature.get("inchikey", ""))
            if key and key not in seen:
                seen.add(key)
                features.append(feature)
    metadata["feature_count"] = len(features)
    metadata["kg_chunk_count"] = len(evidence_parts)
    return {"metadata": metadata, "features": features}


def _merge_kg_queries(
    query_parts: list[dict[str, Any]],
) -> dict[str, str]:
    keys = [
        "pubchem_compound",
        "pubchem_pathway",
        "hmdb",
        "knapsack_activity",
    ]
    return {
        key: "\n\n".join(
            f"# Chunk {index}\n{part.get(key, '')}"
            for index, part in enumerate(query_parts, start=1)
        )
        for key in keys
    }


def create_app(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any | None = None,
) -> gr.Blocks:
    def _run(
        msp_files: list[str] | None,
        file_classes: pd.DataFrame,
        output_directory: str,
        resume_enabled: bool,
        top_n: int,
        mz_tolerance: float,
        min_matched_peaks: int,
        use_precursor_mz: bool,
        precursor_mz_column: str,
        precursor_tolerance: float | None,
        use_ion_mode: bool,
        ion_mode_column: str,
        max_massbank_inchikey: int | float | None,
        use_short_inchikey: bool,
        llm_enabled: bool,
        llm_output_language: str,
        azure_openai_endpoint: str,
        azure_openai_deployment: str,
        azure_openai_api_version: str,
        azure_openai_api_key: str,
        llm_user_context: str,
        request: gr.Request,
    ) -> str:
        session_id = request.request.cookies.get("msp_kg_session_id")
        if not session_id:
            raise gr.Error("Session ID was not found. Please reload the page.")

        try:
            if not msp_files:
                raise ValueError("Please upload one or more MSP files.")
            file_names = [Path(path).name for path in msp_files]
            if len(file_names) != len(set(file_names)):
                raise ValueError("Uploaded MSP file names must be unique.")
            output_name = validate_output_name(output_directory)
            class_df = pd.DataFrame(file_classes)
            if len(class_df) != len(msp_files) or "sample_class" not in class_df:
                raise ValueError("The file/class table does not match uploaded files.")
            classes = class_df["sample_class"].fillna("").astype(str).str.strip()
            if (classes == "").any():
                raise ValueError("Sample class is required for every MSP file.")
            if use_precursor_mz and not str(precursor_mz_column).strip():
                raise ValueError("Precursor m/z column name is required.")
            if use_ion_mode and not str(ion_mode_column).strip():
                raise ValueError("Ion mode column name is required.")

            documents: list[dict[str, Any]] = []
            total_record_count = 0
            readable_count = 0
            skipped_record_count = 0
            for index, file_path in enumerate(msp_files):
                path = Path(file_path)
                source_text = path.read_text(encoding="utf-8", errors="replace")
                records, count, skipped = parse_readable_msp_records(source_text)
                documents.append(
                    {
                        "file_name": path.name,
                        "sample_class": classes.iloc[index],
                        "source_text": source_text,
                    }
                )
                total_record_count += count
                readable_count += len(records)
                skipped_record_count += skipped
        except (OSError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc

        if not readable_count:
            raise gr.Error("No readable spectra were found in the MSP input.")
        if skipped_record_count:
            gr.Warning(
                f"Skipped {skipped_record_count:,} records without readable peaks."
            )

        max_kg = None
        if max_massbank_inchikey not in (None, ""):
            try:
                candidate = int(max_massbank_inchikey)
                max_kg = candidate if candidate > 0 else None
            except (TypeError, ValueError):
                max_kg = None

        payload = {
            "msp_batch_job": {
                "documents": documents,
                "output_name": output_name,
                "resume_enabled": bool(resume_enabled),
                "top_n": int(top_n),
                "mz_tolerance": float(mz_tolerance),
                "min_matched_peaks": int(min_matched_peaks),
                "use_precursor_mz": bool(use_precursor_mz),
                "precursor_mz_column": str(precursor_mz_column).strip(),
                "precursor_tolerance": precursor_tolerance,
                "use_ion_mode": bool(use_ion_mode),
                "ion_mode_column": str(ion_mode_column).strip(),
                "max_massbank_inchikey": max_kg,
                "use_short_inchikey": bool(use_short_inchikey),
            },
            "summary": {
                "workflow": "msp_kg",
                "record_count": total_record_count,
                "file_count": len(documents),
                "readable_spectrum_count": readable_count,
                "skipped_record_count": skipped_record_count,
                "massbank_candidate_count": "-",
                "annotated_spectrum_count": "-",
                "unique_kg_inchikey_count": "-",
                "top_n": int(top_n),
                "mz_tolerance": float(mz_tolerance),
                "min_matched_peaks": int(min_matched_peaks),
                "use_precursor_mz": bool(use_precursor_mz),
                "precursor_mz_column": str(precursor_mz_column).strip(),
                "precursor_tolerance": (
                    float(precursor_tolerance)
                    if precursor_tolerance is not None
                    else "-"
                ),
                "use_ion_mode": bool(use_ion_mode),
                "ion_mode_column": str(ion_mode_column).strip(),
                "max_massbank_inchikey": max_kg if max_kg is not None else "-",
                "use_short_inchikey": bool(use_short_inchikey),
            },
            "llm_config": build_llm_config(
                enabled=llm_enabled,
                output_language=llm_output_language,
                azure_openai_endpoint=azure_openai_endpoint,
                azure_openai_deployment=azure_openai_deployment,
                azure_openai_api_version=azure_openai_api_version,
                azure_openai_api_key=azure_openai_api_key,
                user_context=llm_user_context,
            ),
        }
        session_store.set(session_id, payload)
        return f"OK:{session_id}"

    with gr.Blocks(title="MSP Knowledge Graph Annotation") as app:
        with gr.Group(elem_classes="massbank-page massbank-msp-kg-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a><span>/</span>
                    <span>MSP Knowledge Graph Annotation</span>
                </div>
                <section class="massbank-page-heading">
                    <h1>MSP Knowledge Graph Annotation</h1>
                    <p>
                        Read MSP records, search similar MassBank spectra,
                        and attach knowledge graph evidence to the candidates.
                    </p>
                </section>
                """
            )
            msp_files = gr.File(
                label="MSP files",
                file_types=[".msp"],
                type="filepath",
                file_count="multiple",
            )
            msp_file_status = gr.Textbox(
                label="Uploaded MSP status",
                value="No MSP files are uploaded.",
                lines=2,
                interactive=False,
            )
            file_classes = gr.Dataframe(
                headers=["file_name", "sample_class", "records", "readable", "skipped"],
                datatype=["str", "str", "number", "number", "number"],
                label="Files and sample classes",
                interactive=True,
                wrap=True,
            )
            config_zip = gr.File(
                label="Load settings from previous result ZIP",
                file_types=[".zip"],
                type="filepath",
            )
            config_status = gr.Textbox(
                label="Configuration import status",
                interactive=False,
                lines=2,
            )
            with gr.Row():
                output_directory = gr.Textbox(
                    label="Download folder/archive name (required)",
                    placeholder="kgapp",
                    info=(
                        "Results are downloaded as a ZIP to this browser. "
                        "A Windows path may be pasted; its final folder name is used."
                    ),
                )
                resume_enabled = gr.Checkbox(
                    label="Resume from checkpoint",
                    value=False,
                    info="Continue a compatible interrupted run in the output directory.",
                )

            gr.HTML("<h3>MassBank and KG conditions</h3>")
            with gr.Row():
                top_n = gr.Number(label="MassBank top N", value=10, precision=0, minimum=1)
                mz_tolerance = gr.Number(label="m/z tolerance", value=0.01, minimum=0)
                min_matched_peaks = gr.Number(label="Min matched peaks", value=1, precision=0, minimum=1)
            with gr.Row():
                use_precursor_mz = gr.Checkbox(
                    label="Use precursor m/z filter",
                    value=True,
                )
                precursor_mz_column = gr.Textbox(
                    label="MSP precursor m/z column",
                    value="PRECURSORMZ",
                    info="Case-insensitive; spaces and underscores are ignored.",
                )
                precursor_tolerance = gr.Number(
                    label="Precursor tolerance",
                    value=0.01,
                    minimum=0,
                    info="Applied when PrecursorMZ is present in the MSP metadata.",
                )
            with gr.Row():
                use_ion_mode = gr.Checkbox(
                    label="Use ion mode filter",
                    value=True,
                )
                ion_mode_column = gr.Textbox(
                    label="MSP ion mode column",
                    value="IONMODE",
                    info="Case-insensitive; spaces and underscores are ignored.",
                )
                max_massbank_inchikey = gr.Number(
                    label="Max MassBank InChIKey for KG",
                    value=None,
                    precision=0,
                    minimum=1,
                    info="Blank means all unique InChIKeys in the candidates.",
                )
                use_short_inchikey = gr.Checkbox(
                    label="Connect KG using short InChIKey",
                    value=False,
                )

            gr.HTML("<h3>LLM Interpretation (optional)</h3>")
            with gr.Row():
                llm_enabled = gr.Checkbox(label="Run LLM interpretation", value=False)
                llm_output_language = gr.Dropdown(
                    label="Output language",
                    choices=["English", "Japanese"],
                    value="English",
                )
            with gr.Row():
                azure_openai_endpoint = gr.Textbox(label="Azure OpenAI endpoint")
                azure_openai_deployment = gr.Textbox(label="Azure OpenAI deployment")
            with gr.Row():
                azure_openai_api_version = gr.Textbox(
                    label="Azure OpenAI API version", value="2024-10-21"
                )
                azure_openai_api_key = gr.Textbox(label="Azure OpenAI API key", type="password")
            llm_user_context = gr.Textbox(label="Sample origin / context", lines=4)

            run_button = gr.Button("Run", elem_id="massbank-basic-search-button")
            status_box = gr.Textbox(visible=False)

            msp_files.upload(
                fn=inspect_uploaded_msps,
                inputs=msp_files,
                outputs=[msp_file_status, file_classes],
            )
            msp_files.clear(
                fn=lambda: (
                    "No MSP files are uploaded.",
                    pd.DataFrame(
                        columns=[
                            "file_name", "sample_class", "records",
                            "readable", "skipped",
                        ]
                    ),
                ),
                inputs=[],
                outputs=[msp_file_status, file_classes],
            )
            config_zip.upload(
                fn=load_workflow_config_from_zip,
                inputs=[config_zip, file_classes],
                outputs=[
                    config_status,
                    file_classes,
                    output_directory,
                    top_n,
                    mz_tolerance,
                    min_matched_peaks,
                    use_precursor_mz,
                    precursor_mz_column,
                    precursor_tolerance,
                    use_ion_mode,
                    ion_mode_column,
                    max_massbank_inchikey,
                    use_short_inchikey,
                ],
            )
            run_button.click(
                fn=_run,
                inputs=[
                    msp_files, file_classes, output_directory, resume_enabled,
                    top_n, mz_tolerance, min_matched_peaks,
                    use_precursor_mz, precursor_mz_column, precursor_tolerance,
                    use_ion_mode, ion_mode_column,
                    max_massbank_inchikey, use_short_inchikey,
                    llm_enabled, llm_output_language, azure_openai_endpoint,
                    azure_openai_deployment, azure_openai_api_version,
                    azure_openai_api_key, llm_user_context,
                ],
                outputs=status_box,
            ).then(
                fn=None,
                inputs=status_box,
                outputs=[],
                js="""(status) => {
                    if (status && status.startsWith("OK:")) {
                        const jobId = encodeURIComponent(status.slice(3));
                        window.location.href = `/msp-kg/result/?job_id=${jobId}`;
                    }
                }""",
            )

    return app
