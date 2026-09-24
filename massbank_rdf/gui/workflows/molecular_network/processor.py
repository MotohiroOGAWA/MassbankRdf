from __future__ import annotations

import io
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterator

import gradio as gr
import pandas as pd

from massbank_rdf.services.common_peak_annotation.common_peak_annotator import annotate_common_peaks_with_massbank
from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.msp_kg.input_page import (
    _merge_kg_evidence,
    _merge_kg_queries,
    _metadata_value,
    _normalize_ion_mode,
    parse_readable_msp_records,
)
from massbank_rdf.gui.workflows.msp_kg.processor import (
    _progress_output,
    build_batch_processor,
)
from massbank_rdf.services.kg.common import normalize_inchikey_values
from massbank_rdf.services.molecular_network import (
    NetworkCondition,
    analyze_conditions,
    build_cytoscape_tables,
    common_cluster_peaks,
    deduplicate_edges,
    generate_similarity_edges,
    fill_missing_match_peak_counts,
    resolve_score_thresholds,
)


def _prepare_spectra(
    documents: list[dict[str, Any]],
    *,
    ion_mode_column: str,
) -> tuple[pd.DataFrame, dict[str, tuple[list[float], list[float]]], dict[str, str]]:
    rows: list[dict[str, Any]] = []
    spectra: dict[str, tuple[list[float], list[float]]] = {}
    aliases: dict[str, list[str]] = {}
    for document in documents:
        records, _, _ = parse_readable_msp_records(document["source_text"])
        for record_index, record in enumerate(records, start=1):
            uid = f"{document['file_name']}::{record_index}"
            name = _metadata_value(record, "Name") or ""
            rows.append(
                {
                    "node_id": uid,
                    "source_file": document["file_name"],
                    "sample_class": document["sample_class"],
                    "msp_record_index": record_index,
                    "msp_name": name,
                    "peak_count": len(record.mz_list),
                    "ion_mode": _normalize_ion_mode(
                        _metadata_value(record, ion_mode_column)
                    )
                    or "",
                }
            )
            spectra[uid] = (record.mz_list, record.intensity_list)
            if name:
                aliases.setdefault(str(name), []).append(uid)
    alias_map = {uid: uid for uid in spectra}
    alias_map.update(
        {name: values[0] for name, values in aliases.items() if len(values) == 1}
    )
    return pd.DataFrame(rows), spectra, alias_map


