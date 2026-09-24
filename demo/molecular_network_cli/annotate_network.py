#!/usr/bin/env python3
"""Stage 2: annotate a built network with MSP KG results and optional fallback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import pandas as pd
from tqdm import tqdm

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from demo.molecular_network_cli.build_cytoscape_network import (  # noqa: E402
    load_msp_kg_annotations,
)
from massbank_rdf.db.massbank.database import MassBankDatabase  # noqa: E402
from massbank_rdf.gui.settings import (  # noqa: E402
    create_kg_lookup_service_from_endpoint_settings,
)
from massbank_rdf.services.kg.candidate_ranking import (  # noqa: E402
    filter_similarity_candidates,
)
from massbank_rdf.services.kg.common import (  # noqa: E402
    normalize_inchikey_values,
)
from massbank_rdf.services.molecular_network import (  # noqa: E402
    build_cytoscape_tables,
    common_cluster_peaks,
)


REQUIRED_NETWORK_FILES = {
    "selected_condition_spectrum_nodes.tsv",
    "selected_condition_similarity_edges.tsv",
    "spectrum_peaks.tsv",
    "network_config.json",
}


def merge_evidence(parts: list[dict[str, Any]]) -> dict[str, Any]:
    features = []
    seen = set()
    metadata: dict[str, Any] = {}
    for part in parts:
        if not metadata and isinstance(part.get("metadata"), dict):
            metadata = dict(part["metadata"])
        for feature in part.get("features", []):
            if not isinstance(feature, dict):
                continue
            key = str(feature.get("inchikey", ""))
            if key and key not in seen:
                seen.add(key)
                features.append(feature)
    metadata["feature_count"] = len(features)
    return {"metadata": metadata, "features": features}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stage 2: add MassBank/KG metadata to a spectrum network."
        )
    )
    parser.add_argument("--network-dir", type=Path, required=True)
    parser.add_argument("--msp-kg-result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--annotate-unknown-clusters",
        action="store_true",
        help=(
            "Search common peaks of clusters with no saved MassBank annotation; "
            "precursor is ignored and ion mode is retained."
        ),
    )
    parser.add_argument("--common-presence-fraction", type=float, default=0.5)
    parser.add_argument("--common-relative-intensity", type=float, default=0.05)
    parser.add_argument("--common-peak-limit", type=int, default=100)
    parser.add_argument("--mz-tolerance", type=float)
    parser.add_argument("--massbank-top-n", type=int, default=10)
    parser.add_argument("--massbank-min-matched-peaks", type=int, default=1)
    parser.add_argument("--minimum-similarity", type=float, default=0.5)
    parser.add_argument("--max-inchikeys-per-cluster", type=int)
    parser.add_argument("--kg-timeout", type=float, default=600)
    return parser.parse_args()


def load_network(
    network_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, tuple[list[float], list[float]]], dict[str, Any]]:
    missing = [
        name for name in REQUIRED_NETWORK_FILES
        if not (network_dir / name).is_file()
    ]
    if missing:
        raise ValueError("Network directory is missing: " + ", ".join(missing))
    nodes = pd.read_csv(
        network_dir / "selected_condition_spectrum_nodes.tsv", sep="\t"
    )
    edges = pd.read_csv(
        network_dir / "selected_condition_similarity_edges.tsv", sep="\t"
    )
    peaks = pd.read_csv(network_dir / "spectrum_peaks.tsv", sep="\t")
    config = json.loads(
        (network_dir / "network_config.json").read_text(encoding="utf-8")
    )
    required_nodes = {"node_id", "cluster_id", "ion_mode", "source_file", "sample_class"}
    if not required_nodes.issubset(nodes):
        raise ValueError("Spectrum node table has an incompatible schema.")
    spectra = {
        str(node_id): (
            group.sort_values("peak_index")["mz"].astype(float).tolist(),
            group.sort_values("peak_index")["intensity"].astype(float).tolist(),
        )
        for node_id, group in peaks.groupby("node_id", sort=False)
    }
    return nodes, edges, spectra, config


def fallback_unknown_clusters(
    nodes: pd.DataFrame,
    spectra: dict[str, tuple[list[float], list[float]]],
    candidates: pd.DataFrame,
    *,
    mz_tolerance: float,
    presence_fraction: float,
    relative_intensity: float,
    common_peak_limit: int,
    top_n: int,
    min_matched_peaks: int,
    minimum_similarity: float,
    max_inchikeys: int | None,
    kg_timeout: float,
    progress_callback: Any | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, str]]:
    if candidates.empty:
        annotated_spectra: set[str] = set()
    elif "selected_for_kg" in candidates:
        selected = candidates["selected_for_kg"].apply(
            lambda value: value is True
            or str(value).strip().lower() in {"true", "1", "yes"}
        )
        annotated_spectra = set(
            candidates.loc[selected, "spectrum_uid"].astype(str)
        )
    else:
        annotated_spectra = set(candidates["spectrum_uid"].astype(str))
    node_info = nodes.set_index("node_id")
    db = MassBankDatabase()
    fallback_parts = []
    common_parts = []
    inchikeys = []
    cluster_groups = list(nodes.groupby("cluster_id", sort=False))
    for cluster_index, (cluster_id, cluster) in enumerate(
        cluster_groups, start=1
    ):
        members = cluster["node_id"].astype(str).tolist()
        if annotated_spectra.intersection(members):
            if progress_callback:
                progress_callback(
                    cluster_index, len(cluster_groups), cluster_id,
                    "already annotated",
                )
            continue
        common = common_cluster_peaks(
            spectra,
            members,
            mz_tolerance=mz_tolerance,
            minimum_presence_fraction=presence_fraction,
            minimum_relative_intensity=relative_intensity,
            max_peaks=common_peak_limit,
        )
        if common.empty:
            if progress_callback:
                progress_callback(
                    cluster_index, len(cluster_groups), cluster_id,
                    "no qualifying common peaks",
                )
            continue
        common.insert(0, "cluster_id", cluster_id)
        common_parts.append(common)
        modes = sorted(
            {
                str(node_info.at[member, "ion_mode"]).strip()
                for member in members
                if str(node_info.at[member, "ion_mode"]).strip()
            }
        )
        hits_by_mode = []
        for mode in modes:
            hit = db.search_record_ids_by_cosine_similarity_sql(
                common["mz"].tolist(),
                common["intensity"].tolist(),
                top_n=top_n,
                mz_tolerance=mz_tolerance,
                min_matched_peaks=min_matched_peaks,
                ion_mode=mode,
                precursor_mz=None,
                precursor_tolerance=None,
            )
            hit["fallback_ion_mode"] = mode
            hits_by_mode.append(hit)
        if not hits_by_mode:
            if progress_callback:
                progress_callback(
                    cluster_index, len(cluster_groups), cluster_id,
                    "ion mode unavailable",
                )
            continue
        raw = pd.concat(hits_by_mode, ignore_index=True)
        raw = filter_similarity_candidates(
            raw, minimum_similarity, score_column="cosine_score"
        ).sort_values("cosine_score", ascending=False, kind="stable")
        raw = raw.drop_duplicates("id").head(top_n)
        if raw.empty:
            if progress_callback:
                progress_callback(
                    cluster_index, len(cluster_groups), cluster_id,
                    "no MassBank hits",
                )
            continue
        records = db.get_records_by_ids_dataframe(raw["id"].astype(int).tolist())
        hits = raw.merge(records, on="id", how="left").drop(columns=["id"])
        hits = hits.rename(
            columns={
                "cosine_score": "score",
                "matched_peak_count": "match",
            }
        )
        keys = normalize_inchikey_values(
            hits.get("inchikey", pd.Series(dtype=str)).dropna().astype(str)
        )
        if max_inchikeys:
            keys = keys[:max_inchikeys]
        inchikeys.extend(keys)
        hits["selected_for_kg"] = hits["inchikey"].isin(keys)
        hits["annotation_source"] = "cluster_common_peak_massbank"
        hits["inferred_cluster_id"] = cluster_id
        for member in members:
            part = hits.copy()
            part["spectrum_uid"] = member
            part["source_file"] = node_info.at[member, "source_file"]
            part["sample_class"] = node_info.at[member, "sample_class"]
            fallback_parts.append(part)
        if progress_callback:
            progress_callback(
                cluster_index, len(cluster_groups), cluster_id,
                f"{len(common)} common peaks; {len(hits)} MassBank records",
            )
    fallback = (
        pd.concat(fallback_parts, ignore_index=True)
        if fallback_parts else pd.DataFrame()
    )
    common_frame = (
        pd.concat(common_parts, ignore_index=True)
        if common_parts else pd.DataFrame(
            columns=["cluster_id", "mz", "intensity", "presence_count", "presence_fraction"]
        )
    )
    unique_keys = normalize_inchikey_values(inchikeys)
    evidence_parts = []
    query_parts: list[dict[str, str]] = []
    if unique_keys:
        service = create_kg_lookup_service_from_endpoint_settings(
            timeout=kg_timeout
        )
        chunks = [
            unique_keys[start : start + 50]
            for start in range(0, len(unique_keys), 50)
        ]
        for chunk in tqdm(
            chunks,
            desc="[3/6] Fallback KG",
            unit="chunk",
            dynamic_ncols=True,
        ):
            evidence, queries = service.search_evidence_by_inchikeys(
                chunk,
                limit=100,
                return_query=True,
                use_short_inchikey=False,
            )
            evidence_parts.append(evidence)
            query_parts.append(queries)
    query_keys = ["pubchem_compound", "pubchem_pathway", "hmdb", "knapsack_activity"]
    merged_queries = {
        key: "\n\n".join(
            f"# Chunk {index}\n{part.get(key, '')}"
            for index, part in enumerate(query_parts, start=1)
        )
        for key in query_keys
    }
    return fallback, common_frame, merge_evidence(evidence_parts), merged_queries


def main() -> None:
    args = parse_args()
    network_dir = args.network_dir.resolve()
    print("[1/6] Reading the spectrum network and stored peaks...", file=sys.stderr)
    nodes, similarity_edges, spectra, network_config = load_network(network_dir)
    print(
        f"[1/6] Completed: {len(nodes):,} spectra, "
        f"{len(similarity_edges):,} similarity edges, "
        f"{nodes['cluster_id'].nunique():,} clusters.",
        file=sys.stderr,
    )
    file_classes = dict(
        nodes[["source_file", "sample_class"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    print("[2/6] Reading and validating the MSP KG result ZIP...", file=sys.stderr)
    candidates, saved_evidence = load_msp_kg_annotations(
        args.msp_kg_result.resolve(),
        set(nodes["node_id"].astype(str)),
        file_classes,
    )
    print(
        f"[2/6] Completed: {len(candidates):,} MassBank candidate rows, "
        f"{len(saved_evidence.get('features', [])):,} KG features.",
        file=sys.stderr,
    )
    fallback = pd.DataFrame(
        columns=[
            "spectrum_uid", "inferred_cluster_id", "annotation_source",
            "accession_id", "inchikey", "score", "match",
            "selected_for_kg", "fallback_ion_mode",
        ]
    )
    common_peaks = pd.DataFrame(
        columns=[
            "cluster_id", "mz", "intensity",
            "presence_count", "presence_fraction",
        ]
    )
    fallback_evidence: dict[str, Any] = {"metadata": {}, "features": []}
    fallback_queries: dict[str, str] = {}
    if args.annotate_unknown_clusters:
        print(
            "[3/6] Annotating unknown clusters from common peaks "
            "(precursor disabled, ion mode retained)...",
            file=sys.stderr,
        )
        tolerance = (
            args.mz_tolerance
            if args.mz_tolerance is not None
            else float(network_config.get("mz_tolerance", 0.01))
        )
        cluster_total = int(nodes["cluster_id"].nunique())
        with tqdm(
            total=cluster_total,
            desc="[3/6] Common-peak clusters",
            unit="cluster",
            dynamic_ncols=True,
        ) as bar:
            completed_clusters = 0

            def update_cluster(current, total, cluster, status):
                nonlocal completed_clusters
                bar.update(current - completed_clusters)
                completed_clusters = current
                bar.set_postfix(cluster=cluster, status=status)

            fallback, common_peaks, fallback_evidence, fallback_queries = (
                fallback_unknown_clusters(
                    nodes,
                    spectra,
                    candidates,
                    mz_tolerance=tolerance,
                    presence_fraction=args.common_presence_fraction,
                    relative_intensity=args.common_relative_intensity,
                    common_peak_limit=args.common_peak_limit,
                    top_n=args.massbank_top_n,
                    min_matched_peaks=args.massbank_min_matched_peaks,
                    minimum_similarity=args.minimum_similarity,
                    max_inchikeys=args.max_inchikeys_per_cluster,
                    kg_timeout=args.kg_timeout,
                    progress_callback=update_cluster,
                )
            )
        print(
            f"[3/6] Completed: {len(common_peaks):,} common peaks, "
            f"{len(fallback):,} propagated fallback candidate rows.",
            file=sys.stderr,
        )
        if not fallback.empty:
            candidates = pd.concat([candidates, fallback], ignore_index=True)
    else:
        print(
            "[3/6] Skipped common-peak fallback "
            "(--annotate-unknown-clusters was not specified).",
            file=sys.stderr,
        )
    print("[4/6] Merging saved and fallback KG evidence...", file=sys.stderr)
    evidence = merge_evidence([saved_evidence, fallback_evidence])
    print(
        f"[4/6] Completed: {len(evidence.get('features', [])):,} KG features.",
        file=sys.stderr,
    )
    print("[5/6] Building annotated Cytoscape node/edge tables...", file=sys.stderr)
    node_table, edge_table = build_cytoscape_tables(
        nodes, similarity_edges, candidates, evidence
    )
    print(
        f"[5/6] Completed: {len(node_table):,} nodes, "
        f"{len(edge_table):,} edges.",
        file=sys.stderr,
    )

    print("[6/6] Writing annotated network files...", file=sys.stderr)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "network_condition_statistics.csv",
        "network_cluster_assignments_all_conditions.csv",
        "selected_condition_spectrum_nodes.tsv",
        "selected_condition_similarity_edges.tsv",
        "spectrum_peaks.tsv",
        "network_config.json",
    ]:
        source = network_dir / name
        if source.is_file():
            shutil.copy2(source, output_dir / name)
    node_table.to_csv(output_dir / "node.tsv", sep="\t", index=False)
    edge_table.to_csv(output_dir / "edge.tsv", sep="\t", index=False)
    candidates.to_csv(
        output_dir / "annotated_massbank_candidates.tsv", sep="\t", index=False
    )
    common_peaks.to_csv(
        output_dir / "unannotated_cluster_common_peaks.tsv",
        sep="\t", index=False,
    )
    fallback.to_csv(
        output_dir / "unannotated_cluster_massbank_candidates.tsv",
        sep="\t", index=False,
    )
    (output_dir / "kg_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    query_dir = output_dir / "fallback_sparql"
    query_dir.mkdir(exist_ok=True)
    for name, query in fallback_queries.items():
        (query_dir / f"{name}.sparql").write_text(query, encoding="utf-8")
    annotation_config = {
        "schema_version": 1,
        "stage": "metadata_annotation",
        "source_network_dir": str(network_dir),
        "msp_kg_result": str(args.msp_kg_result.resolve()),
        "annotate_unknown_clusters": args.annotate_unknown_clusters,
        "fallback_candidate_count": len(fallback),
    }
    (output_dir / "annotation_config.json").write_text(
        json.dumps(annotation_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[6/6] All output files written.", file=sys.stderr)
    print(f"Annotated Cytoscape network: {output_dir}")
    print(f"Nodes: {len(node_table):,}; edges: {len(edge_table):,}")


if __name__ == "__main__":
    main()
