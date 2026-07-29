# MSP Knowledge Graph Annotation Workflow

## 概要

このworkflowは、複数のMSPファイルに含まれるMS/MSスペクトルを
MassBankのスペクトルと比較し、類似するMassBankレコードのInChIKeyを
介してPubChem、HMDB、KNApSAcKのKnowledge Graph（KG）情報を付与する。

各MSPファイルには、`PR`、`WT`、`Control`、`Treatment`などの
サンプルクラスを割り当てられる。最終的に、個々のスペクトルの
アノテーションだけでなく、ファイルまたはクラスごとに偏って出現する
InChIKeyやKG metadataを解析する。

概念的なデータのつながりは次のようになる。

```text
KG entity
    ↓
InChIKey
    ↓
MassBank record
    ↓
Input MS/MS spectrum
    ↓
MSP file
    ↓
Sample class（PR、WTなど）
```

ブラウザには集約した結果を表示し、スペクトル単位の詳細結果やKGの
完全なJSONはZIPファイルとしてクライアントPCへダウンロードする。

## 入力

### MSP files

複数の`.msp`ファイルを同時にアップロードできる。

各ファイルは`Name:`をレコード開始位置として複数レコードへ分割される。
各レコードのmetadataとピークを読み取り、ピークを1つ以上読み取れた
レコードを検索対象とする。

アップロード後、次の件数を表示する。

```text
MSP loaded: 4 files; 1,929 records; 1,394 readable spectra.
```

ピークを読み取れないレコードが含まれる場合、処理全体は停止せず、
warningとしてスキップ件数だけを表示する。

```text
Skipped 535 records without readable peaks.
```

### Files and sample classes

アップロードしたファイルごとに、`sample_class`を入力できる。

例：

| file_name | sample_class |
| --- | --- |
| PR_01.msp | PR |
| PR_02.msp | PR |
| WT_01.msp | WT |
| WT_02.msp | WT |

アップロード時の初期値は空欄である。Run開始時に空欄のクラスを、
ファイルのアップロード順に`Class1`、`Class2`、…として自動設定する。
手動入力したクラス名は変更しない。このためクラス指定を省略したファイル
同士は、それぞれ別のクラスとして解析される。同名のMSPファイルを複数
アップロードすることはできない。

### 出力ZIP

出力名の入力は不要である。処理完了後、resultページから
`msp_kg_result.zip`をダウンロードする。ブラウザの保存ダイアログで
クライアントPC上の保存場所を選択する。

### Resume from checkpoint

チェックを付けると、中断した処理をサーバー側のチェックポイントから
再開する。

MassBank検索では25スペクトルごと、KG検索では1チャンクごとに
`checkpoint.pkl`を一時保存する。再開には次の条件が一致する必要がある。

- 同じMSPファイル内容
- 同じファイル名
- 同じサンプルクラス
- 同じ検索条件

設定が一致しない場合、誤った結果を混ぜないため再開を拒否する。
正常終了後はチェックポイントを削除する。

このチェックポイントは、同じサーバープロセスの一時領域に残った中断処理
を再開するためのものである。result ZIPには計算途中のチェックポイントを
含めないため、result ZIPのドラッグ操作だけで計算途中から再開することは
できない。

### Previous MSP result ZIP

以前のresult ZIPを入力画面へドラッグすると、ZIP内の
`workflow_config.json`から検索設定を復元する。

復元対象：

- MassBank top N
- m/z tolerance
- Min matched peaks
- Minimum cosine similarity
- precursor m/zフィルターの有効・無効
- precursor m/zのMSPカラム名
- precursor tolerance
- ion modeフィルターの有効・無効
- ion modeのMSPカラム名
- Max MassBank InChIKey for KG
- short InChIKey使用有無

現在アップロードされているMSPファイルと、保存設定内の`file_name`が
一致した場合、その行の`sample_class`も復元する。一致しないファイルの
クラスは変更しない。

