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
| `MatchPeakCount` | Number of matched peaks |

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
Ion mode is required and is used for both ordinary per-spectrum searches and
unannotated-cluster common-peak searches.

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

For each unannotated cluster:

1. Normalize each spectrum's intensities to its base peak.
2. Remove peaks below the configured minimum relative intensity.
3. Group m/z observations within the MassBank m/z tolerance.
4. Retain groups present in at least the configured fraction of cluster
   spectra.
5. Rank common peaks by presence and intensity and cap their number.
6. Search the synthesized common-peak spectrum against MassBank.

This fallback intentionally disables precursor m/z, but retains ion mode. When
a cluster contains multiple ion modes, its common peaks are searched separately
for every ion mode represented in the cluster, after which duplicate MassBank
records are collapsed. Clusters without a readable ion mode are not searched.
Its candidate edges are marked `cluster_common_peak_massbank`; they are cluster-level
inferences propagated to member spectra and should not be interpreted as
direct spectrum identification.

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
