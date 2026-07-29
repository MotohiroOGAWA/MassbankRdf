from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
import shutil
import tempfile
from typing import Any

import gradio as gr
import pandas as pd

from massbank_rdf.db.massbank.database import MassBankDatabase
from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.kg.common import normalize_inchikey_values

from .input_page import (
    _format_massbank_candidates,
    _merge_kg_evidence,
    _merge_kg_queries,
    _metadata_value,
    _normalize_ion_mode,
    _parse_optional_float,
    parse_readable_msp_records,
)


def _job_signature(job: dict[str, Any]) -> str:
    comparable = {key: value for key, value in job.items() if key != "resume_enabled"}
    encoded = json.dumps(comparable, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _aggregate_massbank(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df.empty:
        return pd.DataFrame()
    group_columns = [
        column
        for column in ["accession_id", "inchikey", "name", "formula", "smiles"]
        if column in candidate_df
    ]
    grouped = candidate_df.groupby(group_columns, dropna=False, sort=False)
    result = grouped.agg(
        assigned_spectrum_count=("spectrum_uid", "nunique"),
        assigned_file_count=("source_file", "nunique"),
        best_score=("score", "max"),
        mean_score=("score", "mean"),
    ).reset_index()
    class_values = grouped["sample_class"].agg(
        lambda values: ", ".join(sorted(set(map(str, values))))
    ).reset_index(name="sample_classes")
    return result.merge(class_values, on=group_columns, how="left").sort_values(
        ["assigned_spectrum_count", "best_score"],
        ascending=[False, False],
    )


def _feature_summary_map(kg_evidence: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for feature in kg_evidence.get("features", []):
        if isinstance(feature, dict) and feature.get("inchikey"):
            result[str(feature["inchikey"])] = json.dumps(
                feature.get("summary", {}),
                ensure_ascii=False,
                sort_keys=True,
            )
    return result


def _class_inchikey_analysis(
    annotations: pd.DataFrame,
    candidates: pd.DataFrame,
    kg_evidence: dict[str, Any],
) -> pd.DataFrame:
    if annotations.empty or candidates.empty:
        return pd.DataFrame()
    selected = candidates[candidates["selected_for_kg"]].copy()
    selected = selected.dropna(subset=["inchikey"]).drop_duplicates(
        ["spectrum_uid", "inchikey"]
    )
    class_totals = annotations.groupby("sample_class")["spectrum_uid"].nunique()
    total_spectra = int(annotations["spectrum_uid"].nunique())
    feature_summaries = _feature_summary_map(kg_evidence)
    rows: list[dict[str, Any]] = []

    for (sample_class, inchikey), group in selected.groupby(
        ["sample_class", "inchikey"], sort=False
    ):
        in_class = int(group["spectrum_uid"].nunique())
        class_total = int(class_totals[sample_class])
        all_for_key = int(
            selected.loc[selected["inchikey"] == inchikey, "spectrum_uid"].nunique()
        )
        outside = all_for_key - in_class
        outside_total = total_spectra - class_total
        prevalence = in_class / class_total if class_total else 0.0
        outside_prevalence = outside / outside_total if outside_total else 0.0
        enrichment = (
            prevalence / outside_prevalence
            if outside_prevalence > 0
            else (float("inf") if prevalence > 0 else 0.0)
        )
        p_value: float | None = None
        try:
            from scipy.stats import fisher_exact

            p_value = float(
                fisher_exact(
                    [
                        [in_class, class_total - in_class],
                        [outside, outside_total - outside],
                    ]
                ).pvalue
            )
        except (ImportError, ValueError):
            pass
        rows.append(
            {
                "sample_class": sample_class,
                "inchikey": inchikey,
                "spectra_with_inchikey": in_class,
                "class_spectrum_count": class_total,
                "class_prevalence": prevalence,
                "other_class_prevalence": outside_prevalence,
                "enrichment_ratio": enrichment,
                "fisher_exact_p_value": p_value,
                "kg_summary": feature_summaries.get(str(inchikey), ""),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["fisher_exact_p_value", "enrichment_ratio"],
        ascending=[True, False],
        na_position="last",
    )


def _write_outputs(
    output_dir: Path,
    *,
    candidate_df: pd.DataFrame,
    annotation_df: pd.DataFrame,
    aggregate_df: pd.DataFrame,
    class_analysis_df: pd.DataFrame,
    kg_evidence: dict[str, Any],
    kg_queries: dict[str, str],
    summary: dict[str, Any],
    workflow_config: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_df.to_csv(output_dir / "massbank_candidates_by_spectrum.csv", index=False)
    annotation_df.to_csv(output_dir / "spectrum_inchikey_annotations.csv", index=False)
    aggregate_df.to_csv(output_dir / "massbank_record_summary.csv", index=False)
    class_analysis_df.to_csv(output_dir / "class_inchikey_kg_analysis.csv", index=False)
    (output_dir / "kg_evidence.json").write_text(
        json.dumps(kg_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    query_dir = output_dir / "sparql"
    query_dir.mkdir(exist_ok=True)
    for name, query in kg_queries.items():
        (query_dir / f"{name}.sparql").write_text(str(query), encoding="utf-8")
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "workflow_config.json").write_text(
        json.dumps(workflow_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_batch_processor(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any,
):
    def process(request: gr.Request, progress=gr.Progress()) -> str:
        session_id = (
            request.request.cookies.get("msp_kg_session_id")
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            raise gr.Error("MSP batch job was not found. Please return to input.")
        if payload.get("kg_precomputed"):
            return f"Batch processing was already completed: {payload.get('output_directory', '')}"

        job = payload.get("msp_batch_job")
        if not isinstance(job, dict):
            raise gr.Error("MSP batch settings were not found.")
        output_name = str(job.get("output_name", "")).strip()
        if not output_name:
            raise gr.Error("Output name is required.")
        job_root = (
            Path(tempfile.gettempdir())
            / "massbank_rdf_msp_jobs"
            / str(session_id)
        )
        output_dir = job_root / output_name
        resume = bool(job.get("resume_enabled"))
        checkpoint_path = output_dir / "checkpoint.pkl"
        if output_dir.exists() and not resume:
            shutil.rmtree(output_dir)
        if resume and output_dir.exists() and any(output_dir.iterdir()) and not checkpoint_path.exists():
            raise gr.Error("Resume was enabled, but no checkpoint was found.")
        output_dir.mkdir(parents=True, exist_ok=True)

        tasks: list[tuple[str, str, int, Any]] = []
        total_count = 0
        skipped_count = 0
        for document in job.get("documents", []):
            records, count, skipped = parse_readable_msp_records(document["source_text"])
            total_count += count
            skipped_count += skipped
            for file_record_index, record in enumerate(records, start=1):
                tasks.append(
                    (
                        str(document["file_name"]),
                        str(document["sample_class"]),
                        file_record_index,
                        record,
                    )
                )

        signature = _job_signature(job)
        state = {
            "signature": signature,
            "next_index": 0,
            "candidate_parts": [],
            "annotations": [],
            "all_inchikeys": [],
            "kg_next_chunk": 0,
            "evidence_parts": [],
            "query_parts": [],
        }
        if resume and checkpoint_path.exists():
            with checkpoint_path.open("rb") as handle:
                loaded = pickle.load(handle)
            if loaded.get("signature") != signature:
                raise gr.Error("Checkpoint settings do not match the current run.")
            state = loaded

        db = MassBankDatabase()
        max_kg = job.get("max_massbank_inchikey")
        for task_index in range(int(state["next_index"]), len(tasks)):
            file_name, sample_class, file_record_index, record = tasks[task_index]
            progress(
                (task_index, len(tasks)),
                desc=f"MassBank search: spectrum {task_index + 1:,}/{len(tasks):,}",
            )
            precursor_mz = (
                _parse_optional_float(
                    _metadata_value(
                        record,
                        str(job.get("precursor_mz_column", "PRECURSORMZ")),
                    )
                )
                if bool(job.get("use_precursor_mz", True))
                else None
            )
            tolerance = job.get("precursor_tolerance")
            raw = db.search_record_ids_by_cosine_similarity_sql(
                record.mz_list,
                record.intensity_list,
                top_n=int(job["top_n"]),
                mz_tolerance=float(job["mz_tolerance"]),
                min_matched_peaks=int(job["min_matched_peaks"]),
                ion_mode=(
                    _normalize_ion_mode(
                        _metadata_value(
                            record,
                            str(job.get("ion_mode_column", "IONMODE")),
                        )
                    )
                    if bool(job.get("use_ion_mode", True))
                    else None
                ),
                precursor_mz=precursor_mz,
                precursor_tolerance=(
                    float(tolerance)
                    if precursor_mz is not None and tolerance is not None
                    else None
                ),
            )
            candidates = _format_massbank_candidates(
                db,
                raw,
                spectrum_index=task_index + 1,
                record=record,
            )
            spectrum_uid = f"{file_name}::{file_record_index}"
            if not candidates.empty:
                candidates.insert(0, "spectrum_uid", spectrum_uid)
                candidates.insert(1, "source_file", file_name)
                candidates.insert(2, "sample_class", sample_class)
                candidates.insert(3, "file_record_index", file_record_index)
                keys = normalize_inchikey_values(
                    candidates["inchikey"].dropna().astype(str).tolist()
                )
            else:
                keys = []
            annotated = keys[: int(max_kg)] if max_kg is not None else keys
            if not candidates.empty:
                selected = set(annotated)
                candidates["selected_for_kg"] = [
                    bool(key and key[0] in selected)
                    for key in (
                        normalize_inchikey_values([str(value)])
                        for value in candidates["inchikey"]
                    )
                ]
                state["candidate_parts"].append(candidates)
            state["all_inchikeys"].extend(annotated)
            state["annotations"].append(
                {
                    "spectrum_uid": spectrum_uid,
                    "source_file": file_name,
                    "sample_class": sample_class,
                    "file_record_index": file_record_index,
                    "msp_name": _metadata_value(record, "Name") or "",
                    "peak_count": int(record.peaks.shape[0]),
                    "massbank_hit_count": len(candidates),
                    "annotated_inchikey_count": len(annotated),
                    "annotated_inchikeys": ", ".join(annotated),
                }
            )
            state["next_index"] = task_index + 1
            if state["next_index"] % 25 == 0 or state["next_index"] == len(tasks):
                with checkpoint_path.open("wb") as handle:
                    pickle.dump(state, handle)

        candidate_df = (
            pd.concat(state["candidate_parts"], ignore_index=True)
            if state["candidate_parts"]
            else pd.DataFrame()
        )
        annotation_df = pd.DataFrame(state["annotations"])
        unique_keys = normalize_inchikey_values(state["all_inchikeys"])
        evidence_parts: list[dict[str, Any]] = state.setdefault(
            "evidence_parts", []
        )
        query_parts: list[dict[str, Any]] = state.setdefault("query_parts", [])
        chunks = [unique_keys[start : start + 50] for start in range(0, len(unique_keys), 50)]
        kg_start = int(state.setdefault("kg_next_chunk", 0))
        for chunk_offset in range(kg_start, len(chunks)):
            index = chunk_offset + 1
            chunk = chunks[chunk_offset]
            progress((index - 1, max(1, len(chunks))), desc=f"KG search: chunk {index:,}/{len(chunks):,}")
            evidence, queries = kg_lookup_service.search_evidence_by_inchikeys(
                chunk,
                limit=100,
                return_query=True,
                use_short_inchikey=bool(job.get("use_short_inchikey")),
            )
            evidence_parts.append(evidence)
            query_parts.append(queries)
            state["kg_next_chunk"] = index
            with checkpoint_path.open("wb") as handle:
                pickle.dump(state, handle)

        kg_evidence = _merge_kg_evidence(evidence_parts)
        kg_queries = _merge_kg_queries(query_parts)
        aggregate_df = _aggregate_massbank(candidate_df)
        class_analysis_df = _class_inchikey_analysis(
            annotation_df, candidate_df, kg_evidence
        )
        summary = payload.get("summary", {})
        summary.update(
            {
                "record_count": total_count,
                "readable_spectrum_count": len(tasks),
                "skipped_record_count": skipped_count,
                "massbank_candidate_count": len(candidate_df),
                "massbank_record_count": len(aggregate_df),
                "annotated_spectrum_count": int(
                    (annotation_df["annotated_inchikey_count"] > 0).sum()
                ),
                "unique_kg_inchikey_count": len(unique_keys),
                "output_directory": str(output_dir),
            }
        )
        workflow_config = {
            "schema_version": 1,
            "workflow": "msp_kg",
            "output_name": output_name,
            "files": [
                {
                    "file_name": str(document.get("file_name", "")),
                    "sample_class": str(document.get("sample_class", "")),
                }
                for document in job.get("documents", [])
            ],
            "search": {
                key: job.get(key)
                for key in [
                    "top_n",
                    "mz_tolerance",
                    "min_matched_peaks",
                    "use_precursor_mz",
                    "precursor_mz_column",
                    "precursor_tolerance",
                    "use_ion_mode",
                    "ion_mode_column",
                    "max_massbank_inchikey",
                    "use_short_inchikey",
                ]
            },
        }
        _write_outputs(
            output_dir,
            candidate_df=candidate_df,
            annotation_df=annotation_df,
            aggregate_df=aggregate_df,
            class_analysis_df=class_analysis_df,
            kg_evidence=kg_evidence,
            kg_queries=kg_queries,
            summary=summary,
            workflow_config=workflow_config,
        )
        archive_path = Path(
            shutil.make_archive(
                str(job_root / output_name),
                "zip",
                root_dir=output_dir,
            )
        )
        checkpoint_path.unlink(missing_ok=True)
        payload.update(
            {
                "result_df": aggregate_df,
                "massbank_detail_df": candidate_df,
                "spectrum_annotation_df": annotation_df,
                "class_analysis_df": class_analysis_df,
                "kg_inchikeys": unique_keys,
                "kg_evidence": kg_evidence,
                "kg_queries": kg_queries,
                "kg_precomputed": True,
                "output_directory": str(output_dir),
                "output_archive": str(archive_path),
            }
        )
        payload.pop("msp_batch_job", None)
        session_store.set(session_id, payload)
        progress(1.0, desc="MSP batch processing completed")
        return f"Completed. Results saved to: {output_dir}"

    return process