`Open completed result ZIP`を押すと、完成済みZIPから次を読み込んで
resultページへ直接移動する。

- スペクトルごとのMassBank候補
- スペクトルごとのInChIKey annotation
- MassBank record集約結果
- class別KG解析
- KG evidence
- 実行済みSPARQL
- summaryとworkflow設定

この経路では`kg_precomputed=True`としてセッションを作るため、
MassBankスペクトル検索とKG検索は実行しない。MSPファイルを再アップロード
する必要もない。MassBank、SPARQL、KG、Class Analysis、Output、
`Ask your results`の各タブはZIP内の保存結果を使用する。

これは完成済み結果の再表示・対話解析であり、計算途中のZIPから検索を再開
する機能ではない。計算途中の再開にはサーバー側の
`Resume from checkpoint`を使用する。

Azure OpenAI API keyなどの認証情報は、安全のためZIPへ保存せず、
インポートもしない。インポートした結果でチャットを使用する場合は、
入力画面でLLMを有効にして認証情報を再入力してから
`Open completed result ZIP`を押す。

### LLM settings upload / download

LLM設定欄の`Download LLM settings`を押すと、次の設定を
`llm_settings.json`としてダウンロードする。

- interactive result chatの有効・無効
- output language
- Azure OpenAI endpoint
- deployment
- API version
- API key
- sample origin / context

ダウンロードした設定ファイルを`Upload LLM settings`へドラッグすると、
各入力欄を復元する。

API keyも設定ファイルへ保存し、アップロード時に復元する。API keyは
暗号化されず平文で保存されるため、設定ファイルを安全な場所に保管し、
共有ZIPやGitへ含めない。

## MassBank検索条件

### MassBank top N

各入力スペクトルについて保持するMassBank候補の最大件数である。

`MassBank top N = 10`の場合、1スペクトルにつき最大10候補を保持する。
候補はコサイン類似度の高い順に並ぶ。

### m/z tolerance

入力ピークとMassBankピークを一致と判定するm/z許容幅である。

### Min matched peaks

MassBank候補として採用するために必要な最小一致ピーク数である。

### Minimum cosine similarity

MassBank候補の類似度下限で、デフォルトは`0.5`である。

指定値以下の候補を除外する。デフォルトの場合、次の条件になる。

```text
cosine similarity > 0.5
```

`0.5`ちょうどの候補も除外対象である。この設定はKnowledge Graph
Search、Common Peak Annotation、MSP KG workflowで共通の入力
コンポーネントと判定処理を使用する。

### Precursor tolerance

`Use precursor m/z filter`はデフォルトでONである。OFFにすると、
MSPにprecursor m/zが存在してもMassBank検索の絞り込みには使用しない。

`MSP precursor m/z column`でmetadataカラム名を指定する。デフォルトは
`PRECURSORMZ`である。カラム名は大文字小文字を区別せず、空白と
アンダースコアも無視して照合する。

次の指定は同等に扱われる。

```text
PRECURSORMZ
PrecursorMZ
precursor_mz
Precursor MZ
```

入力MSPレコードに指定したカラムがある場合、次の範囲に入る
MassBankレコードだけを検索する。`PRECURSOR M/Z`のようにスラッシュを
含むカラムを使う場合は、入力画面にも同じカラム名を指定する。

```text
input precursor m/z - tolerance
    <= MassBank precursor m/z
    <= input precursor m/z + tolerance
```

入力レコードにprecursor m/zがない場合、precursor条件は適用しない。

### Ion mode

`Use ion mode filter`はデフォルトでONである。OFFにすると、MSPに
ion modeが存在してもMassBank検索の絞り込みには使用しない。

`MSP ion mode column`でmetadataカラム名を指定する。デフォルトは
`IONMODE`である。precursor m/zと同様に、大文字小文字、空白、
アンダースコアを無視して照合する。

```text
IONMODE
Ion_mode
ion mode
IonMode
```

