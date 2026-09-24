# MSP Molecular Network + KG

`/molecular-network/input/` で MSP と edge テーブルを読み込み、先に
クラスターを特定する。各スペクトルの MassBank 検索は行わない。

処理順は次のとおり。

1. MSP / edge テーブルを読み込む。
2. edge を準備する。
3. edge からクラスターを生成する。
4. MSP 内の既存の化合物名・構造 ID をクラスター単位に集約する。
5. 構造情報がないクラスターについて Common peak を抽出し、MassBank を検索する。
6. 既存情報および Common peak 候補の InChIKey で KG メタデータを取得する。
7. クラスター情報・根拠・Cytoscape テーブルを保存する。

## 入力とクラスター生成方法

edge テーブルは TSV/CSV で `SourceID`, `TargetID`, `Score` を必須とする。
`MatchPeakCount` がなければ、両端の MSP スペクトルを m/z 許容幅で
一対一対応させて計算する。入力済みの Score は再計算しない。

ノード ID は **0 始まりの全レコード通し番号**。スペクトルを持たないレコードも
一つとして数え、ノード・メタデータを保持する。例えば「スペクトルあり・なし・あり」
の順なら ID は `0, 1, 2` で、最後のスペクトルは `2` になる。
複数ファイルではアップロード順に通し番号を付ける。
`file_name.msp::zero_based_record_number` はファイル内の0始まり位置の別名。
全入力で一意の非数値 MSP `Name` も別名として使用できる。
数値の Name よりレコード位置の ID を優先する。
edge に現れないレコードも単独ノードとして保持する。
`has_spectrum` でピークの有無を区別する。Common peak の計算にはスペクトルを
持つメンバーのみを使用する。
スペクトルのないレコードにつながる edge の一致ピーク数は計算できないため、
その edge には `MatchPeakCount` の入力が必要。既存値は保持する。

現行の重み付き Leiden を継続して使う。

1. 自己ループを除く。逆向きを含む重複 edge は Score が最大の行を残す。
   同点なら MatchPeakCount が最大の行を残す。
2. Score と MatchPeakCount の下限で edge を絞る。
3. 各ノードの上位 k 本を選択し、どちらか一方が選択した edge を残す
   （union top-k）。したがって最終次数は k を超えることがある。
4. 無向グラフの連結成分を抽出し、`connected_component_id` を付ける。
5. 各連結成分で Score を重みとする Leiden
   (`RBConfigurationVertexPartition`) を実行して `cluster_id` を付ける。
6. 孤立ノードは単独クラスターにする。

resolution は分割の粒度を調整するパラメータ。seed の既定値は 42。
連結成分と Leiden クラスターは別々に出力する。
クラスターはスペクトル類似性のグループであり、同一化合物を意味しない。

Score の `p95` は edge 全体の Score の 95 パーセンタイルを下限にする。
MatchPeakCount/top-k フィルタより前に計算する。既定値は p95、top-k=10、
MatchPeakCount=6、resolution=1.0 の **1 条件**。
複数条件を比較したい場合はカンマ区切りで指定する。
出力条件は比較対象に含める。MatchPeakCount は入力した最初の値を使う。
大量の条件を毎回実行する必要はない。

edge が未指定の場合のみ、同じ ion mode の MSP 同士から cosine edge を生成する。
この場合は MSP の ion mode が必須。edge を入力する場合は必須ではない。
MSP は処理中に一度読み込み、その後の工程で再利用する。

## 一次アノテーション：MSP 既存情報

ユーザーが選択した方式は、MSP に含まれる既存情報の集約。

- 名前：`CompoundName`、なければ `Name`。
- 構造情報：`InChIKey`、`InChI`、`SMILES`。
- クラスターの全候補、構造情報を持つメンバー数、全メンバーに対する割合、
  根拠となるノード ID を保持する。
- 複数の構造情報がある場合はリストのまま残す。一つの化合物に強制統合しない。
- `Name` は測定 ID の場合もあるため、名前だけなら `name_only` とする。
  名前だけのクラスターは Common peak の対象に含める。
- InChIKey の形式に一致する値、`InChI=` で始まる値、または入力 SMILES が
  あるメンバーを持つクラスターは `structure_present` とする。
  MSP 提供者の構造情報を受け継ぐものであり、構造の実験的な検証ではない。
- InChI/SMILES のみでは現在の KG API に問い合わせられない。
  自動的に InChIKey へ変換する機能は含まない。

