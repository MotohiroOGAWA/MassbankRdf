#!/usr/bin/env python3
"""Stage 1: build a spectrum-only Cytoscape molecular network."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import pandas as pd
from tqdm import tqdm

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from demo.molecular_network_cli.build_cytoscape_network import (  # noqa: E402
    comma_values,
    load_msp_files,
    parse_assignments,
    remap_uploaded_edges,
)
from massbank_rdf.services.molecular_network import (  # noqa: E402
    NetworkCondition,
    analyze_conditions,
    build_cytoscape_tables,
    generate_binned_numpy_similarity_edges,
    read_similarity_edges,
    resolve_score_thresholds,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 1: build a spectrum molecular network from MSP files."
    )
    parser.add_argument("msp_files", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--edge-table", type=Path)
    parser.add_argument("--sample-class", action="append")
    parser.add_argument("--ion-mode-column", default="IONMODE")
    parser.add_argument("--mz-tolerance", type=float, default=0.01)
    parser.add_argument("--score-thresholds", default="p95,p97,p98,p99")
    parser.add_argument("--match-peak-counts", default="3")
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
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print("[1/5] Reading MSP files...", file=sys.stderr)
    with tqdm(
        total=len(args.msp_files), desc="[1/5] MSP files",
        unit="file", dynamic_ncols=True,
    ) as bar:
        completed_files = 0

        def update_msp(current, total, name, readable):
            nonlocal completed_files
            bar.update(current - completed_files)
            completed_files = current
            bar.set_postfix(file=name, readable=f"{readable:,}")

        spectrum_nodes, spectra, aliases = load_msp_files(
            args.msp_files,
            ion_mode_column=args.ion_mode_column,
            class_assignments=parse_assignments(args.sample_class),
            progress_callback=update_msp,
        )
    print(
        f"[1/5] Completed: {len(spectrum_nodes):,} readable spectra.",
        file=sys.stderr,
    )
    match_counts = comma_values(args.match_peak_counts, int)
    edge_minimum_matches = min(
        [*match_counts, int(args.selected_match_peak_count)]
    )
    if args.edge_table:
        print("[2/5] Reading and validating the edge table...", file=sys.stderr)
        edges = remap_uploaded_edges(
            read_similarity_edges(args.edge_table), aliases
        )
        edge_source = "uploaded"
        print(f"[2/5] Completed: {len(edges):,} edges.", file=sys.stderr)
    else:
        print("[2/5] Generating spectrum-similarity edges...", file=sys.stderr)
        edges = None
        ion_modes = spectrum_nodes.set_index("node_id")["ion_mode"].to_dict()
        with tqdm(
            total=len(spectra), desc="[2/5] NumPy cosine",
            unit="spectrum", dynamic_ncols=True,
        ) as bar:
            completed_spectra = 0
            for processed, total, count, result in (
                generate_binned_numpy_similarity_edges(
                    spectra,
                    ion_modes,
                    mz_tolerance=args.mz_tolerance,
                    minimum_matched_peaks=edge_minimum_matches,
                    batch_size=args.edge_batch_size,
                )
            ):
                bar.update(processed - completed_spectra)
                completed_spectra = processed
                bar.set_postfix(edges=f"{count:,}")
                if result is not None:
                    edges = result
        if edges is None or edges.empty:
            raise ValueError("No spectrum-similarity edges passed the threshold.")
        edge_source = "generated"
        print(f"[2/5] Completed: {len(edges):,} edges.", file=sys.stderr)
    early_edge_path = (
        output_dir / f"{edge_source}_similarity_edges.tsv"
    )
    edges.to_csv(early_edge_path, sep="\t", index=False)
    print(
        f"[2/5] Saved intermediate edges: {early_edge_path}",
        file=sys.stderr,
    )

    score_specs = comma_values(args.score_thresholds, str)
    top_values = comma_values(args.top_k_values, int, allow_all=True)
    resolutions = comma_values(args.resolutions, float)
    selected_top = comma_values(args.selected_top_k, int, allow_all=True)[0]
    selected_score_text = str(args.selected_score).strip().lower()
    if selected_score_text not in {
        str(value).strip().lower() for value in score_specs
    }:
        score_specs.append(args.selected_score)
        print(
            f"[3/5] Added selected Score condition to grid: "
            f"{args.selected_score}",
            file=sys.stderr,
        )
    if args.selected_match_peak_count not in match_counts:
        match_counts.append(args.selected_match_peak_count)
        print(
            f"[3/5] Added selected MatchPeakCount to grid: "
            f"{args.selected_match_peak_count}",
            file=sys.stderr,
        )
    if selected_top not in top_values:
        top_values.append(selected_top)
        print(
            f"[3/5] Added selected top-k to grid: {selected_top}",
            file=sys.stderr,
        )
    if not any(
        math.isclose(args.selected_resolution, value)
        for value in resolutions
    ):
        resolutions.append(args.selected_resolution)
        print(
            f"[3/5] Added selected resolution to grid: "
            f"{args.selected_resolution}",
            file=sys.stderr,
        )
    condition_count = (
        len(score_specs) * len(match_counts) * len(top_values) * len(resolutions)
    )
    print(
        f"[3/5] Evaluating {condition_count:,} network conditions...",
        file=sys.stderr,
    )
    with tqdm(
        total=condition_count, desc="[3/5] Leiden conditions",
        unit="condition", dynamic_ncols=True,
    ) as bar:
        completed_conditions = 0

        def update_condition(current, total, condition):
            nonlocal completed_conditions
            bar.update(current - completed_conditions)
            completed_conditions = current
            bar.set_postfix(condition=condition)

        statistics, assignments, filtered = analyze_conditions(
            edges,
            spectrum_nodes["node_id"],
            score_thresholds=score_specs,
            top_k_values=top_values,
            match_peak_counts=match_counts,
            resolutions=resolutions,
            random_seed=args.random_seed,
            progress_callback=update_condition,
        )
    print("[3/5] Network-condition comparison completed.", file=sys.stderr)
    print("[4/5] Selecting the requested network condition...", file=sys.stderr)
    threshold, score_label = resolve_score_thresholds(
        edges, [args.selected_score]
    )[0]
    selected = NetworkCondition(
        threshold, score_label, selected_top,
        args.selected_match_peak_count, args.selected_resolution,
        args.random_seed,
    ).condition_id
    if selected not in assignments:
        matching = statistics[
            (statistics["score_threshold_specification"].astype(str) == score_label)
            & (
                statistics["match_peak_count_threshold"].astype(int)
                == int(args.selected_match_peak_count)
            )
            & (
                statistics["top_k"].astype(str)
                == ("all" if selected_top is None else str(selected_top))
            )
            & (
                statistics["leiden_resolution"].astype(float).apply(
                    lambda value: math.isclose(
                        value, float(args.selected_resolution)
                    )
                )
            )
        ]
        if matching.empty:
            raise ValueError(
                "Selected condition could not be resolved after it was added "
                f"to the grid: {selected}"
            )
        selected = str(matching.iloc[0]["condition_id"])
    selected_nodes = assignments[selected].merge(
        spectrum_nodes, on="node_id", how="left"
    )
    node_table, edge_table = build_cytoscape_tables(
        selected_nodes,
        filtered[selected],
        pd.DataFrame(),
        {"metadata": {}, "features": []},
    )
    print(
        f"[4/5] Selected: {selected}; {len(node_table):,} nodes, "
        f"{len(edge_table):,} edges.",
        file=sys.stderr,
    )

    print("[5/5] Writing Cytoscape and analysis files...", file=sys.stderr)
    peak_rows = []
    for node_id, (mz_values, intensity_values) in spectra.items():
        for peak_index, (mz, intensity) in enumerate(
            zip(mz_values, intensity_values), start=1
        ):
            peak_rows.append(
                {
                    "node_id": node_id,
                    "peak_index": peak_index,
                    "mz": mz,
                    "intensity": intensity,
                }
            )
    node_table.to_csv(output_dir / "node.tsv", sep="\t", index=False)
    edge_table.to_csv(output_dir / "edge.tsv", sep="\t", index=False)
    selected_nodes.to_csv(
        output_dir / "selected_condition_spectrum_nodes.tsv",
        sep="\t", index=False,
    )
    filtered[selected].to_csv(
        output_dir / "selected_condition_similarity_edges.tsv",
        sep="\t", index=False,
    )
    pd.DataFrame(peak_rows).to_csv(
        output_dir / "spectrum_peaks.tsv", sep="\t", index=False
    )
    statistics.to_csv(
        output_dir / "network_condition_statistics.csv", index=False
    )
    pd.concat(assignments.values(), ignore_index=True).to_csv(
        output_dir / "network_cluster_assignments_all_conditions.csv",
        index=False,
    )
    edges.to_csv(
        output_dir / f"{edge_source}_similarity_edges.tsv",
        sep="\t", index=False,
    )
    config = {
        "schema_version": 1,
        "stage": "spectrum_network",
        "selected_condition_id": selected,
        "edge_source": edge_source,
        "similarity_engine": (
            "numpy_binned_sparse_cosine"
            if edge_source == "generated"
            else "uploaded"
        ),
        "similarity_bin_width": (
            2.0 * args.mz_tolerance if edge_source == "generated" else None
        ),
        "mz_tolerance": args.mz_tolerance,
        "ion_mode_column": args.ion_mode_column,
        "msp_files": [str(path.resolve()) for path in args.msp_files],
        "score_thresholds": score_specs,
        "match_peak_counts": match_counts,
        "top_k_values": top_values,
        "resolutions": resolutions,
        "random_seed": args.random_seed,
    }
    (output_dir / "network_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[5/5] All output files written.", file=sys.stderr)
    print(f"Cytoscape network: {output_dir}")
    print(f"Selected condition: {selected}")


if __name__ == "__main__":
    main()