入力MSPレコードにion modeがある場合、同じion modeのMassBankレコード
だけを検索する。

次の値を正規化する。

```text
POSITIVE / POS / + → POSITIVE
NEGATIVE / NEG / - → NEGATIVE
```

入力レコードにion modeがない場合、ion mode条件は適用しない。

現在、`[M+H]+`や`[M-H]-`などのprecursor typeは検索条件に使用して
いない。

### Max MassBank InChIKey for KG

1スペクトルについてKG検索に使用するユニークInChIKeyの最大件数である。

例：

```text
MassBank top N = 10
Max MassBank InChIKey for KG = 3
```

この場合、MassBank候補は最大10件保存するが、KG検索には上位候補から
得た最大3種類のユニークInChIKeyだけを使用する。同じInChIKeyを持つ
MassBankレコードが複数あっても1種類として数える。

空欄の場合、そのスペクトルのMassBank候補から得られたすべての
ユニークInChIKeyをKG検索対象にする。

### Connect KG using short InChIKey

無効の場合はfull InChIKeyでKGへ接続する。

有効の場合はInChIKeyの先頭14文字のconnectivity blockで検索する。
同じ結合構造を持つ立体異性体やプロトン化状態の違いを含めてKGを
検索できる一方、異なるfull InChIKeyの情報が同じ候補へ対応する可能性
がある。

## 処理フロー

### 1. 入力の検証

Runを押すと、次を検証する。

1. MSPファイルが1つ以上ある
2. ファイル名が重複していない
3. sample classの空欄を`Class1`、`Class2`、…で補完できる
4. MSP内に読み取り可能なスペクトルがある

検証成功後、resultページへ遷移してバッチ処理を開始する。

### 2. MSPレコードの読み取り

各MSPファイルをレコードへ分割し、metadataとピーク配列を作る。
読み取り可能な全スペクトルには次の識別子を付ける。

```text
spectrum_uid = source_file::file_record_index
```

例：

```text
PR_01.msp::125
```

### 3. スペクトルごとのMassBank検索

各スペクトルを独立してMassBankへ問い合わせる。

```text
Input spectrum 1 → MassBank top N
Input spectrum 2 → MassBank top N
Input spectrum 3 → MassBank top N
...
```

ブラウザには次のような進捗を表示する。

```text
MassBank search: spectrum 350/1,394
```

検索ループ中は、各hitを次のコンパクトな値だけでチェックポイントへ記録する。

```text
(spectrum index, MassBank record index, cosine score,
 matched peak count, candidate rank)
```

MassBank化合物metadataとKG metadata scoreをスペクトルごとには取得しない。
全スペクトルの検索完了後、ユニークなMassBank record indexのmetadataを
一括取得し、続いてユニークなInChIKeyのKG metadata scoreを1回のバッチで
取得する。

最終的に各候補へ次の情報を付ける。

- 元MSPファイル
- sample class
- ファイル内レコード番号
- スペクトル識別子
- 候補順位
- コサイン類似度
- 一致ピーク数
- MassBank accession
- MassBank化合物metadata
- InChIKey
- KG検索に採用されたか

### 4. スペクトルごとのInChIKeyアノテーション

各スペクトルのMassBank候補へ、MassBank類似度と事前計算済みKG
metadata量を組み合わせた順位を付ける。

`data/db/kg.sqlite3`にはInChIKeyごとのmetadata件数を事前集計した
`kg_metadata_scores`テーブルを持つ。通常の検索時にPubChem、HMDB、
KNApSAcKの全関係を再集計せず、このテーブルをInChIKey indexで参照する。

KG metadata countは次のユニーク件数の合計である。

- PubChem compound
- PubChem descriptor
- PubChem pathway
- HMDB metabolite
- HMDB pathway
- HMDB disease
- HMDB biospecimen
- KNApSAcK record
- KNApSAcK activity
- KNApSAcK activity category
- KNApSAcK activity function
- KNApSAcK target species