その他の方法として、外部アノテーション表の集約、CANOPUS による化合物クラス予測、
MS2LDA/Mass2Motif による部分構造アノテーションがある。これらは今回の実装には
含めない。将来追加する際も入力由来の情報と予測結果を区別する。

参考：
- [CANOPUS](https://bio.informatik.uni-jena.de/software/canopus/)
- [MS2LDA user guide](https://www.ms2lda.org/user_guide/)

## Common peak → MassBank → KG

構造情報のあるメンバーが一つもないクラスターだけを対象にする。

1. 各スペクトルの相対強度閾値以下のピークを除く。
2. 共通ピーク検出サービスで m/z 許容幅に基づきピークをまとめる。
3. 出現スペクトル数、ピーク数、合計強度、m/z の順で順位を付ける。
4. クラスター内出現率 (`presence_fraction`) で絞り、上位 N ピークを選ぶ。
5. 出現スペクトル数を擬似強度として MassBank を検索する。
   precursor m/z フィルタは使わない。ion mode、最小一致ピーク数、
   最小類似度、候補数の設定を適用する。
6. 共通サービスの KG metadata rank とユニーク InChIKey 上限を適用する。
   `Max MassBank InChIKey` の既定値は 10。空欄の場合は上限なし。
7. 候補 InChIKey と MSP の既存 InChIKey を重複排除し、50 件ずつ KG に照会する。

KG の検索入口は InChIKey。m/z 自体を KG に直接照会するものではない。
Common peak の候補はクラスターへの推定根拠として保存し、メンバー全員の同定には
変換しない。候補がなければ未アノテーションのまま保持する。
候補が存在しても KG のメタデータが見つからない場合を区別して記録する。
単独クラスターのピークはその一つのスペクトルに由来し、複数メンバーでの共有を
裏付けるものではない。KG の関連は試料での疾患・経路の存在を確定しない。

## 工程別進捗

全体を一本のパーセントに換算せず、以下の七本を常時表示する。

| 工程 | 進捗の単位 |
|---|---|
| MSP / edge input | 読込開始・終了 |
| Edge preparation | edge 生成時の処理済スペクトル数、または一致ピーク数の計算件数 |
| Cluster generation | 完了した条件数 / 条件総数 |
| MSP annotation | 集約済クラスター数 / 全クラスター数 |
| Common peaks | 処理済対象クラスター数 / 対象クラスター数 |
| KG metadata | 照会済ユニーク InChIKey 数 / 全キー数 |
| Export | 出力開始・終了 |

未開始の工程は Waiting、完了した工程は 100% を保持する。
KG 対象がなければスキップを明示する。ページ再読込で完了結果を表示する場合も
七本のバーを維持する。

## 出力

| ファイル | 内容 |
|---|---|
| `cluster_annotations.tsv` | 名前・構造情報の集約、根拠数・割合、Common peak 候補、KG 状態 |
| `msp_annotations.tsv` | MSP 由来の各スペクトルの情報 |
| `network_condition_statistics.csv` | 各条件のクラスター数・孤立ノード数・サイズ・modularity 等 |
| `network_cluster_assignments_all_conditions.csv` | 全条件での所属クラスター |
| `selected_condition_spectrum_nodes.tsv` | 選択条件のノードと既存 MSP 情報 |
| `selected_condition_similarity_edges.tsv` | 選択条件で残った edge |
| `uploaded_similarity_edges.tsv` / `generated_similarity_edges.tsv` | 入力/生成 edge |
| `unannotated_cluster_common_peaks.tsv` | 未アノテーションクラスターの共通ピーク |
| `unannotated_cluster_massbank_candidates.tsv` | クラスター単位の MassBank 候補 |
| `kg_evidence.json`, `sparql/` | KG 根拠とクエリ |
| `molecular_network_config.json`, `summary.json` | 設定と集計 |
| `node.tsv`, `edge.tsv` | Cytoscape 用のノード・edge |

Cytoscape の主な edge 種別は `spectrum_similarity`, `msp_metadata`,
`cluster_membership`, `cluster_common_peak_massbank`, `kg_metadata`。
Common peak 候補は `cluster:<id>` ノードに接続する。
KG メタデータノードにはクラスター ID を付ける。
結果ページの先頭タブは Cluster annotations。

旧 MSP KG 完了 ZIP の再利用 UI と、スペクトル単位の MassBank/precursor 設定は
このワークフローから外した。別の MSP + KG ワークフローは変更しない。
