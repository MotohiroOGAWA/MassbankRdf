from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import sparse


EDGE_COLUMNS = ("SourceID", "TargetID", "Score", "MatchPeakCount")


@dataclass(frozen=True)
class NetworkCondition:
    score_threshold: float
    score_label: str
    top_k: int | None
    match_peak_count: int
    resolution: float
    random_seed: int = 42

    @property
    def condition_id(self) -> str:
        top = "all" if self.top_k is None else str(self.top_k)
        score = self.score_label.replace(".", "_")
        return (
            f"match{self.match_peak_count}_score{score}_top{top}_"
            f"res{self.resolution:g}"
        )


def _exact_spectrum_cosine(
    first: tuple[Iterable[float], Iterable[float]],
    second: tuple[Iterable[float], Iterable[float]],
    mz_tolerance: float,
) -> tuple[float, int]:
    """Calculate one-to-one tolerance-matched cosine and matched-peak count."""
    first_mz = np.asarray(list(first[0]), dtype=float)
    first_intensity = np.asarray(list(first[1]), dtype=float)
    second_mz = np.asarray(list(second[0]), dtype=float)
    second_intensity = np.asarray(list(second[1]), dtype=float)
    first_order = np.argsort(first_mz, kind="stable")
    second_order = np.argsort(second_mz, kind="stable")
    first_mz = first_mz[first_order]
    first_intensity = first_intensity[first_order]
    second_mz = second_mz[second_order]
    second_intensity = second_intensity[second_order]
    norm = float(np.linalg.norm(first_intensity) * np.linalg.norm(second_intensity))
    if not len(first_mz) or not len(second_mz) or norm <= 0:
        return 0.0, 0
    candidates: list[tuple[float, int, int]] = []
    right_start = 0
    for left_index, mz in enumerate(first_mz):
        while (
            right_start < len(second_mz)
            and second_mz[right_start] < mz - mz_tolerance
        ):
            right_start += 1
        right_index = right_start
        while (
            right_index < len(second_mz)
            and second_mz[right_index] <= mz + mz_tolerance
        ):
            candidates.append(
                (abs(float(mz - second_mz[right_index])), left_index, right_index)
            )
            right_index += 1
    used_left: set[int] = set()
    used_right: set[int] = set()
    dot_product = 0.0
    for _, left_index, right_index in sorted(candidates):
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        dot_product += float(
            first_intensity[left_index] * second_intensity[right_index]
        )
    return dot_product / norm, len(used_left)


def generate_similarity_edges(
    spectra: dict[str, tuple[Iterable[float], Iterable[float]]],
    ion_modes: dict[str, str],
    *,
    mz_tolerance: float,
    minimum_matched_peaks: int,
    batch_size: int = 250,
):
    """Yield progress while generating sparse-candidate, exact cosine edges.

    Yields `(processed_nodes, total_nodes, edge_count, result)`; `result` is
    only populated in the final yield.
    """
    if mz_tolerance <= 0:
        raise ValueError("m/z tolerance must be greater than zero.")
    if minimum_matched_peaks < 1:
        raise ValueError("Minimum matched peaks must be at least one.")
    grouped: dict[str, list[str]] = {}
    for node_id in spectra:
        ion_mode = str(ion_modes.get(node_id, "")).strip()
        if ion_mode:
            grouped.setdefault(ion_mode, []).append(node_id)
    total_nodes = sum(len(values) for values in grouped.values())
    processed_nodes = 0
    rows: list[dict[str, Any]] = []
    for ion_mode, node_ids in grouped.items():
        if len(node_ids) < 2:
            processed_nodes += len(node_ids)
            yield processed_nodes, total_nodes, len(rows), None
            continue
        all_mz = [
            np.asarray(list(spectra[node_id][0]), dtype=float)
            for node_id in node_ids
        ]
        maximum_bin = max(
            (int(np.floor(mz.max() / mz_tolerance)) for mz in all_mz if len(mz)),
            default=0,
        )
        matrix_rows: list[int] = []
        matrix_columns: list[int] = []
        for row_index, mz_values in enumerate(all_mz):
            bins = np.floor(mz_values / mz_tolerance).astype(np.int64)
            expanded = np.unique(
                np.concatenate([bins - 1, bins, bins + 1])
            )
            expanded = expanded[expanded >= 0]
            matrix_rows.extend([row_index] * len(expanded))
            matrix_columns.extend(expanded.tolist())
        incidence = sparse.csr_matrix(
            (
                np.ones(len(matrix_rows), dtype=np.int32),
                (matrix_rows, matrix_columns),
            ),
            shape=(len(node_ids), maximum_bin + 2),
        )
        incidence.data[:] = 1
        for start in range(0, len(node_ids), int(batch_size)):
            stop = min(start + int(batch_size), len(node_ids))
            overlap = (incidence[start:stop] @ incidence.T).tocoo()
            candidate_pairs = sorted(
                {
                    (start + int(local), int(target))
                    for local, target, count in zip(
                        overlap.row, overlap.col, overlap.data
                    )
                    if start + int(local) < int(target)
                    and int(count) >= int(minimum_matched_peaks)
                }
            )
            for left_index, right_index in candidate_pairs:
                score, matched = _exact_spectrum_cosine(
                    spectra[node_ids[left_index]],
                    spectra[node_ids[right_index]],
                    float(mz_tolerance),
                )
                if matched >= int(minimum_matched_peaks):
                    rows.append(
                        {
                            "SourceID": node_ids[left_index],
                            "TargetID": node_ids[right_index],
                            "Score": score,
                            "MatchPeakCount": matched,
                            "IonMode": ion_mode,
                        }
                    )
            processed_nodes += stop - start
            yield processed_nodes, total_nodes, len(rows), None
    result = pd.DataFrame(
        rows,
        columns=[*EDGE_COLUMNS, "IonMode"],
    )
    yield processed_nodes, total_nodes, len(result), result