候補InChIKeyごとに次を計算する。

```text
massbank_similarity_rank
    = best cosine similarityの降順順位
```

```text
kg_metadata_rank
    = kg_metadata_countの降順順位
```

```text
combined_rank_sum
    = massbank_similarity_rank + kg_metadata_rank
```

`combined_rank_sum`が小さい候補から採用する。同点の場合は、
MassBank類似度が高い候補、KG metadata countが多い候補の順にする。

この方法により、スペクトル類似度だけが高くKG情報がほとんどない候補と、
十分な類似度を持ちKG metadataも豊富な候補のバランスを取る。

候補表には次の列を追加する。

- `massbank_similarity_rank`
- `kg_metadata_count`
- KG source/entity別metadata count
- `kg_metadata_rank`
- `combined_rank_sum`
- `combined_rank`

combined rank順でInChIKeyを重複排除し、その後、
`Max MassBank InChIKey for KG`を適用する。

候補表の`selected_for_kg`が`True`の行は、その候補のInChIKeyが
KG検索対象として採用されたことを示す。

### 5. ファイル横断のInChIKey重複排除

すべてのスペクトルを検索した後、全ファイル・全クラスから得た
InChIKeyを重複排除する。

```text
Spectrum-level InChIKeys
    ↓ global de-duplication
Unique InChIKeys for KG
```

同じInChIKeyが数百スペクトルに割り当てられても、KGへの問い合わせ
対象としては1回だけ扱う。

### 6. Knowledge Graph検索

ユニークInChIKeyを50件ずつのチャンクに分割し、次のKGを検索する。

- PubChem
- HMDB
- KNApSAcK

ブラウザには次のような進捗を表示する。

```text
KG search: chunk 3/18
```

検索する情報の例：

- 化合物記述子
- pathway
- disease
- biospecimen
- organism
- biological activity
- target species

チャンクごとの結果を統合し、InChIKey単位の`kg_evidence.json`を作る。

### 7. MassBankレコード単位の集約

ブラウザのMassBankタブでは、スペクトルごとの候補をそのまま数千行
表示せず、MassBankレコード単位に集約する。

```text
MassBank record
    ├─ assigned spectrum count
    ├─ assigned file count
    ├─ sample classes
    ├─ best score
    └─ mean score
```

`assigned_spectrum_count`は、そのMassBankレコードがTop N候補に含まれた
ユニークスペクトル数である。必ずしもrank 1になった回数ではない。

### 8. クラス別InChIKey・KG解析

各クラスとInChIKeyの組合せについて次を計算する。

```text
class prevalence
    = class内でInChIKeyが付いたスペクトル数
      / class内の全スペクトル数
```

```text
other class prevalence
    = 対象class以外でInChIKeyが付いたスペクトル数
      / 対象class以外の全スペクトル数
```

```text
enrichment ratio
    = class prevalence / other class prevalence
```

SciPyが利用できる場合、次の2×2分割表でFisherの正確確率検定も行う。

| | InChIKeyあり | InChIKeyなし |
| --- | ---: | ---: |
| 対象クラス | a | b |
| その他のクラス | c | d |

この結果へInChIKeyに対応するKG entity数の概要を結合する。

注意：出力するp値は未補正である。多数のInChIKeyを検定する本格的な
解析では、Benjamini-Hochberg法などによるFDR補正を別途行う必要がある。

### 9. ZIP作成

すべての成果物をサーバーの一時領域へ出力し、1つのZIPへまとめる。
resultページの`Output`タブからクライアントPCへダウンロードする。

## ブラウザの結果

### Search summary

次の実行概要を表示する。

- MSPファイル数
- MSP総レコード数
- 読み取り可能スペクトル数
- スキップレコード数
- InChIKeyを付与できたスペクトル数
- MassBank候補総数
- KG検索したユニークInChIKey数
- 使用した検索条件

### MassBankタブ

MassBankレコード単位の集約結果を表示する。

