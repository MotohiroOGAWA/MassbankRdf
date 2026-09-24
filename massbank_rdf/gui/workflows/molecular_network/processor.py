from __future__ import annotations

import io
import json
import shutil
import tempfile
from html import escape
from itertools import product
from pathlib import Path
from typing import Any, Iterator

import gradio as gr
import pandas as pd
import numpy as np

from massbank_rdf.models.msp_record import MSPRecord

from massbank_rdf.services.common_peak_annotation.common_peak_annotator import annotate_common_peaks_with_massbank
from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.msp_kg.input_page import (
    _merge_kg_evidence,
    _merge_kg_queries,
    _metadata_value,
    _normalize_ion_mode,
    split_msp_record_blocks,
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


class StageProgress:
    """Keep one persistent progress bar per stage (no overall percentage)."""

    labels = {
        "input": "MSP / edge input", "edges": "Edge preparation",
        "clusters": "Cluster generation", "annotation": "MSP annotation",
        "common": "Common peaks", "kg": "KG metadata", "output": "Export",
    }

    def __init__(self) -> None:
        self.values = {key: (0.0, "Waiting") for key in self.labels}

    def update(self, stage: str, fraction: float, message: str) -> tuple[str, str]:
        self.values[stage] = (max(0, min(1, fraction)), message)
        bars = []
        for key, label in self.labels.items():
            value, detail = self.values[key]
            bars.append(
                f'<div><strong>{escape(label)}</strong> '
                f'{value * 100:.1f}% — {escape(detail)}'
                f'<progress aria-label="{escape(label)}" style="width:100%;height:20px" '
                f'value="{value * 100:.2f}" max="100"></progress></div>'
            )
        return message, "".join(bars)


def _has_structure(frame: pd.DataFrame) -> pd.Series:
    smiles = frame["smiles"].fillna("").str.strip()
    return (
        frame["inchikey"].str.fullmatch(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", na=False)
        | frame["inchi"].str.startswith("InChI=", na=False)
        | ~smiles.str.lower().isin({"", "na", "n/a", "nan", "none", "null", "unknown", "-"})
    )


def summarize_cluster(cluster_id: str, members: pd.DataFrame) -> dict[str, Any]:
    values = {}
    for column in ("compound_name", "inchikey", "inchi", "smiles"):
        values[column] = sorted({str(value).strip() for value in members[column] if str(value).strip()})
    structure_mask = _has_structure(members)
    return {
        "cluster_id": cluster_id, "member_count": len(members),
        "structure_annotated_member_count": int(structure_mask.sum()),
        "annotation_coverage": float(structure_mask.mean()),
        "annotation_status": "structure_present" if structure_mask.any() else (
            "name_only" if values["compound_name"] else "unannotated"
        ),
        "annotation_source": "msp_metadata",
        **{key: json.dumps(value, ensure_ascii=False) for key, value in values.items()},
        "supporting_node_ids": json.dumps(members.loc[structure_mask, "node_id"].tolist()),
    }


def _prepare_spectra(
    documents: list[dict[str, Any]],
    *,
    ion_mode_column: str,
) -> tuple[pd.DataFrame, dict[str, tuple[list[float], list[float]]], dict[str, str]]:
    rows: list[dict[str, Any]] = []
    spectra: dict[str, tuple[list[float], list[float]]] = {}
    aliases: dict[str, list[str]] = {}
    canonical_aliases: dict[str, str] = {}
    for document in documents:
        blocks = split_msp_record_blocks(document["source_text"])
        for record_index, block in enumerate(blocks):
            uid = str(len(rows))
            canonical_aliases[uid] = uid
            canonical_aliases[f"{document['file_name']}::{record_index}"] = uid
            try:
                record = MSPRecord.from_msp_text(block)
            except ValueError:
                # Retain metadata and numbering even when no valid spectrum exists.
                metadata = {}
                for line in block.splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip()
                    if key.lower().replace(" ", "").replace("_", "") == "numpeaks":
                        break
                    metadata[key] = value.strip()
                record = MSPRecord(metadata=metadata, peaks=np.empty((0, 2)), raw_text=block)
            name = _metadata_value(record, "Name") or ""
            rows.append(
                {
                    "node_id": uid,
                    "source_file": document["file_name"],
                    "sample_class": document["sample_class"],
                    "msp_record_index": record_index,
                    "msp_name": name,
                    "inchikey": (_metadata_value(record, "InChIKey") or "").strip().upper(),
                    "inchi": _metadata_value(record, "InChI") or "",
                    "smiles": _metadata_value(record, "SMILES") or "",
                    "compound_name": _metadata_value(record, "CompoundName") or name,
                    "peak_count": len(record.mz_list),
                    "has_spectrum": bool(len(record.mz_list)),
                    "ion_mode": _normalize_ion_mode(
                        _metadata_value(record, ion_mode_column)
                    )
                    or "",
                }
            )
            if len(record.mz_list):
                spectra[uid] = (record.mz_list, record.intensity_list)
            if name:
                aliases.setdefault(str(name), []).append(uid)
    alias_map = {
        name: values[0] for name, values in aliases.items()
        if len(values) == 1 and not name.isdecimal()
    }
    # Numeric IDs always mean record positions, never numeric Name aliases.
    alias_map.update(canonical_aliases)
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
            f"{len(unknown)} edge node IDs do not match an MSP record: {preview}"
        )
    return deduplicate_edges(result)


def _annotate_unknown_clusters(
    assignments: pd.DataFrame,
    spectra: dict[str, tuple[list[float], list[float]]],
    spectrum_nodes: pd.DataFrame,
    network_job: dict[str, Any],
    search_job: dict[str, Any],
) -> Iterator[tuple[int, int, Any]]:
    structure_mask = _has_structure(spectrum_nodes)
    selected_spectra = set(spectrum_nodes.loc[structure_mask, "node_id"])
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
    groups = [
        (cluster_id, cluster) for cluster_id, cluster in assignments.groupby("cluster_id", sort=False)
        if not selected_spectra.intersection(cluster["node_id"])
    ]
    for index, (cluster_id, cluster) in enumerate(groups, 1):
        yield index - 1, len(groups), None
        members = cluster["node_id"].astype(str).tolist()
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
        hits["selected_for_kg"] = hits["inchikey"].isin(keys)
        hits["score"] = hits.get("cosine_score", hits.get("score", 0.0))
        hits["annotation_source"] = "cluster_common_peak_massbank"
        hits["inferred_cluster_id"] = cluster_id
        hits["spectrum_uid"] = ""
        fallback_rows.append(hits)
    fallback = (
        pd.concat(fallback_rows, ignore_index=True)
        if fallback_rows
        else pd.DataFrame(columns=[
            "inferred_cluster_id", "spectrum_uid", "inchikey", "selected_for_kg",
            "annotation_source", "score", "accession_id",
        ])
    )
    common_frame = (
        pd.concat(common_rows, ignore_index=True)
        if common_rows
        else pd.DataFrame(
            columns=["cluster_id", "mz", "intensity", "presence_count", "presence_fraction"]
        )
    )
    yield len(groups), len(groups), (fallback, common_frame)


def build_molecular_network_processor(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any,
):
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
            stages = StageProgress()
            for stage in stages.labels:
                output = stages.update(stage, 1, "Completed")
            yield output
            return
        network_job = payload.get("molecular_network_job")
        search_job = payload.get("msp_batch_job")
        if not isinstance(network_job, dict) or not isinstance(search_job, dict):
            raise gr.Error("Molecular-network settings were not found.")
        stages = StageProgress()
        yield stages.update("input", 0, "Reading MSP spectra and edge table")
        search_job_copy = dict(search_job)
        spectrum_nodes, spectra, aliases = _prepare_spectra(
            network_job["documents"],
            ion_mode_column=str(search_job_copy.get("ion_mode_column", "IONMODE")),
        )
        yield stages.update("input", 1, f"Read {len(spectrum_nodes):,} records ({len(spectra):,} spectra)")
        yield stages.update("edges", 0, "Preparing similarity edges")
        if not network_job.get("edge_tsv"):
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
                yield stages.update(
                    "edges", fraction,
                    "Generating spectrum similarity edges: "
                    f"{processed:,}/{total:,} spectra; "
                    f"{edge_count:,} qualifying edges",
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
        if "MatchPeakCount" not in uploaded_edges:
            uploaded_edges["MatchPeakCount"] = float("nan")
        if uploaded_edges["MatchPeakCount"].isna().any():
            yield stages.update("edges", 0, "Calculating missing MatchPeakCount from MSP spectra")
            try:
                uploaded_edges = _remap_edges(uploaded_edges, aliases)
                missing_indices = uploaded_edges.index[uploaded_edges["MatchPeakCount"].isna()]
                available = uploaded_edges.loc[missing_indices, ["SourceID", "TargetID"]].isin(list(spectra)).all(axis=1)
                if not available.all():
                    raise ValueError(
                        "MatchPeakCount cannot be calculated for edges whose MSP records have no spectrum. "
                        "Supply MatchPeakCount for those edges in the edge table. "
                        "All records still count toward zero-based Node IDs."
                    )
                for start in range(0, len(missing_indices), 500):
                    indices = missing_indices[start:start + 500]
                    filled = fill_missing_match_peak_counts(
                        uploaded_edges.loc[indices], spectra,
                        mz_tolerance=float(search_job_copy["mz_tolerance"]),
                    )
                    uploaded_edges.loc[indices, "MatchPeakCount"] = filled["MatchPeakCount"]
                    yield stages.update("edges", min(start + 500, len(missing_indices)) / len(missing_indices),
                                        f"Matched-peak counts {min(start + 500, len(missing_indices))}/{len(missing_indices)}")
            except ValueError as exc:
                raise gr.Error(str(exc)) from exc
            network_job["edge_tsv"] = uploaded_edges.to_csv(sep="\t", index=False)
            payload["molecular_network_job"] = network_job
            session_store.set(session_id, payload)
        yield stages.update("edges", 1, "Similarity edges ready")
        yield stages.update("clusters", 0, "Clustering the edge table")
        try:
            edges = pd.read_csv(io.StringIO(network_job["edge_tsv"]), sep="\t")
            edges = _remap_edges(edges, aliases)
            statistics_parts, assignments, filtered = [], {}, {}
            combinations = list(product(
                network_job["score_thresholds"], network_job["top_k_values"],
                network_job["match_peak_counts"], network_job["resolutions"],
            ))
            for index, (score, top_k, matches, resolution) in enumerate(combinations, 1):
                stats, nodes, selected_edges = analyze_conditions(
                    edges, spectrum_nodes["node_id"], score_thresholds=[score],
                    top_k_values=[top_k], match_peak_counts=[matches],
                    resolutions=[resolution], random_seed=network_job["random_seed"],
                )
                statistics_parts.append(stats)
                assignments.update(nodes)
                filtered.update(selected_edges)
                yield stages.update("clusters", index / len(combinations),
                                    f"Cluster conditions {index}/{len(combinations)}")
            statistics = pd.concat(statistics_parts, ignore_index=True)
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

        yield stages.update("annotation", 0, "Aggregating existing MSP annotations")
        selected_nodes = assignments[selected_condition].merge(
            spectrum_nodes, on="node_id", how="left"
        )
        cluster_rows = []
        groups = list(selected_nodes.groupby("cluster_id", sort=False))
        for index, (cluster_id, members) in enumerate(groups, 1):
            cluster_rows.append(summarize_cluster(cluster_id, members))
            yield stages.update("annotation", index / len(groups),
                                f"MSP cluster annotations {index}/{len(groups)}")
        cluster_annotations = pd.DataFrame(cluster_rows)
        candidates = spectrum_nodes.rename(columns={"node_id": "spectrum_uid"}).copy()
        candidates["selected_for_kg"] = candidates["inchikey"].str.fullmatch(
            r"[A-Z]{14}-[A-Z]{10}-[A-Z]", na=False
        )
        candidates["annotation_source"] = "msp_metadata"
        candidates["name"] = candidates["compound_name"]
        candidates["score"] = 1.0
        yield stages.update("common", 0, "Analyzing common peaks in unannotated clusters")
        for completed, total, result in _annotate_unknown_clusters(
            assignments[selected_condition], spectra, spectrum_nodes,
            network_job, search_job_copy,
        ):
            yield stages.update("common", completed / max(1, total),
                                f"Common-peak clusters {completed}/{total}")
            if result is not None:
                fallback, common_peaks = result
        primary_candidates = candidates.copy()
        if not fallback.empty:
            candidates = pd.concat([candidates, fallback], ignore_index=True)
        yield stages.update("common", 1, "Common-peak analysis completed" if total else "Skipped: all clusters have structure information")
        evidence_parts = []
        query_parts = []
        keys = normalize_inchikey_values(
            candidates.loc[candidates["selected_for_kg"], "inchikey"].tolist()
        )
        yield stages.update("kg", 0, "Retrieving KG metadata")
        for start in range(0, len(keys), 50):
            evidence, queries = kg_lookup_service.search_evidence_by_inchikeys(
                keys[start:start + 50], limit=100, return_query=True,
                use_short_inchikey=False,
            )
            evidence_parts.append(evidence)
            query_parts.append(queries)
            yield stages.update("kg", min(start + 50, len(keys)) / len(keys),
                                f"KG keys {min(start + 50, len(keys))}/{len(keys)}")
        yield stages.update("kg", 1, "KG metadata completed" if keys else "Skipped: no InChIKeys")
        kg_evidence = _merge_kg_evidence(evidence_parts)
        kg_queries = _merge_kg_queries(
            query_parts
        )
        kg_feature_keys = {
            str(feature.get("inchikey")) for feature in kg_evidence.get("features", [])
            if isinstance(feature, dict) and any(
                records for providers in feature.get("entities", {}).values()
                if isinstance(providers, dict) for records in providers.values()
            )
        }
        for index, row in cluster_annotations.iterrows():
            cluster_id = row["cluster_id"]
            inferred_keys = set()
            if not fallback.empty:
                inferred_keys = set(fallback.loc[
                    (fallback["inferred_cluster_id"] == cluster_id) & fallback["selected_for_kg"],
                    "inchikey",
                ])
            direct_keys = set(json.loads(row["inchikey"]))
            cluster_annotations.loc[index, "common_peak_candidate_inchikeys"] = json.dumps(sorted(inferred_keys))
            cluster_annotations.loc[index, "kg_metadata_inchikeys"] = json.dumps(sorted(
                (direct_keys | inferred_keys) & kg_feature_keys
            ))
            cluster_annotations.loc[index, "metadata_status"] = (
                "kg_metadata_found" if (direct_keys | inferred_keys) & kg_feature_keys
                else "no_kg_metadata"
            )
        payload["summary"].update({
            "cluster_count": len(cluster_annotations),
            "structure_annotated_cluster_count": int((cluster_annotations["structure_annotated_member_count"] > 0).sum()),
            "common_peak_candidate_count": len(fallback),
            "unique_kg_inchikey_count": len(keys),
        })
        selected_nodes = assignments[selected_condition].merge(
            spectrum_nodes, on="node_id", how="left"
        )
        cytoscape_nodes, cytoscape_edges = build_cytoscape_tables(
            selected_nodes,
            filtered[selected_condition],
            candidates,
            kg_evidence,
        )
        yield stages.update("output", 0, "Writing cluster and network tables")
        output_dir = Path(tempfile.mkdtemp(prefix="massbank_rdf_network_")) / "result"
        output_dir.mkdir(parents=True, exist_ok=True)
        cluster_annotations.to_csv(output_dir / "cluster_annotations.tsv", sep="\t", index=False)
        primary_candidates.to_csv(output_dir / "msp_annotations.tsv", sep="\t", index=False)
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
            "node_id_scheme": "zero_based_all_records_upload_order",
            "primary_annotation_source": "msp_metadata",
            "common_peak_annotation_source": "massbank",
            "ion_mode_column": search_job_copy.get("ion_mode_column", "IONMODE"),
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
        (output_dir / "summary.json").write_text(
            json.dumps(payload["summary"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        archive = output_dir.with_suffix(".zip")
        archive.unlink(missing_ok=True)
        archive = Path(
            shutil.make_archive(
                str(archive.with_suffix("")), "zip", root_dir=output_dir
            )
        )
        payload.update(
            {
                "massbank_detail_df": pd.DataFrame(),
                "result_df": cluster_annotations,
                "cluster_annotations_df": cluster_annotations,
                "spectrum_annotation_df": primary_candidates,
                "kg_precomputed": True,
                "kg_inchikeys": keys,
                "output_directory": str(output_dir),
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
        yield stages.update("output", 1, f"Completed molecular network: {selected_condition}")

    return process
