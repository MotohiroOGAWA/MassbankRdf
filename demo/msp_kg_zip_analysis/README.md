# MSP/KG result ZIP metadata-count histogram

`msp_kg_result.zip`を安全に一時ディレクトリへ解凍し、
`massbank_candidates_by_spectrum.csv`と
`spectrum_inchikey_annotations.csv`からスペクトル単位の
`kg_metadata_count`分布を描画する。

## 集計定義

デフォルトの`--aggregation top`では、各スペクトルについて
`selected_for_kg=True`の候補を最終rank順に並べ、最上位のユニークな
InChIKeyの`kg_metadata_count`を代表値とする。同じInChIKeyを持つ複数の
MassBankレコードは1回だけ数える。MassBank/InChIKey annotationがない
入力スペクトルも除外せず、metadata countを0として含める。

別の集計も選択できる。

- `top`: 最上位ユニークInChIKey
- `max`: 選択ユニークInChIKey中の最大値
- `mean`: 選択ユニークInChIKeyの平均
- `sum`: 選択ユニークInChIKeyの合計

## 1つのZIP

```bash
python demo/msp_kg_zip_analysis/plot_metadata_count_histogram.py \
  /path/to/msp_kg_result.zip \
  --output-dir /path/to/analysis
```

## 2つのZIPを比較

```bash
python demo/msp_kg_zip_analysis/plot_metadata_count_histogram.py \
  /path/to/result_1.zip \
  /path/to/result_2.zip \
  --label Experiment \
  --label Control \
  --bin-width 25 \
  --x-max 500 \
  --output-dir /path/to/analysis
```

2つのデータセットには同一binを使用する。1つ目を青、2つ目を赤、
`alpha=0.42`で重ねる。それぞれの平均位置に同色の点線を引く。

bin数ではなく`--bin-width`で幅を指定する。デフォルトは`10`である。

```bash
--bin-width 25
```

この場合、0–25、25–50、50–75…の範囲で集計する。

### x軸上限とoverflow bin

`--x-max`を指定すると、その値以上のmetadata countを右端の最後のbinへ
まとめる。

```bash
python demo/msp_kg_zip_analysis/plot_metadata_count_histogram.py \
  result.zip \
  --bin-width 25 \
  --x-max 500
```

この場合、x軸の右端は`≥500`となり、500以上の全スペクトルを同じbinへ
集約する。凡例にはそのスペクトル数を表示する。平均と各TSVは切り捨て前の
元のmetadata countから計算・保存する。平均が`--x-max`を超える場合だけ、
点線を右端へ表示し、凡例には実際の平均値を記載する。

## 出力

- `metadata_count_histogram.png`: ヒストグラム
- `metadata_count_by_spectrum.tsv`: プロットした全スペクトルの値
- `metadata_count_summary.tsv`: 件数、平均、中央値、標準偏差、最小、最大、
  metadata count 0のスペクトル数

`matplotlib`がない環境では次を実行する。

```bash
pip install matplotlib
```