主な列：

- `accession_id`
- `inchikey`
- `name`
- `formula`
- `smiles`
- `assigned_spectrum_count`
- `assigned_file_count`
- `best_score`
- `mean_score`
- `sample_classes`

### SPARQLタブ

PubChem、HMDB、KNApSAcKへ送ったSPARQLを表示する。
InChIKeyが多い場合、`# Chunk N`単位で連結される。

### KGタブ

統合したKG evidenceをJSONで表示する。

### Class Analysisタブ

クラスとInChIKeyの組合せごとに次を表示する。

- クラス内該当スペクトル数
- クラス内全スペクトル数
- クラス内出現率
- 他クラス出現率
- enrichment ratio
- Fisher exact p値
- KG summary

### Outputタブ

全成果物を含むZIPをダウンロードする。

### Interpretationタブ

MSP workflowでは、トークン消費を抑えるため全KG featureの自動LLM
Interpretationを実行しない。入力画面の`Enable interactive result chat`
を有効にすると、次の`Ask your results`タブから必要な根拠だけを検索して
LLMへ渡す。

### Ask your resultsタブ

現在の解析結果について会話形式で質問する。例：

```text
Are any candidates associated with Alzheimer's disease observed in these results?
Among them, show the spectra associated with the PR class.
Which KG metadata supports this answer?
```

質問に対して、LLMより先に決定論的な検索を行う。

1. 疾患名、pathway名、class、MassBank accession、InChIKeyなどを抽出する
2. `kg_evidence`とスペクトルごとのMassBank候補から一致行を取得する
3. InChIKeyを介してKG featureと入力スペクトルを結合する
4. 抽出した根拠だけをAzure OpenAIへ渡す
5. 回答と根拠表を表示する

追質問では直前の回答で抽出したInChIKey範囲を維持する。LLMには、
入力スペクトルの観測、MassBank類似候補、KG associationを区別し、
候補を確定同定として表現しないよう指示する。

次の場合はAzure OpenAIを呼び出さずに拒否する。

- 質問が500文字を超える
- 全結果の網羅的解析など、全データ投入を要求する
- 一致するKG featureが20件を超える
- 一致するMassBank候補行が60件を超える
- LLMへ渡す根拠JSONが30,000文字を超える
- 検索対象となる具体的な語を決定論的に抽出できない

回答には直近4メッセージだけを会話文脈として使用し、その文字数も
6,000文字に制限する。LLMの回答上限は800 tokenである。一致する根拠が
ない場合はLLMを呼び出さず、「この結果では確認できない」と表示する。

## ZIP内の出力

```text
msp_kg_result.zip
├── massbank_candidates_by_spectrum.csv
├── spectrum_inchikey_annotations.csv
├── massbank_record_summary.csv
├── class_inchikey_kg_analysis.csv
├── kg_evidence.json
├── summary.json
├── workflow_config.json
└── sparql/
    ├── pubchem_compound.sparql
    ├── pubchem_pathway.sparql
    ├── hmdb.sparql
    └── knapsack_activity.sparql
```

## `massbank_candidates_by_spectrum.csv`

スペクトルごとの全MassBank候補を保存する詳細ファイルである。

1行は「1入力スペクトル × 1 MassBank候補」を表す。

主な列：

