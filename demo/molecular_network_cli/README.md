# Molecular network Cytoscape CLI

複数MSPから分子ネットワークを構築し、別コマンドでMassBank/KG metadataを
追加する2段階CLIである。どちらの段階でもCytoscapeへ直接読み込める
`node.tsv`と`edge.tsv`を出力する。GUIは使用しない。

## Stage 1: MSPからnetworkとclusterを作る

```bash
cd /home/ogawa/workspace/MassbankRdf/mnt/app

python demo/molecular_network_cli/build_network.py \
  /data/WT.msp \
  /data/PR.msp \
  --sample-class WT.msp=WT \
  --sample-class PR.msp=PR \
  --output-dir /data/spectrum_network
```

edgeテーブルを省略すると、全スペクトルを最初にNumPy配列へ一度だけ変換し、
同じion mode内でm/z bin疎行列を作る。cosine similarityと共有bin数は
バッチ疎行列積で計算し、スペクトルpairをPythonで1組ずつ再計算しない。
bin幅は`2 * --mz-tolerance`である。GUIの厳密な一対一peak matchingとは
Scoreが異なる可能性があるが、大規模MSPのnetwork作成を優先した方式である。

MSP読込、NumPy cosine、Leiden条件、common-peak cluster、KG chunkは`tqdm`で
逐次表示する。短い読込・結合・書出し工程も工程番号と完了件数を表示する。

```text
Edges: 1,000/5,000 spectra; 12,345 edges
```

この時点の`node.tsv`と`edge.tsv`はスペクトル分子ネットワークとして
Cytoscapeで表示でき、各スペクトルにはLeidenの`cluster_id`と
`connected_component_id`が付いている。

後段のcommon-peak計算に必要な全peakは`spectrum_peaks.tsv`へ保存されるため、
Stage 2で元のMSPファイルを再指定する必要はない。

### 既存edgeを使う

```bash
python demo/molecular_network_cli/build_network.py \
  WT.msp PR.msp \
  --edge-table spectrum_edges.tsv \
  --output-dir spectrum_network
```

edgeテーブルの必須列は次の4列である。

- `SourceID`
- `TargetID`
- `Score`
- `MatchPeakCount`

## Stage 2: MSP KG結果からannotationを追加する

```bash
python demo/molecular_network_cli/annotate_network.py \
  --network-dir /data/spectrum_network \
  --msp-kg-result /data/msp_kg_result.zip \
  --output-dir /data/annotated_network
```

`/msp-kg/` workflowが出力したZIPから次を読み込む。

- スペクトルとMassBank record/InChIKeyの対応
- `selected_for_kg`
- KG evidence
- 疾患、経路、生体試料、organism、activityなど

ZIP内の全`spectrum_uid`がStage 1のnetworkと完全一致しない場合は停止する。
保存済みannotationのみを使う場合、MassBank/KG検索は新たに実行しない。

`annotated_network/node.tsv`と`edge.tsv`には、スペクトルに加えてInChIKeyと
KG metadata node/edgeが含まれる。同じmetadataでもclusterが異なれば
cluster固有の別nodeになる。

## 未注釈clusterをcommon peakで検索する

```bash
python demo/molecular_network_cli/annotate_network.py \
  --network-dir /data/spectrum_network \
  --msp-kg-result /data/msp_kg_result.zip \
  --output-dir /data/annotated_network \
  --annotate-unknown-clusters
```

このフラグを指定した場合だけ、保存済みZIPに選択MassBank annotationが
1件もないclusterについて次を実行する。

1. cluster内で頻出し、相対強度が十分なcommon peakを作る
2. precursor m/zを指定せずMassBank検索する
3. ion modeは維持し、複数modeがあればmodeごとに検索する
4. 得られたユニークInChIKeyをKG検索する
5. `cluster_common_peak_massbank` edgeとしてclusterのスペクトルへ付与する

主なオプション：

```bash
--common-presence-fraction 0.5
--common-relative-intensity 0.05
--common-peak-limit 100
--massbank-top-n 10
--massbank-min-matched-peaks 1
--minimum-similarity 0.5
--max-inchikeys-per-cluster 3
```

## 条件指定

```bash
--mz-tolerance 0.01
--match-peak-counts 6
--score-thresholds p95,p97,p98,p99
--top-k-values 5,10,15,20
--resolutions 0.5,1.0,1.5,2.0
--selected-score p95
--selected-match-peak-count 6
--selected-top-k 10
--selected-resolution 1.0
--random-seed 42
```

選択条件は比較gridに含まれている必要がある。

## Stage 1出力

- `node.tsv`
- `edge.tsv`
- `network_condition_statistics.csv`
- `network_cluster_assignments_all_conditions.csv`
- `selected_condition_spectrum_nodes.tsv`
- `selected_condition_similarity_edges.tsv`
- `generated_similarity_edges.tsv`または`uploaded_similarity_edges.tsv`
- `spectrum_peaks.tsv`
- `network_config.json`

## Stage 2追加出力

- annotation済み`node.tsv`
- annotation済み`edge.tsv`
- `annotated_massbank_candidates.tsv`
- `kg_evidence.json`
- `annotation_config.json`
- `unannotated_cluster_common_peaks.tsv`
- `unannotated_cluster_massbank_candidates.tsv`
- `fallback_sparql/`

`node.tsv`の`node_type`で`spectrum`、`inchikey`、疾患、経路などを判別する。

## Cytoscape

1. `node.tsv`をnode tableとして読み込み、keyを`node_id`にする。
2. `edge.tsv`をnetworkとして読み込み、sourceを`source`、targetを`target`にする。
3. `node_type`、`cluster_id`、`sample_class`をStyleへ割り当てる。
4. `edge_type`でスペクトル類似度、MassBank annotation、KG metadataを分ける。
