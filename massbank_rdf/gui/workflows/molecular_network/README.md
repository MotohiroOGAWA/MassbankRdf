# MSP Molecular Network + KG workflow

## Purpose

This workflow combines a spectrum molecular network with MassBank annotations
and KG metadata. It produces Cytoscape-compatible node and edge tables while
retaining the complete MassBank/KG output from the MSP annotation workflow.

The workflow URL is `/molecular-network/input/`.

## Inputs

Uploads are validated by their contents, regardless of filename extension.
This applies to MSP spectra, result ZIP archives, and edge tables.
Tab/comma delimiters in edge tables are detected from the header.

### MSP files

One or more MSP files can be uploaded. The editable `sample_class` column is
handled in the same way as the MSP KG workflow. Blank classes become `Class1`,
`Class2`, and so on in upload order.

The canonical spectrum node ID is:

```text
file_name.msp::readable_record_number
```

The edge table may instead use an MSP `Name` value when that value is unique
across all uploaded spectra. Empty or duplicated `Name` values cannot be used
as aliases; use the canonical ID in that case.

### Reusing a completed MSP KG result

`Completed MSP KG result ZIP` accepts a ZIP produced by
`/msp-kg/input/`. When supplied:

1. Validate the completed-result schema and ZIP size.
2. Compare the complete saved `spectrum_uid` set with the currently uploaded
   MSP spectra.
3. Reject the ZIP if any spectrum is missing or unexpected.
4. Restore MassBank candidates, selected InChIKeys, KG evidence, SPARQL,
   record summary, and annotations.
5. Update candidate/annotation sample classes from the current file/class
   table.
6. Skip the per-spectrum MassBank search and batched KG search.
7. Continue with edge generation/import, network comparison, Leiden, and the
   unannotated-cluster fallback.

This is substantially faster when the same MSP spectra have already completed
the MSP KG workflow. A ZIP from different MSP files cannot be reused merely
because its record count happens to be the same.

### Spectrum similarity edge table

The edge table is optional. If supplied, upload TSV, CSV, or TXT with these
case-sensitive columns:

| Column | Meaning |
|---|---|
| `SourceID` | First spectrum node |
| `TargetID` | Second spectrum node |
| `Score` | Spectrum similarity and edge weight |
| `MatchPeakCount` | Optional number of matched peaks |

If `MatchPeakCount` is absent, the UI shows a warning. Before MassBank/KG
search, the workflow matches each edge endpoint to its MSP spectrum and computes
one-to-one matched-peak counts using the configured m/z tolerance. The supplied
`Score` is preserved. Computed counts are used in network filtering and exported
in the edge tables. Unknown spectrum IDs produce an error.

Self-loops are removed. Reverse/duplicate edges are collapsed and the row with
the highest `Score`, then highest `MatchPeakCount`, is retained.

### Automatic edge calculation

When the edge table is omitted, the workflow calculates it from the uploaded
MSP spectra before MassBank search:

1. Read and normalize the configured ion mode for every spectrum. A readable
   spectrum without ion mode is rejected at input validation.
2. Compare spectra only within the same ion mode.
3. Build a sparse expanded m/z-bin incidence matrix to find candidate pairs.
4. Re-evaluate candidate pairs with exact one-to-one peak matching within the
   configured MassBank m/z tolerance.
5. Calculate cosine similarity from the full spectrum norms and matched-peak
   dot product.
6. Retain pairs whose exact matched-peak count is at least the smallest
   MatchPeakCount value in the network condition grid.

Progress reports processed spectra and the number of qualifying edges. Sparse
candidate discovery avoids exact comparison of every possible spectrum pair,
while exact scoring prevents coarse-bin false positives from entering the
network.

## MassBank and KG annotation

Every readable spectrum is searched against MassBank first, using the same
parameters and candidate-ranking code as the MSP KG workflow. Candidate
InChIKeys are then queried against the KG in batches. `Use KG metadata rank`
can be turned off to rank unique InChIKeys using MassBank similarity only.

The precursor m/z filter applies only to this ordinary per-spectrum search.
The MSP ion mode is required for ordinary per-spectrum searches and automatic
edge generation. Common-peak searches use the shared Ion mode dropdown instead;
a blank selection disables that search filter.

## Molecular-network condition grid

For each condition:

1. Keep edges with `MatchPeakCount` at least the configured threshold.
2. Keep edges with `Score` at least the configured fixed or percentile
   threshold.
3. Optionally retain each node's top-k edges. The final graph uses the union of
   the per-node selections: an edge remains when it is selected by either end.
4. Remove duplicate undirected edges and self-loops.
5. Include every MSP spectrum as a node, including isolated spectra.
6. Split the graph into connected components.
7. Run weighted Leiden independently within every non-singleton component,
   using `Score` as weight. Singletons become one-node clusters.

Score thresholds accept comma-separated fixed values such as `0.7,0.8` or
percentiles such as `p95,p97,p98,p99`. Percentiles are calculated from the
uploaded edge table before the MatchPeakCount and top-k filters.

Default comparison values are:

- `MatchPeakCount >= 6`
- Score thresholds `p95,p97,p98,p99`
- top k `5,10,15,20`
- Leiden resolution `0.5,1.0,1.5,2.0`
- random seed `42`

Score filtering is intended to select credible edges. Use Leiden resolution to
control cluster granularity.