| 列 | 意味 |
| --- | --- |
| `spectrum_uid` | 入力スペクトルの一意ID |
| `source_file` | 元MSPファイル名 |
| `sample_class` | ファイルへ割り当てたクラス |
| `file_record_index` | MSPファイル内のレコード番号 |
| `msp_record_index` | 全ファイルを通した処理番号 |
| `msp_name` | 入力MSPのName |
| `candidate_rank` | スペクトル内のMassBank候補順位 |
| `score` | コサイン類似度 |
| `match` | 一致ピーク数 |
| `accession_id` | MassBank accession |
| `name` | MassBank化合物名 |
| `inchikey` | MassBank候補のInChIKey |
| `formula` | 分子式 |
| `smiles` | SMILES |
| `precursor_mz` | MassBank側precursor m/z |
| `precursor_type` | MassBank側precursor type |
| `ion_mode` | MassBank側ion mode |
| `selected_for_kg` | KG検索へ採用した候補か |
| `massbank_similarity_rank` | 候補InChIKeyの類似度順位 |
| `kg_metadata_count` | kg.sqlite3に事前集計したmetadata総数 |
| `kg_metadata_rank` | 候補内のKG metadata順位 |
| `combined_rank_sum` | 類似度順位とKG順位の合計 |
| `combined_rank` | rank sumに基づく最終順位 |

## `spectrum_inchikey_annotations.csv`

1行を1入力スペクトルとして、スペクトルごとのInChIKeyアノテーションを
まとめる。

| 列 | 意味 |
| --- | --- |
| `spectrum_uid` | スペクトル一意ID |
| `source_file` | 元MSPファイル |
| `sample_class` | サンプルクラス |
| `file_record_index` | ファイル内レコード番号 |
| `msp_name` | MSPのName |
| `peak_count` | 入力ピーク数 |
| `massbank_hit_count` | MassBank候補数 |
| `annotated_inchikey_count` | 採用したユニークInChIKey数 |
| `annotated_inchikeys` | 採用InChIKeyのカンマ区切り一覧 |

MassBank候補がない場合、`massbank_hit_count`と
`annotated_inchikey_count`は0になり、`annotated_inchikeys`は空欄に
なる。

## `massbank_record_summary.csv`

MassBank候補をMassBankレコード単位に集約する。
ブラウザのMassBankタブと同じ粒度のファイルである。

| 列 | 意味 |
| --- | --- |
| `accession_id` | MassBank accession |
| `inchikey` | InChIKey |
| `name` | 化合物名 |
| `formula` | 分子式 |
| `smiles` | SMILES |
| `assigned_spectrum_count` | Top N候補に含まれたユニークスペクトル数 |
| `assigned_file_count` | 候補が出現したファイル数 |
| `best_score` | 最高コサイン類似度 |
| `mean_score` | 平均コサイン類似度 |
| `sample_classes` | 候補が出現したクラス一覧 |

## `class_inchikey_kg_analysis.csv`

クラスごとのInChIKey出現傾向とKG概要を保存する。

| 列 | 意味 |
| --- | --- |
| `sample_class` | 対象クラス |
| `inchikey` | 対象InChIKey |
| `spectra_with_inchikey` | クラス内でInChIKeyが付いたスペクトル数 |
| `class_spectrum_count` | クラス内全スペクトル数 |
| `class_prevalence` | クラス内出現率 |
| `other_class_prevalence` | 他クラス出現率 |
| `enrichment_ratio` | 対象クラスへの濃縮率 |
| `fisher_exact_p_value` | Fisher exact検定の未補正p値 |
| `kg_summary` | InChIKeyに対応するKG entity数の概要 |

`enrichment_ratio = inf`は、対象クラスには存在するが他クラスでは
0件だったことを示す。

## `kg_evidence.json`

KG検索結果をInChIKey単位に統合したJSONである。

```json
{
  "metadata": {
    "feature_count": 1
  },
  "features": [
    {
      "inchikey": "...",
      "summary": {},
      "entities": {
        "compounds": {},
        "diseases": {},
        "pathways": {},
        "biospecimens": {},
        "organisms": {},
        "activities": {}
      }
    }
  ]
}
```

`entities`は情報源別にPubChem、HMDB、KNApSAcKのデータを保持する。

## `summary.json`

実行条件と全体件数を保存する。

主な内容：

- ファイル数
- 総レコード数
- 読み取り可能スペクトル数
- スキップ数
- MassBank候補数
- MassBank集約レコード数
- InChIKey付与スペクトル数
- KG検索ユニークInChIKey数
- MassBank top N
- m/z tolerance
- minimum matched peaks
- minimum cosine similarity
- precursor tolerance
- Max MassBank InChIKey for KG
- short InChIKey使用有無

