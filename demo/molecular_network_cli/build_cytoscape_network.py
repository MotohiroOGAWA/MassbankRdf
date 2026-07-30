#!/usr/bin/env python3
"""Build Cytoscape molecular-network tables from MSP files."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
from typing import Any
import zipfile

import pandas as pd

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from massbank_rdf.models import MSPRecord
from massbank_rdf.services.molecular_network import (
    NetworkCondition,
    analyze_conditions,
    build_cytoscape_tables,
    generate_similarity_edges,
    read_similarity_edges,
    resolve_score_thresholds,
)


def split_msp_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        if current and raw_line.strip().lower().startswith("name:"):
            blocks.append("\n".join(current).strip())
            current = []
        if raw_line.strip() or current:
            current.append(raw_line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def normalize_ion_mode(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in {"POSITIVE", "POS", "+"}:
        return "POSITIVE"
    if normalized in {"NEGATIVE", "NEG", "-"}:
        return "NEGATIVE"
    return normalized


def parse_assignments(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"Invalid --sample-class value: {value}")
        file_name, sample_class = value.split("=", 1)
        if not file_name.strip() or not sample_class.strip():
            raise ValueError(f"Invalid --sample-class value: {value}")
        result[Path(file_name.strip()).name] = sample_class.strip()
    return result


def load_msp_files(
    paths: list[Path],
    *,
    ion_mode_column: str,
    class_assignments: dict[str, str],
) -> tuple[
    pd.DataFrame,
    dict[str, tuple[list[float], list[float]]],
    dict[str, str],
]:
    rows: list[dict[str, Any]] = []
    spectra: dict[str, tuple[list[float], list[float]]] = {}
    aliases: dict[str, list[str]] = {}
    seen_names: set[str] = set()
    for file_number, path in enumerate(paths, start=1):
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.name in seen_names:
            raise ValueError(f"MSP file names must be unique: {path.name}")
        seen_names.add(path.name)
        sample_class = class_assignments.get(path.name, f"Class{file_number}")
        readable_index = 0
        for block in split_msp_blocks(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            try:
                record = MSPRecord.from_msp_text(block)
            except ValueError:
                continue
            readable_index += 1
            node_id = f"{path.name}::{readable_index}"
            name = record.get_metadata_value("Name") or ""
            ion_mode = normalize_ion_mode(
                record.get_metadata_value(ion_mode_column)
            )
            if not ion_mode:
                raise ValueError(
                    f"{node_id} has no usable {ion_mode_column} ion mode."
                )
            rows.append(
                {
                    "node_id": node_id,
                    "source_file": path.name,
                    "sample_class": sample_class,
                    "msp_record_index": readable_index,
                    "msp_name": name,
                    "peak_count": len(record.mz_list),
                    "ion_mode": ion_mode,
                }
            )
            spectra[node_id] = (
                list(map(float, record.mz_list)),
                list(map(float, record.intensity_list)),
            )
            if name:
                aliases.setdefault(str(name), []).append(node_id)
    if not rows:
        raise ValueError("No readable MSP spectra were found.")
    alias_map = {node_id: node_id for node_id in spectra}
    alias_map.update(
        {name: ids[0] for name, ids in aliases.items() if len(ids) == 1}
    )
    return pd.DataFrame(rows), spectra, alias_map


def remap_uploaded_edges(
    edges: pd.DataFrame,
    aliases: dict[str, str],
) -> pd.DataFrame:
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
        raise ValueError(
            f"{len(unknown)} edge node IDs do not match MSP spectra: "
            + ", ".join(sorted(unknown)[:10])
        )
    return result


def _zip_member_by_name(
    archive: zipfile.ZipFile,
    name: str,
) -> zipfile.ZipInfo:
    matches = [
        member for member in archive.infolist()
        if Path(member.filename).name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Result ZIP must contain exactly one {name}.")
    return matches[0]


def load_msp_kg_annotations(
    archive_path: Path,
    expected_spectrum_ids: set[str],
    sample_classes: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    with zipfile.ZipFile(archive_path) as archive:
        candidate_member = _zip_member_by_name(
            archive, "massbank_candidates_by_spectrum.csv"
        )
        annotation_member = _zip_member_by_name(
            archive, "spectrum_inchikey_annotations.csv"
        )
        evidence_member = _zip_member_by_name(archive, "kg_evidence.json")
        try:
            candidates = pd.read_csv(
                io.BytesIO(archive.read(candidate_member))
            )
        except pd.errors.EmptyDataError:
            candidates = pd.DataFrame()
        annotations = pd.read_csv(io.BytesIO(archive.read(annotation_member)))
        evidence = json.loads(archive.read(evidence_member).decode("utf-8"))
    archived_ids = set(annotations["spectrum_uid"].dropna().astype(str))
    if archived_ids != expected_spectrum_ids:
        raise ValueError(
            "MSP KG ZIP spectrum IDs do not match the MSP input "
            f"(missing={len(expected_spectrum_ids - archived_ids)}, "
            f"unexpected={len(archived_ids - expected_spectrum_ids)})."
        )
    if not candidates.empty:
        required = {"spectrum_uid", "inchikey"}
        if not required.issubset(candidates):
            raise ValueError("MassBank candidate table has an incompatible schema.")
        source_to_class = sample_classes
        if "source_file" in candidates:
            candidates["sample_class"] = (
                candidates["source_file"].astype(str).map(source_to_class)
                .fillna(candidates.get("sample_class", ""))
            )
    if not isinstance(evidence, dict) or not isinstance(
        evidence.get("features", []), list
    ):
        raise ValueError("kg_evidence.json has an incompatible schema.")
    return candidates, evidence


def comma_values(text: str, cast, *, allow_all: bool = False) -> list[Any]:
    result: list[Any] = []
    for raw in text.split(","):
        value = raw.strip()
        if not value:
            continue
        result.append(
            None if allow_all and value.lower() in {"all", "none"} else cast(value)
        )
    if not result:
        raise ValueError("A parameter list must not be empty.")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build weighted-Leiden molecular-network and Cytoscape TSV files "
            "from one or more MSP files."
        )
    )
    parser.add_argument("msp_files", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--edge-table", type=Path)
    parser.add_argument("--msp-kg-result", type=Path)
    parser.add_argument(
        "--sample-class", action="append",
        help="file_name.msp=ClassName; repeat for multiple files.",
    )
    parser.add_argument("--ion-mode-column", default="IONMODE")
    parser.add_argument("--mz-tolerance", type=float, default=0.01)
    parser.add_argument("--score-thresholds", default="p95,p97,p98,p99")
    parser.add_argument("--match-peak-counts", default="6")
    parser.add_argument("--top-k-values", default="5,10,15,20")
    parser.add_argument("--resolutions", default="0.5,1.0,1.5,2.0")
    parser.add_argument("--selected-score", default="p95")
    parser.add_argument("--selected-match-peak-count", type=int, default=6)
    parser.add_argument("--selected-top-k", default="10")
    parser.add_argument("--selected-resolution", type=float, default=1.0)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--edge-batch-size", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    classes = parse_assignments(args.sample_class)
    spectrum_nodes, spectra, aliases = load_msp_files(
        args.msp_files,
        ion_mode_column=args.ion_mode_column,
        class_assignments=classes,
    )
    file_classes = dict(
        spectrum_nodes[["source_file", "sample_class"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    match_counts = comma_values(args.match_peak_counts, int)
    if args.edge_table:
        edges = remap_uploaded_edges(
            read_similarity_edges(args.edge_table), aliases
        )
        edge_source = "uploaded"
    else:
        print(
            "Generating spectrum-similarity edges...",
            file=sys.stderr,
        )
        edges = None
        ion_modes = spectrum_nodes.set_index("node_id")["ion_mode"].to_dict()
        for processed, total, count, result in generate_similarity_edges(
            spectra,
            ion_modes,
            mz_tolerance=args.mz_tolerance,
            minimum_matched_peaks=min(match_counts),
            batch_size=args.edge_batch_size,
        ):
            print(
                f"\rEdges: {processed:,}/{total:,} spectra; {count:,} edges",
                end="",
                file=sys.stderr,
                flush=True,
            )
            if result is not None:
                edges = result
        print(file=sys.stderr)
        if edges is None or edges.empty:
            raise ValueError("No spectrum-similarity edges passed the match threshold.")
        edge_source = "generated"

    score_specs = comma_values(args.score_thresholds, str)
    top_values = comma_values(args.top_k_values, int, allow_all=True)
    resolutions = comma_values(args.resolutions, float)
    print(
        f"Evaluating {len(score_specs) * len(match_counts) * len(top_values) * len(resolutions):,} "
        "network conditions...",
        file=sys.stderr,
    )
    statistics, assignments, filtered = analyze_conditions(
        edges,
        spectrum_nodes["node_id"],
        score_thresholds=score_specs,
        top_k_values=top_values,
        match_peak_counts=match_counts,
        resolutions=resolutions,
        random_seed=args.random_seed,
    )
    selected_threshold, selected_label = resolve_score_thresholds(
        edges, [args.selected_score]
    )[0]
    selected_top = comma_values(args.selected_top_k, int, allow_all=True)[0]
    selected = NetworkCondition(
        selected_threshold,
        selected_label,
        selected_top,
        args.selected_match_peak_count,
        args.selected_resolution,
        args.random_seed,
    ).condition_id
    if selected not in assignments:
        raise ValueError(
            "Selected condition is not present in the condition grid: " + selected
        )

    candidates = pd.DataFrame()
    evidence: dict[str, Any] = {"metadata": {}, "features": []}
    if args.msp_kg_result:
        candidates, evidence = load_msp_kg_annotations(
            args.msp_kg_result.resolve(),
            set(spectrum_nodes["node_id"]),
            file_classes,
        )
    selected_nodes = assignments[selected].merge(
        spectrum_nodes, on="node_id", how="left"
    )
    cytoscape_nodes, cytoscape_edges = build_cytoscape_tables(
        selected_nodes,
        filtered[selected],
        candidates,
        evidence,
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cytoscape_nodes.to_csv(output_dir / "node.tsv", sep="\t", index=False)
    cytoscape_edges.to_csv(output_dir / "edge.tsv", sep="\t", index=False)
    statistics.to_csv(
        output_dir / "network_condition_statistics.csv", index=False
    )
    pd.concat(assignments.values(), ignore_index=True).to_csv(
        output_dir / "network_cluster_assignments_all_conditions.csv",
        index=False,
    )
    selected_nodes.to_csv(
        output_dir / "selected_condition_spectrum_nodes.tsv",
        sep="\t", index=False,
    )
    filtered[selected].to_csv(
        output_dir / "selected_condition_similarity_edges.tsv",
        sep="\t", index=False,
    )
    edges.to_csv(
        output_dir / f"{edge_source}_similarity_edges.tsv",
        sep="\t", index=False,
    )
    configuration = {
        "msp_files": [str(path.resolve()) for path in args.msp_files],
        "edge_source": edge_source,
        "msp_kg_result": (
            str(args.msp_kg_result.resolve()) if args.msp_kg_result else None
        ),
        "score_thresholds": score_specs,
        "match_peak_counts": match_counts,
        "top_k_values": top_values,
        "resolutions": resolutions,
        "selected_condition_id": selected,
        "mz_tolerance": args.mz_tolerance,
        "random_seed": args.random_seed,
    }
    (output_dir / "network_config.json").write_text(
        json.dumps(configuration, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Cytoscape nodes: {output_dir / 'node.tsv'}")
    print(f"Cytoscape edges: {output_dir / 'edge.tsv'}")
    print(f"Selected condition: {selected}")


if __name__ == "__main__":
    main()