def read_similarity_edges(path: str | Path) -> pd.DataFrame:
    """Read and validate a tab- or comma-separated similarity edge table."""
    path = Path(path)
    separator = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    frame = pd.read_csv(path, sep=separator)
    missing = [column for column in EDGE_COLUMNS if column not in frame]
    if missing:
        raise ValueError(
            "Similarity edge table is missing required columns: "
            + ", ".join(missing)
        )
    result = frame.loc[:, EDGE_COLUMNS].copy()
    result["SourceID"] = result["SourceID"].astype(str).str.strip()
    result["TargetID"] = result["TargetID"].astype(str).str.strip()
    result["Score"] = pd.to_numeric(result["Score"], errors="coerce")
    result["MatchPeakCount"] = pd.to_numeric(
        result["MatchPeakCount"], errors="coerce"
    )
    result = result.dropna(subset=["Score", "MatchPeakCount"])
    result = result[
        (result["SourceID"] != "")
        & (result["TargetID"] != "")
        & (result["SourceID"] != result["TargetID"])
    ].copy()
    return deduplicate_edges(result)


def deduplicate_edges(edges: pd.DataFrame) -> pd.DataFrame:
    """Remove self-loops and collapse undirected duplicates to their best row."""
    if edges.empty:
        return pd.DataFrame(columns=EDGE_COLUMNS)
    result = edges.copy()
    left = result[["SourceID", "TargetID"]].min(axis=1)
    right = result[["SourceID", "TargetID"]].max(axis=1)
    result["SourceID"] = left
    result["TargetID"] = right
    result = result[result["SourceID"] != result["TargetID"]]
    return (
        result.sort_values(
            ["Score", "MatchPeakCount"], ascending=[False, False], kind="stable"
        )
        .drop_duplicates(["SourceID", "TargetID"], keep="first")
        .loc[:, EDGE_COLUMNS]
        .reset_index(drop=True)
    )


def resolve_score_thresholds(
    edges: pd.DataFrame,
    specifications: Iterable[str | float | int],
) -> list[tuple[float, str]]:
    """Resolve fixed scores and p95-style percentile specifications."""
    scores = pd.to_numeric(edges["Score"], errors="coerce").dropna()
    if scores.empty:
        raise ValueError("No numeric Score values were found.")
    resolved: list[tuple[float, str]] = []
    for value in specifications:
        text = str(value).strip().lower()
        if not text:
            continue
        if text.startswith("p"):
            percentile = float(text[1:])
            if not 0 <= percentile <= 100:
                raise ValueError(f"Invalid Score percentile: {value}")
            threshold = float(np.percentile(scores.to_numpy(), percentile))
            label = f"p{percentile:g}"
        else:
            threshold = float(text)
            label = f"{threshold:g}"
        if not any(math.isclose(threshold, item[0]) and label == item[1] for item in resolved):
            resolved.append((threshold, label))
    if not resolved:
        raise ValueError("At least one Score threshold is required.")
    return resolved