## `workflow_config.json`

result ZIPを入力画面へドラッグして設定を復元するための機械可読設定で
ある。

```json
{
  "schema_version": 1,
  "workflow": "msp_kg",
  "files": [
    {
      "file_name": "PR_01.msp",
      "sample_class": "PR"
    }
  ],
  "search": {
    "top_n": 10,
    "mz_tolerance": 0.01,
    "min_matched_peaks": 1,
    "minimum_similarity": 0.5,
    "use_precursor_mz": true,
    "precursor_mz_column": "PRECURSORMZ",
    "precursor_tolerance": 0.01,
    "use_ion_mode": true,
    "ion_mode_column": "IONMODE",
    "max_massbank_inchikey": 3,
    "use_short_inchikey": false
  }
}
```

MSPの生データやAPI keyはこの設定ファイルに保存しない。

## `sparql/*.sparql`

各KGへ送信したSPARQLを保存する。

| ファイル | 内容 |
| --- | --- |
| `pubchem_compound.sparql` | PubChem化合物検索 |
| `pubchem_pathway.sparql` | PubChem pathway検索 |
| `hmdb.sparql` | HMDB metabolite、pathway、disease、biospecimen検索 |
| `knapsack_activity.sparql` | KNApSAcK activity検索 |

## Unknownスペクトルについて

他の解析ツールでUnknownとされたスペクトルでも、このworkflowの
MassBank類似検索から候補InChIKeyが得られれば、KGを介して次のような
metadataを付与できる可能性がある。

- pathway
- disease association
- biospecimen
- organism
- biological activity
- target species

ただし、MassBank候補からInChIKeyを1つも取得できないスペクトルは、
現在のデータモデルではKGへ接続する識別子を持たない。そのため、
完全なUnknownスペクトルへKGだけから直接metadataを割り当てることは
できない。

また、KG metadataはMassBank類似候補を介した間接的な情報であり、
入力スペクトルの化合物同定を保証するものではない。特に低い類似度、
少ない一致ピーク数、複数候補が競合する場合は、候補順位、score、
match、クラス内再現性を合わせて解釈する必要がある。

## 解釈上の注意

- MassBank候補は確定同定ではなくスペクトル類似候補である。
- `assigned_spectrum_count`はrank 1の回数ではなく、Top Nに含まれた
  スペクトル数である。
- `selected_for_kg=True`はKG検索に使用したことを示すだけで、
  正しい化合物であることを保証しない。
- クラス間でスペクトル数が大きく異なる場合、単純な件数ではなく
  prevalenceを比較する。
- Fisher exact p値は未補正なので、多重検定補正を検討する。
- 同一化合物由来の複数スペクトルや重複ピークがある場合、
  スペクトル数を独立観測として扱うことが適切か確認する。
- short InChIKey検索では立体異性体などの情報が混ざる可能性がある。
- KGに情報がないことは、生物学的意味がないことを意味しない。

## KG metadata scoreの再構築

`kg.sqlite3`を更新した場合、通常のKG import処理は古い
`kg_metadata_scores`を無効化する。次回workflow実行時に自動生成される。

事前に明示的に再構築する場合：

```bash
cd /workspaces/MassbankRdf/mnt/app
python data/db/build_kg_metadata_scores.py
```

別のKG databaseを指定する場合：

```bash
python data/db/build_kg_metadata_scores.py --db /path/to/kg.sqlite3
```

## 実装ファイル

```text
msp_kg/
├── input_page.py   # 複数ファイル入力、クラス表、条件検証
├── processor.py    # MassBank/KGバッチ処理、統計、保存、再開
├── result_chat_tab.py # 根拠制限付き対話UI
├── page.py         # Home画面のworkflow項目
├── __init__.py
└── README.md
```
