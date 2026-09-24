from __future__ import annotations

import io
from pathlib import Path
import shutil
import tempfile
from typing import Any
import zipfile

import gradio as gr
import pandas as pd

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.msp_kg.input_page import (
    _metadata_value,
    _normalize_ion_mode,
    assign_default_sample_classes,
    inspect_uploaded_msps,
    load_result_payload_from_zip,
    parse_readable_msp_records,
)
from massbank_rdf.gui.workflows.shared.common_peak_conditions_panel import create_common_peak_conditions_panel
from massbank_rdf.services.common_peak_annotation.settings import build_common_peak_settings
from massbank_rdf.services.molecular_network import read_similarity_edges


def _comma_values(text: str, cast, *, allow_all: bool = False) -> list[Any]:
    values: list[Any] = []
    for item in str(text).split(","):
        item = item.strip()
        if not item:
            continue
        if allow_all and item.lower() in {"all", "none"}:
            values.append(None)
        else:
            values.append(cast(item))
    if not values:
        raise ValueError("A parameter list must not be empty.")
    return values


def _reuse_msp_kg_result(
    archive_path: str,
    *,
    session_id: str,
    expected_spectrum_ids: set[str],
    sample_classes: dict[str, str],
) -> dict[str, Any]:
    """Load and safely copy a compatible completed MSP/KG result."""
    imported = load_result_payload_from_zip(archive_path)
    annotations = pd.DataFrame(imported["spectrum_annotation_df"]).copy()
    archived_ids = set(annotations["spectrum_uid"].dropna().astype(str))
    if archived_ids != expected_spectrum_ids:
        missing = len(expected_spectrum_ids - archived_ids)
        unexpected = len(archived_ids - expected_spectrum_ids)
        raise ValueError(
            "The completed MSP KG ZIP does not match the uploaded MSP spectra "
            f"(missing={missing:,}, unexpected={unexpected:,})."
        )
    for key in [
        "spectrum_annotation_df",
        "massbank_detail_df",
    ]:
        frame = pd.DataFrame(imported[key]).copy()
        if not frame.empty and "source_file" in frame:
            frame["sample_class"] = (
                frame["source_file"].astype(str).map(sample_classes)
                .fillna(frame.get("sample_class", ""))
            )
        imported[key] = frame

    job_root = (
        Path(tempfile.gettempdir())
        / "massbank_rdf_msp_jobs"
        / str(session_id)
    )
    output_dir = job_root / "molecular_network_result"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        root = output_dir.resolve()
        for member in archive.infolist():
            target = (output_dir / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Unsafe ZIP member path: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    pd.DataFrame(imported["spectrum_annotation_df"]).to_csv(
        output_dir / "spectrum_inchikey_annotations.csv", index=False
    )
    pd.DataFrame(imported["massbank_detail_df"]).to_csv(
        output_dir / "massbank_candidates_by_spectrum.csv", index=False
    )
    imported_archive = job_root / "molecular_network_result.zip"
    shutil.copy2(archive_path, imported_archive)
    imported.update(
        {
            "output_directory": str(output_dir),
            "output_archive": str(imported_archive),
            "kg_precomputed": True,
            "reused_msp_kg_result": True,
        }
    )
    return imported


def create_app(session_store: TemporarySessionStore) -> gr.Blocks:
    def run(
        msp_files: list[str] | None,
        file_classes: pd.DataFrame,
        edge_file: str | None,
        completed_msp_kg_zip: str | None,
        resume_enabled: bool,
        mz_tolerance: float,
        minimum_relative_intensity: float,
        common_peak_n: float,
        max_massbank_inchikey: float,
        massbank_top_n: float,
        min_matched_peaks: float,
        minimum_similarity: float,
        ion_mode: str,
        use_kg_metadata_rank: bool,
        use_precursor_mz: bool,
        precursor_mz_column: str,
        precursor_tolerance: float,
        ion_mode_column: str,
        score_thresholds: str,
        network_match_peaks: str,
        top_k_values: str,
        resolutions: str,
        selected_score: str,
        selected_top_k: str,
        selected_resolution: float,
        common_presence: float,
        random_seed: int,
        request: gr.Request,
    ) -> str:
        session_id = request.request.cookies.get("molecular_network_session_id")
        if not session_id:
            raise gr.Error("Session ID was not found. Please reload the page.")
        try:
            settings = build_common_peak_settings(
                mz_tolerance, minimum_relative_intensity, common_peak_n,
                max_massbank_inchikey, massbank_top_n, min_matched_peaks,
                minimum_similarity, ion_mode,
            )
            if not 0 <= float(common_presence) <= 1:
                raise ValueError("Minimum cluster presence fraction must be between 0 and 1.")
            if not msp_files:
                raise ValueError("Please upload one or more MSP files.")
            edge_frame = (
                read_similarity_edges(edge_file) if edge_file else None
            )
            if edge_frame is not None and edge_frame.empty:
                raise ValueError("No usable similarity edges were found.")
            class_frame = pd.DataFrame(file_classes)
            if len(class_frame) != len(msp_files) or "sample_class" not in class_frame:
                raise ValueError("The file/class table does not match uploaded files.")
            classes = assign_default_sample_classes(class_frame["sample_class"])
            documents = []
            readable = 0
            total = 0
            skipped = 0
            names: list[str] = []
            expected_spectrum_ids: set[str] = set()
            for position, file_path in enumerate(msp_files):
                path = Path(file_path)
                if path.name in names:
                    raise ValueError("Uploaded MSP file names must be unique.")
                names.append(path.name)
                text = path.read_text(encoding="utf-8", errors="replace")
                records, count, skipped_count = parse_readable_msp_records(text)
                missing_ion_mode = sum(
                    not bool(
                        _normalize_ion_mode(
                            _metadata_value(record, str(ion_mode_column))
                        )
                    )
                    for record in records
                )
                if missing_ion_mode:
                    raise ValueError(
                        f"{path.name}: {missing_ion_mode} readable spectra do "
                        f"not have a usable {ion_mode_column} ion mode value."
                    )
                readable += len(records)
                total += count
                skipped += skipped_count
                documents.append(
                    {
                        "file_name": path.name,
                        "sample_class": classes.iloc[position],
                        "source_text": text,
                    }
                )
                expected_spectrum_ids.update(
                    f"{path.name}::{record_index}"
                    for record_index in range(1, len(records) + 1)
                )
            score_specs = _comma_values(score_thresholds, str)
            match_values = _comma_values(network_match_peaks, int)
            top_values = _comma_values(top_k_values, int, allow_all=True)
            resolution_values = _comma_values(resolutions, float)
            selected_top = _comma_values(selected_top_k, int, allow_all=True)[0]
            max_kg = settings["max_massbank_inchikey"]
        except (OSError, ValueError, TypeError) as exc:
            raise gr.Error(str(exc)) from exc

        payload = {
            "msp_batch_job": {
                "documents": documents,
                "resume_enabled": bool(resume_enabled),
                "top_n": settings["massbank_top_n"],
                "mz_tolerance": float(mz_tolerance),
                "min_matched_peaks": settings["min_matched_peaks"],
                "minimum_similarity": float(minimum_similarity),
                "use_kg_metadata_rank": bool(use_kg_metadata_rank),
                "use_precursor_mz": bool(use_precursor_mz),
                "precursor_mz_column": str(precursor_mz_column),
                "precursor_tolerance": float(precursor_tolerance),
                "use_ion_mode": True,
                "ion_mode_column": str(ion_mode_column),
                "max_massbank_inchikey": max_kg,
                "use_short_inchikey": False,
            },
            "molecular_network_job": {
                "common_peak_settings": settings,
                "documents": documents,
                "edge_tsv": (
                    edge_frame.to_csv(sep="\t", index=False)
                    if edge_frame is not None
                    else None
                ),
                "edge_source": "uploaded" if edge_frame is not None else "generated",
                "score_thresholds": score_specs,
                "match_peak_counts": match_values,
                "top_k_values": top_values,
                "resolutions": resolution_values,
                "selected_score": str(selected_score).strip(),
                "selected_top_k": selected_top,
                "selected_resolution": float(selected_resolution),
                "common_presence_fraction": float(common_presence),
                "common_relative_intensity": settings["minimum_relative_intensity"],
                "common_peak_limit": settings["common_peak_n"],
                "random_seed": int(random_seed),
            },
            "summary": {
                "workflow": "molecular_network",
                "record_count": total,
                "readable_spectrum_count": readable,
                "skipped_record_count": skipped,
                "top_n": settings["massbank_top_n"],
                "mz_tolerance": float(mz_tolerance),
                "min_matched_peaks": settings["min_matched_peaks"],
                "minimum_similarity": float(minimum_similarity),
                "use_kg_metadata_rank": bool(use_kg_metadata_rank),
                "use_precursor_mz": bool(use_precursor_mz),
                "precursor_mz_column": str(precursor_mz_column),
                "precursor_tolerance": float(precursor_tolerance),
                "use_ion_mode": True,
                "ion_mode_column": str(ion_mode_column),
                "max_massbank_inchikey": max_kg,
            },
        }
        if completed_msp_kg_zip:
            network_summary = dict(payload["summary"])
            try:
                reused = _reuse_msp_kg_result(
                    completed_msp_kg_zip,
                    session_id=session_id,
                    expected_spectrum_ids=expected_spectrum_ids,
                    sample_classes={
                        document["file_name"]: document["sample_class"]
                        for document in documents
                    },
                )
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                raise gr.Error(str(exc)) from exc
            original_summary = reused.get("summary", {})
            payload.update(reused)
            payload["summary"] = {
                **original_summary,
                **network_summary,
                "workflow": "molecular_network",
                "reused_msp_kg_result": True,
            }
            payload["msp_batch_job"] = {
                **payload["msp_batch_job"],
                "resume_enabled": False,
            }
        session_store.set(session_id, payload)
        return f"OK:{session_id}"

    with gr.Blocks(title="MSP Molecular Network + KG") as app:
        with gr.Group(elem_classes="massbank-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav"><a href="/">Home</a><span>/</span>
                <span>MSP Molecular Network + KG</span></div>
                <section class="massbank-page-heading">
                <h1>MSP Molecular Network + KG</h1>
                <p>Compare molecular-network conditions, run weighted Leiden,
                annotate through MassBank/KG, and export Cytoscape TSV files.</p>
                </section>
                """
            )
            msp_files = gr.File(
                label="MSP files", type="filepath",
                file_count="multiple",
            )
            msp_status = gr.Textbox(label="Uploaded MSP status", interactive=False)
            file_classes = gr.Dataframe(
                headers=["file_name", "sample_class", "records", "readable", "skipped"],
                datatype=["str", "str", "number", "number", "number"],
                label="Files and sample classes", interactive=True,
            )
            edge_file = gr.File(
                label="Spectrum similarity edges (TSV/CSV, optional)",
                type="filepath",
            )
            gr.Markdown(
                "Required columns: `SourceID`, `TargetID`, `Score`, "
                "`MatchPeakCount`. IDs may be a unique MSP `Name` or "
                "`file.msp::record_number`. If omitted, edges are calculated "
                "from the uploaded MSP spectra using ion-mode-specific cosine "
                "similarity."
            )
            completed_msp_kg_zip = gr.File(
                label="Completed MSP KG result ZIP (optional)",
                type="filepath",
            )
            gr.Markdown(
                "When supplied, MassBank and KG searches are skipped and the "
                "saved candidates/evidence are reused. The ZIP must contain "
                "exactly the same spectrum IDs as the uploaded MSP files."
            )
            resume_enabled = gr.Checkbox(label="Resume from checkpoint", value=False)
            conditions = create_common_peak_conditions_panel()
            gr.Markdown(
                "These conditions control cluster common-peak annotation. "
                "MassBank top N, m/z tolerance, minimum matched peaks, similarity "
                "and InChIKey limit also apply to individual spectra. "
                "Individual spectra use the ion mode stored in the MSP."
            )
            gr.HTML("<h3>Additional molecular-network settings</h3>")
            with gr.Row():
                use_kg_metadata_rank = gr.Checkbox(
                    label="Use KG metadata rank for individual spectra", value=True
                )
                use_precursor_mz = gr.Checkbox(label="Use precursor m/z for individual spectra", value=True)
                precursor_mz_column = gr.Textbox(label="Precursor column", value="PRECURSORMZ")
                precursor_tolerance = gr.Number(label="Precursor tolerance", value=0.01)
                ion_mode_column = gr.Textbox(label="MSP ion mode column", value="IONMODE")
            gr.HTML("<h3>Network condition grid</h3>")
            with gr.Row():
                score_thresholds = gr.Textbox(
                    label="Score thresholds", value="p95,p97,p98,p99",
                    info="Comma-separated fixed values or percentiles.",
                )
                network_match_peaks = gr.Textbox(
                    label="MatchPeakCount thresholds", value="6"
                )
                top_k_values = gr.Textbox(label="Per-node top k", value="5,10,15,20")
                resolutions = gr.Textbox(
                    label="Leiden resolutions", value="0.5,1.0,1.5,2.0"
                )
            gr.HTML("<h3>Condition exported to node.tsv / edge.tsv</h3>")
            with gr.Row():
                selected_score = gr.Textbox(label="Selected Score threshold", value="p95")
                selected_top_k = gr.Textbox(label="Selected top k", value="10")
                selected_resolution = gr.Number(label="Selected resolution", value=1.0)
                random_seed = gr.Number(label="Random seed", value=42, precision=0)
            gr.HTML("<h3>Unannotated-cluster common peak search</h3>")
            with gr.Row():
                common_presence = gr.Slider(
                    label="Minimum cluster presence fraction", minimum=0, maximum=1,
                    value=0,
                    info="0 disables this additional cluster filter.",
                )
            run_button = gr.Button("Run", elem_id="massbank-basic-search-button")
            status = gr.Textbox(visible=False)
            msp_files.upload(
                inspect_uploaded_msps, msp_files, [msp_status, file_classes]
            )
            run_button.click(
                run,
                [
                    msp_files, file_classes, edge_file, completed_msp_kg_zip,
                    resume_enabled, *conditions.inputs,
                    use_kg_metadata_rank, use_precursor_mz, precursor_mz_column,
                    precursor_tolerance, ion_mode_column,
                    score_thresholds, network_match_peaks,
                    top_k_values, resolutions, selected_score, selected_top_k,
                    selected_resolution, common_presence, random_seed,
                ],
                status,
            ).then(
                fn=None, inputs=status, outputs=[],
                js="""(status) => {
                    if (status && status.startsWith("OK:")) {
                      window.location.href = `/molecular-network/result/?job_id=${encodeURIComponent(status.slice(3))}`;
                    }
                }""",
            )
    return app