def filter_edges(
    edges: pd.DataFrame,
    *,
    score_threshold: float,
    match_peak_count: int,
    top_k: int | None,
) -> pd.DataFrame:
    """Apply confidence filters and union-of-per-node top-k pruning."""
    result = edges[
        (edges["MatchPeakCount"] >= int(match_peak_count))
        & (edges["Score"] >= float(score_threshold))
    ].copy()
    result = deduplicate_edges(result)
    if result.empty or top_k is None:
        return result
    if int(top_k) < 1:
        raise ValueError("top_k must be at least 1 or blank.")
    directed = pd.concat(
        [
            result.assign(_node=result["SourceID"]),
            result.assign(_node=result["TargetID"]),
        ],
        ignore_index=True,
    )
    selected = (
        directed.sort_values(
            ["_node", "Score", "MatchPeakCount"],
            ascending=[True, False, False],
            kind="stable",
        )
        .groupby("_node", sort=False)
        .head(int(top_k))[["SourceID", "TargetID"]]
        .drop_duplicates()
    )
    return result.merge(selected, on=["SourceID", "TargetID"], how="inner")


def _require_leiden():
    try:
        import igraph as ig
        import leidenalg
    except ImportError as exc:
        raise RuntimeError(
            "Weighted Leiden clustering requires python-igraph and leidenalg. "
            "Install the application requirements and restart the server."
        ) from exc
    return ig, leidenalg


def cluster_network(
    all_node_ids: Iterable[str],
    edges: pd.DataFrame,
    *,
    resolution: float,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, float]:
    """Split into components and run weighted Leiden within every component."""
    ig, leidenalg = _require_leiden()
    nodes = list(dict.fromkeys(str(node) for node in all_node_ids))
    edge_nodes = pd.unique(edges[["SourceID", "TargetID"]].to_numpy().ravel())
    for node in map(str, edge_nodes):
        if node not in nodes:
            nodes.append(node)
    index = {node: position for position, node in enumerate(nodes)}
    graph = ig.Graph(
        n=len(nodes),
        edges=[
            (index[str(row.SourceID)], index[str(row.TargetID)])
            for row in edges.itertuples(index=False)
        ],
        directed=False,
    )
    graph.vs["name"] = nodes
    weights = edges["Score"].astype(float).tolist()
    graph.es["weight"] = weights
    components = graph.connected_components(mode="weak")
    memberships = [-1] * len(nodes)
    component_ids = [-1] * len(nodes)
    component_sizes = [0] * len(nodes)
    next_cluster = 0
    for component_number, vertex_ids in enumerate(components, start=1):
        vertex_ids = list(vertex_ids)
        for vertex in vertex_ids:
            component_ids[vertex] = component_number
            component_sizes[vertex] = len(vertex_ids)
        if len(vertex_ids) == 1:
            memberships[vertex_ids[0]] = next_cluster
            next_cluster += 1
            continue
        subgraph = graph.subgraph(vertex_ids)
        partition = leidenalg.find_partition(
            subgraph,
            leidenalg.RBConfigurationVertexPartition,
            weights=subgraph.es["weight"],
            resolution_parameter=float(resolution),
            seed=int(random_seed),
        )
        for local_vertex, local_cluster in enumerate(partition.membership):
            memberships[vertex_ids[local_vertex]] = next_cluster + local_cluster
        next_cluster += len(set(partition.membership))
    modularity = (
        float(graph.modularity(memberships, weights=weights))
        if graph.ecount() and len(set(memberships)) > 1
        else 0.0
    )
    node_frame = pd.DataFrame(
        {
            "node_id": nodes,
            "cluster_id": [f"C{value + 1}" for value in memberships],
            "connected_component_id": [
                f"CC{value}" for value in component_ids
            ],
            "component_node_count": component_sizes,
        }
    )
    return node_frame, modularity