The selected export condition must also be present in the comparison grid.
Its first MatchPeakCount threshold, selected Score threshold, selected top-k,
and selected resolution determine `node.tsv` and `edge.tsv`.

## Unannotated-cluster fallback

After the selected network has been clustered, a cluster is considered
annotated when at least one member spectrum has a selected MassBank InChIKey.
Only clusters with no such annotation enter the fallback.

The **Common peak annotation conditions** panel is the same component used by
Common Peak Annotation. Both workflows share validation, `find_common_peaks`,
and `annotate_common_peaks_with_massbank`, including KG metadata ranking and
unique InChIKey limits. Change the shared component/service to update both.

Shared defaults are m/z tolerance 0.01, minimum relative intensity 0.05,
Common peak N 10, unlimited unique InChIKeys, MassBank top N 50,
minimum matched peaks 3, minimum cosine similarity 0.5, and Positive ion mode.
The MassBank search limits also apply to ordinary per-spectrum searches.

For each unannotated cluster:

1. Remove peaks below the per-record relative intensity threshold.
2. Group peaks within tolerance of the running group mean m/z.
3. Rank by record count, peak count, total intensity, then m/z.
4. Apply the network-specific minimum cluster presence fraction (default 0,
   disabled), preserving the shared ranking.
5. Select Common peak N peaks and search using record counts as pseudo intensities.
6. Apply similarity filtering, shared KG metadata ranking and the InChIKey limit.

Common-peak search does not apply precursor m/z. Its Ion mode dropdown has
exactly the same behavior as Common Peak Annotation, including the blank option.
MSP ion-mode column, ordinary-spectrum precursor filtering/ranking, cluster
presence threshold, and network/Leiden settings remain additional controls.

Candidate edges are marked `cluster_common_peak_massbank`; these are cluster-level
inferences propagated to member spectra, not direct spectrum identifications.
`molecular_network_config.json` records the shared `common_peak_settings` as well
as the network-specific settings. Common peak exports retain shared statistics
and the network aliases `mz`, `intensity` (record count), and `presence_count`.

Fallback InChIKeys that were not already queried are sent to the KG in batches.

## Output files

The result page includes the normal MassBank, SPARQL, KG, class-analysis, and
download tabs, plus network-condition and Cytoscape previews. The ZIP contains:

| File | Meaning |
|---|---|
| `node.tsv` | Cytoscape nodes for the selected condition |
| `edge.tsv` | Cytoscape edges for the selected condition |
| `network_condition_statistics.csv` | One row per parameter combination |
| `network_cluster_assignments_all_conditions.csv` | Cluster/component assignment for every node and condition |
| `selected_condition_spectrum_nodes.tsv` | Spectrum nodes and selected cluster attributes |
| `selected_condition_similarity_edges.tsv` | Filtered spectrum-similarity edges |
| `generated_similarity_edges.tsv` | Automatically calculated unfiltered edge input |
| `uploaded_similarity_edges.tsv` | Validated/remapped uploaded edge input |
| `unannotated_cluster_common_peaks.tsv` | Common peaks synthesized for fallback clusters |
| `unannotated_cluster_massbank_candidates.tsv` | Fallback MassBank matches |
| `molecular_network_config.json` | Network grid and selected-condition settings |
| `massbank_candidates_by_spectrum.csv` | Ordinary per-spectrum MassBank candidates |
| `spectrum_inchikey_annotations.csv` | Ordinary selected InChIKeys per spectrum |
| `massbank_record_summary.csv` | MassBank record aggregation |
| `class_inchikey_kg_analysis.csv` | Sample-class/InChIKey summary |
| `kg_evidence.json` | Ordinary and fallback KG evidence |
| `sparql/` | Generated KG queries |

### `node.tsv`

`node_id` is namespaced for Cytoscape:

- `spectrum:...` for an MSP spectrum
- `inchikey:...` for a compound key
- `metadata:<cluster>:<type>:<provider>:...` for a KG entity

Spectrum rows contain `node_type=spectrum`, `cluster_id`, `connected_component_id`,
`component_node_count`, source file, class, MSP name, and peak count. KG rows
include their metadata type in `node_type`, as well as provider and cluster ID.
The same KG entity is emitted as a separate metadata node in every cluster in
which it occurs, so metadata nodes never merge otherwise separate clusters.

### `edge.tsv`

Edge types are:

- `spectrum_similarity`
- `massbank_annotation`
- `cluster_common_peak_massbank`
- `kg_metadata`

Spectrum-similarity `weight` is `Score`; its matched peak count is retained.
Annotation edges carry the MassBank score and accession where available.

### Condition statistics

Each row reports:

- node count
- edge count
- isolated node count
- connected component count
- cluster count
- largest component node count and fraction
- minimum, median, mean, and maximum cluster size
- weighted modularity
- resolved Score threshold
- Score threshold specification
- top k
- MatchPeakCount threshold
- Leiden resolution
- random seed

## Cytoscape import

Import `node.tsv` as a node table with `node_id` as the key. Import `edge.tsv`
as a network table using `source` and `target`. Map `node_type`, `cluster_id`,
and `sample_class` to visual properties. `edge_type` can be used to distinguish
spectrum similarity, MassBank annotation, and KG metadata relationships.

## Dependencies

Weighted Leiden uses `python-igraph` and `leidenalg`; these are declared in
`env/requirements.txt`. The workflow raises an explicit error if they are not
installed rather than silently substituting a different clustering algorithm.