def _remap_edges(edges: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    result = edges.copy()
    unknown: set[str] = set()
    for column in ["SourceID", "TargetID"]:
        mapped = []
        for value in result[column].astype(str):
            if value not in aliases:
                unknown.add(value)
            mapped.append(aliases.get(value, value))
        result[column] = mapped
    if unknown:
        preview = ", ".join(sorted(unknown)[:10])
        raise ValueError(
            f"{len(unknown)} edge node IDs do not match an MSP spectrum: {preview}"
        )
    return deduplicate_edges(result)


def _annotate_unknown_clusters(
    assignments: pd.DataFrame,
    spectra: dict[str, tuple[list[float], list[float]]],
    spectrum_nodes: pd.DataFrame,
    candidates: pd.DataFrame,
    network_job: dict[str, Any],
    search_job: dict[str, Any],
    kg_lookup_service: Any,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    selected_spectra = set()
    if not candidates.empty and {"spectrum_uid", "selected_for_kg"}.issubset(candidates):
        selected_spectra = set(
            candidates.loc[
                candidates["selected_for_kg"].fillna(False), "spectrum_uid"
            ].astype(str)
        )
    settings = network_job.get("common_peak_settings") or {
        "mz_tolerance": search_job["mz_tolerance"],
        "minimum_relative_intensity": network_job["common_relative_intensity"],
        "common_peak_n": network_job["common_peak_limit"],
        "massbank_top_n": search_job["top_n"],
        "min_matched_peaks": search_job["min_matched_peaks"],
        "minimum_similarity": search_job.get("minimum_similarity", 0.5),
        "max_massbank_inchikey": search_job.get("max_massbank_inchikey"),
        "ion_mode": None,
    }
    fallback_rows: list[pd.DataFrame] = []
    common_rows: list[pd.DataFrame] = []
    fallback_keys: list[str] = []
    for cluster_id, cluster in assignments.groupby("cluster_id", sort=False):
        members = cluster["node_id"].astype(str).tolist()
        if selected_spectra.intersection(members):
            continue
        common = common_cluster_peaks(
            spectra,
            members,
            mz_tolerance=float(settings["mz_tolerance"]),
            minimum_presence_fraction=float(
                network_job["common_presence_fraction"]
            ),
            minimum_relative_intensity=float(
                settings["minimum_relative_intensity"]
            ),
            max_peaks=int(settings["common_peak_n"]),
        )
        if common.empty:
            continue
        common.insert(0, "cluster_id", cluster_id)
        common_rows.append(common)
        annotation = annotate_common_peaks_with_massbank(
            common,
            **{key: value for key, value in settings.items() if key != "minimum_relative_intensity"},
        )
        hits = annotation["massbank_hits"].copy()
        if hits.empty:
            continue
        keys = normalize_inchikey_values(
            hits.get("inchikey", pd.Series(dtype=str)).dropna().astype(str).tolist()
        )
        fallback_keys.extend(keys)
        hits["selected_for_kg"] = hits["inchikey"].isin(keys)
        hits["annotation_source"] = "cluster_common_peak_massbank"
        hits["inferred_cluster_id"] = cluster_id
        for member in members:
            member_hits = hits.copy()
            member_hits["spectrum_uid"] = member
            fallback_rows.append(member_hits)
    fallback = (
        pd.concat(fallback_rows, ignore_index=True)
        if fallback_rows
        else pd.DataFrame()
    )
    common_frame = (
        pd.concat(common_rows, ignore_index=True)
        if common_rows
        else pd.DataFrame(
            columns=["cluster_id", "mz", "intensity", "presence_count", "presence_fraction"]
        )
    )
    evidence: dict[str, Any] = {"metadata": {}, "features": []}
    queries: dict[str, Any] = {}
    unique_keys = normalize_inchikey_values(fallback_keys)
    if unique_keys:
        evidence_parts = []
        query_parts = []
        for start in range(0, len(unique_keys), 50):
            part_evidence, part_queries = kg_lookup_service.search_evidence_by_inchikeys(
                unique_keys[start : start + 50],
                limit=100,
                return_query=True,
                use_short_inchikey=False,
            )
            evidence_parts.append(part_evidence)
            query_parts.append(part_queries)
        evidence = _merge_kg_evidence(evidence_parts)
        queries = _merge_kg_queries(query_parts)
    return fallback, common_frame, evidence, queries


def build_molecular_network_processor(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any,
):
    base_processor = build_batch_processor(
        session_store,
        kg_lookup_service,
        session_cookie_name="molecular_network_session_id",
        output_name="molecular_network_result",
    )

    def process(
        request: gr.Request,
        progress=gr.Progress(),
    ) -> Iterator[tuple[str, str]]:
        session_id = (
            request.request.cookies.get("molecular_network_session_id")
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            raise gr.Error("Molecular-network job was not found.")
        if payload.get("network_precomputed"):
            yield _progress_output("Molecular network already completed.", 1.0)
            return
        network_job = payload.get("molecular_network_job")
        search_job = payload.get("msp_batch_job")
        if not isinstance(network_job, dict) or not isinstance(search_job, dict):
            raise gr.Error("Molecular-network settings were not found.")
        search_job_copy = dict(search_job)
        if not network_job.get("edge_tsv"):
            spectrum_nodes, spectra, _ = _prepare_spectra(
                network_job["documents"],
                ion_mode_column=str(
                    search_job_copy.get("ion_mode_column", "IONMODE")
                ),
            )
            ion_modes = spectrum_nodes.set_index("node_id")["ion_mode"].to_dict()
            minimum_network_matches = min(
                int(value) for value in network_job["match_peak_counts"]
            )
            generated_edges = None
            for processed, total, edge_count, result in generate_similarity_edges(
                spectra,
                ion_modes,
                mz_tolerance=float(search_job_copy["mz_tolerance"]),
                minimum_matched_peaks=minimum_network_matches,
            ):
                generated_edges = result if result is not None else generated_edges
                fraction = processed / max(1, total)
                yield _progress_output(
                    "Generating spectrum similarity edges: "
                    f"{processed:,}/{total:,} spectra; "
                    f"{edge_count:,} qualifying edges",
                    0.08 * fraction,
                )
            if generated_edges is None or generated_edges.empty:
                raise gr.Error(
                    "No spectrum-similarity edges met the minimum matched-peak "
                    "condition within the same ion mode."
                )
            network_job["edge_tsv"] = generated_edges.to_csv(
                sep="\t", index=False
            )
            payload["molecular_network_job"] = network_job
            session_store.set(session_id, payload)
        uploaded_edges = pd.read_csv(io.StringIO(network_job["edge_tsv"]), sep="\t")
        if uploaded_edges["MatchPeakCount"].isna().any():
            yield _progress_output(
                "Calculating missing MatchPeakCount from MSP spectra...", 0.04
            )
            _, spectra, aliases = _prepare_spectra(
                network_job["documents"],
                ion_mode_column=str(search_job_copy.get("ion_mode_column", "IONMODE")),
            )
            try:
                uploaded_edges = fill_missing_match_peak_counts(
                    _remap_edges(uploaded_edges, aliases), spectra,
                    mz_tolerance=float(search_job_copy["mz_tolerance"]),
                )
            except ValueError as exc:
                raise gr.Error(str(exc)) from exc
            network_job["edge_tsv"] = uploaded_edges.to_csv(sep="\t", index=False)
            payload["molecular_network_job"] = network_job
            session_store.set(session_id, payload)
            yield _progress_output("MatchPeakCount calculated and applied.", 0.08)
        for message, html in base_processor(request, progress):
            match = re.search(r'value="([0-9.]+)"', html)
            base_fraction = (
                float(match.group(1)) / 100.0 if match else 0.0
            )
            yield _progress_output(message, 0.08 + 0.84 * base_fraction)

        payload = session_store.get(session_id)
        if not isinstance(payload, dict) or not payload.get("kg_precomputed"):
            raise gr.Error("MassBank/KG annotation did not complete.")
        yield _progress_output("Preparing molecular-network parameter grid...", 0.94)
        try:
            spectrum_nodes, spectra, aliases = _prepare_spectra(
                network_job["documents"],
                ion_mode_column=str(search_job_copy.get("ion_mode_column", "IONMODE")),
            )
            edges = pd.read_csv(io.StringIO(network_job["edge_tsv"]), sep="\t")
            edges = _remap_edges(edges, aliases)
            statistics, assignments, filtered = analyze_conditions(
                edges,
                spectrum_nodes["node_id"],
                score_thresholds=network_job["score_thresholds"],
                top_k_values=network_job["top_k_values"],
                match_peak_counts=network_job["match_peak_counts"],
                resolutions=network_job["resolutions"],
                random_seed=network_job["random_seed"],
            )
            selected_score = resolve_score_thresholds(
                edges, [network_job["selected_score"]]
            )[0]
            selected_condition = NetworkCondition(
                selected_score[0],
                selected_score[1],
                network_job["selected_top_k"],
                int(network_job["match_peak_counts"][0]),
                float(network_job["selected_resolution"]),
                int(network_job["random_seed"]),
            ).condition_id
            if selected_condition not in assignments:
                raise ValueError(
                    "The selected export condition is not in the comparison grid. "
                    "Include its Score threshold, top k, MatchPeakCount threshold, "
                    "and resolution in the grid."
                )
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise gr.Error(str(exc)) from exc

        yield _progress_output(
            "Searching unannotated clusters by common peaks (without precursor filter)...",
            0.97,
        )
        candidates = pd.DataFrame(payload.get("massbank_detail_df", []))
        fallback, common_peaks, fallback_evidence, fallback_queries = (
            _annotate_unknown_clusters(
                assignments[selected_condition],
                spectra,
                spectrum_nodes,
                candidates,
                network_job,
                search_job_copy,
                kg_lookup_service,
            )
        )
        if not fallback.empty:
            candidates = pd.concat([candidates, fallback], ignore_index=True)
        kg_evidence = _merge_kg_evidence(
            [payload.get("kg_evidence", {}), fallback_evidence]
        )
        kg_queries = _merge_kg_queries(
            [payload.get("kg_queries", {}), fallback_queries]
        )
        selected_nodes = assignments[selected_condition].merge(
            spectrum_nodes, on="node_id", how="left"
        )
        cytoscape_nodes, cytoscape_edges = build_cytoscape_tables(
            selected_nodes,
            filtered[selected_condition],
            candidates,
            kg_evidence,
        )
        output_dir = Path(payload["output_directory"])
        statistics.to_csv(output_dir / "network_condition_statistics.csv", index=False)
        pd.concat(assignments.values(), ignore_index=True).to_csv(
            output_dir / "network_cluster_assignments_all_conditions.csv",
            index=False,
        )
        selected_nodes.to_csv(
            output_dir / "selected_condition_spectrum_nodes.tsv",
            sep="\t", index=False,
        )
        filtered[selected_condition].to_csv(
            output_dir / "selected_condition_similarity_edges.tsv",
            sep="\t", index=False,
        )
        edges.to_csv(
            output_dir / (
                "generated_similarity_edges.tsv"
                if network_job.get("edge_source") == "generated"
                else "uploaded_similarity_edges.tsv"
            ),
            sep="\t",
            index=False,
        )
        cytoscape_nodes.to_csv(output_dir / "node.tsv", sep="\t", index=False)
        cytoscape_edges.to_csv(output_dir / "edge.tsv", sep="\t", index=False)
        common_peaks.to_csv(
            output_dir / "unannotated_cluster_common_peaks.tsv",
            sep="\t", index=False,
        )
        fallback.to_csv(
            output_dir / "unannotated_cluster_massbank_candidates.tsv",
            sep="\t", index=False,
        )
        (output_dir / "kg_evidence.json").write_text(
            json.dumps(kg_evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        query_dir = output_dir / "sparql"
        query_dir.mkdir(exist_ok=True)
        for name, query in kg_queries.items():
            safe_name = str(name).replace("/", "_").replace("\\", "_")
            (query_dir / f"{safe_name}.sparql").write_text(
                str(query), encoding="utf-8"
            )
        config = {
            "workflow": "molecular_network",
            "selected_condition_id": selected_condition,
            "common_peak_settings": network_job.get("common_peak_settings"),
            "edge_source": network_job.get("edge_source", "uploaded"),
            "reused_msp_kg_result": bool(
                payload.get("reused_msp_kg_result")
            ),
            **{
                key: network_job[key]
                for key in [
                    "score_thresholds", "match_peak_counts", "top_k_values",
                    "resolutions", "selected_score", "selected_top_k",
                    "selected_resolution", "random_seed",
                    "common_presence_fraction", "common_relative_intensity",
                    "common_peak_limit",
                ]
            },
        }
        (output_dir / "molecular_network_config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        archive = Path(payload["output_archive"])
        archive.unlink(missing_ok=True)
        archive = Path(
            shutil.make_archive(
                str(archive.with_suffix("")), "zip", root_dir=output_dir
            )
        )
        payload.update(
            {
                "massbank_detail_df": candidates,
                "kg_evidence": kg_evidence,
                "kg_queries": kg_queries,
                "network_statistics_df": statistics,
                "network_nodes_df": cytoscape_nodes,
                "network_edges_df": cytoscape_edges,
                "selected_network_condition": selected_condition,
                "network_precomputed": True,
                "output_archive": str(archive),
            }
        )
        session_store.set(session_id, payload)
        yield _progress_output(
            f"Completed molecular network: {selected_condition}", 1.0
        )

    return process