def analyze_conditions(
    edges: pd.DataFrame,
    all_node_ids: Iterable[str],
    *,
    score_thresholds: Iterable[str | float | int],
    top_k_values: Iterable[int | None],
    match_peak_counts: Iterable[int],
    resolutions: Iterable[float],
    random_seed: int = 42,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Evaluate a full parameter grid and return statistics and assignments."""
    nodes = list(dict.fromkeys(map(str, all_node_ids)))
    resolved_scores = resolve_score_thresholds(edges, score_thresholds)
    stats: list[dict[str, Any]] = []
    assignments: dict[str, pd.DataFrame] = {}
    filtered_edges: dict[str, pd.DataFrame] = {}
    for (threshold, score_label), top_k, match_count, resolution in product(
        resolved_scores, top_k_values, match_peak_counts, resolutions
    ):
        condition = NetworkCondition(
            threshold, score_label, top_k, int(match_count), float(resolution),
            int(random_seed),
        )
        selected = filter_edges(
            edges,
            score_threshold=threshold,
            match_peak_count=match_count,
            top_k=top_k,
        )
        node_frame, modularity = cluster_network(
            nodes, selected, resolution=resolution, random_seed=random_seed
        )
        sizes = node_frame.groupby("cluster_id").size().to_numpy()
        component_sizes = (
            node_frame.groupby("connected_component_id").size().to_numpy()
        )
        degree_nodes = set(selected["SourceID"]) | set(selected["TargetID"])
        largest = int(component_sizes.max()) if len(component_sizes) else 0
        stats.append(
            {
                "condition_id": condition.condition_id,
                "score_threshold_specification": score_label,
                "score_threshold_resolved": threshold,
                "top_k": top_k if top_k is not None else "all",
                "match_peak_count_threshold": int(match_count),
                "leiden_resolution": float(resolution),
                "random_seed": int(random_seed),
                "node_count": len(node_frame),
                "edge_count": len(selected),
                "isolated_node_count": len(node_frame) - len(degree_nodes),
                "connected_component_count": len(component_sizes),
                "cluster_count": len(sizes),
                "largest_component_node_count": largest,
                "largest_component_fraction": (
                    largest / len(node_frame) if len(node_frame) else 0.0
                ),
                "cluster_size_min": int(sizes.min()) if len(sizes) else 0,
                "cluster_size_median": float(np.median(sizes)) if len(sizes) else 0,
                "cluster_size_mean": float(np.mean(sizes)) if len(sizes) else 0,
                "cluster_size_max": int(sizes.max()) if len(sizes) else 0,
                "modularity": modularity,
            }
        )
        node_frame.insert(0, "condition_id", condition.condition_id)
        assignments[condition.condition_id] = node_frame
        filtered_edges[condition.condition_id] = selected
    return pd.DataFrame(stats), assignments, filtered_edges


def common_cluster_peaks(
    spectra: dict[str, tuple[Iterable[float], Iterable[float]]],
    node_ids: Iterable[str],
    *,
    mz_tolerance: float = 0.01,
    minimum_presence_fraction: float = 0.5,
    minimum_relative_intensity: float = 0.05,
    max_peaks: int = 100,
) -> pd.DataFrame:
    """Find frequent, sufficiently intense peaks in an unannotated cluster."""
    selected = [spectra[node] for node in node_ids if node in spectra]
    if not selected:
        return pd.DataFrame(columns=["mz", "intensity", "presence_count", "presence_fraction"])
    observations: list[tuple[float, float, int]] = []
    for spectrum_index, (mz_values, intensity_values) in enumerate(selected):
        mz = np.asarray(list(mz_values), dtype=float)
        intensity = np.asarray(list(intensity_values), dtype=float)
        maximum = float(intensity.max()) if len(intensity) else 0.0
        if maximum <= 0:
            continue
        relative = intensity / maximum
        for peak_mz, peak_intensity in zip(mz, relative):
            if peak_intensity >= float(minimum_relative_intensity):
                observations.append((float(peak_mz), float(peak_intensity), spectrum_index))
    observations.sort()
    groups: list[list[tuple[float, float, int]]] = []
    for observation in observations:
        if not groups or observation[0] - groups[-1][-1][0] > float(mz_tolerance):
            groups.append([observation])
        else:
            groups[-1].append(observation)
    rows = []
    for group in groups:
        best_by_spectrum: dict[int, tuple[float, float]] = {}
        for mz, intensity, spectrum_index in group:
            current = best_by_spectrum.get(spectrum_index)
            if current is None or intensity > current[1]:
                best_by_spectrum[spectrum_index] = (mz, intensity)
        presence = len(best_by_spectrum)
        fraction = presence / len(selected)
        if fraction < float(minimum_presence_fraction):
            continue
        weights = np.asarray([value[1] for value in best_by_spectrum.values()])
        mzs = np.asarray([value[0] for value in best_by_spectrum.values()])
        rows.append(
            {
                "mz": float(np.average(mzs, weights=weights)),
                "intensity": float(weights.mean() * fraction),
                "presence_count": presence,
                "presence_fraction": fraction,
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["presence_fraction", "intensity"], ascending=False)
        .head(int(max_peaks))
        .sort_values("mz")
        .reset_index(drop=True)
        if rows
        else pd.DataFrame(columns=["mz", "intensity", "presence_count", "presence_fraction"])
    )


def build_cytoscape_tables(
    spectrum_nodes: pd.DataFrame,
    similarity_edges: pd.DataFrame,
    candidates: pd.DataFrame,
    kg_evidence: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create Cytoscape tables containing spectra, compounds, and KG entities."""
    node_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    def present(value: Any, default: Any = "") -> Any:
        try:
            return default if value is None or bool(pd.isna(value)) else value
        except (TypeError, ValueError):
            return value

    def add_node(node_id: str, node_type: str, label: str, **attributes: Any) -> None:
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        node_rows.append(
            {"node_id": node_id, "node_type": node_type, "label": label, **attributes}
        )

    def add_edge(
        source: str, target: str, edge_type: str, weight: float = 1.0, **attributes: Any
    ) -> None:
        key = (source, target, edge_type)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edge_rows.append(
            {
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "weight": weight,
                **attributes,
            }
        )

    for row in spectrum_nodes.itertuples(index=False):
        values = row._asdict()
        raw_id = str(values.pop("node_id"))
        add_node(f"spectrum:{raw_id}", "spectrum", raw_id, **values)
    for row in similarity_edges.itertuples(index=False):
        add_edge(
            f"spectrum:{row.SourceID}",
            f"spectrum:{row.TargetID}",
            "spectrum_similarity",
            float(row.Score),
            match_peak_count=int(row.MatchPeakCount),
        )

    spectrum_cluster = {
        str(row.node_id): str(getattr(row, "cluster_id", ""))
        for row in spectrum_nodes.itertuples(index=False)
    }
    inchikey_clusters: dict[str, set[str]] = {}
    selected = candidates.copy()
    if "selected_for_kg" in selected:
        selected = selected[selected["selected_for_kg"].fillna(False)]
    if not selected.empty and {"spectrum_uid", "inchikey"}.issubset(selected):
        for row in selected.dropna(subset=["inchikey"]).itertuples(index=False):
            values = row._asdict()
            spectrum_id = str(values["spectrum_uid"])
            inchikey = str(values["inchikey"])
            compound_id = f"inchikey:{inchikey}"
            add_node(compound_id, "inchikey", inchikey)
            cluster_id = spectrum_cluster.get(spectrum_id, "")
            inchikey_clusters.setdefault(inchikey, set()).add(cluster_id)
            add_edge(
                f"spectrum:{spectrum_id}",
                compound_id,
                str(present(values.get("annotation_source"), "massbank_annotation")),
                float(present(values.get("score"), 0.0)),
                accession_id=str(present(values.get("accession_id"), "")),
            )

    feature_by_key = {
        str(feature.get("inchikey")): feature
        for feature in kg_evidence.get("features", [])
        if isinstance(feature, dict) and feature.get("inchikey")
    }
    for inchikey, feature in feature_by_key.items():
        compound_id = f"inchikey:{inchikey}"
        if compound_id not in seen_nodes:
            continue
        entities = feature.get("entities", {})
        if not isinstance(entities, dict):
            continue
        for cluster_id in sorted(inchikey_clusters.get(inchikey, {""})):
            cluster_token = cluster_id or "unclustered"
            for entity_type, providers in entities.items():
                if not isinstance(providers, dict):
                    continue
                for provider, records in providers.items():
                    if not isinstance(records, list):
                        continue
                    for position, entity in enumerate(records, start=1):
                        if not isinstance(entity, dict):
                            continue
                        raw_id = (
                            entity.get("id")
                            or entity.get("accession")
                            or entity.get("label")
                            or entity.get("name")
                            or f"{provider}-{position}"
                        )
                        label = (
                            entity.get("label")
                            or entity.get("name")
                            or entity.get("accession")
                            or raw_id
                        )
                        entity_id = (
                            f"metadata:{cluster_token}:{entity_type}:"
                            f"{provider}:{raw_id}"
                        )
                        add_node(
                            entity_id,
                            str(entity_type),
                            str(label),
                            provider=str(provider),
                            cluster_id=cluster_id,
                        )
                        add_edge(
                            compound_id,
                            entity_id,
                            "kg_metadata",
                            1.0,
                            cluster_id=cluster_id,
                        )
    return pd.DataFrame(node_rows), pd.DataFrame(edge_rows)
