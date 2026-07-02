# demo-interpret をデモデータでオフライン検証できるようにする設計

- 日付: 2026-07-02
- 対象: `demo/demo-test/demo-interpret.py`, `tests/demo_interpret/`, 同梱デモデータ
- ステータス: 承認済み（実装計画へ）

## 背景 / 問題

`python demo/demo-test/demo-interpret.py --rebuild` 実行時に
`sqlite3.OperationalError: no such table: massbank_peak_records` が発生した。

根本原因:

1. `--rebuild` は evidence（MassBank 検索 + KG/SPARQL 参照）を **DB から再構築**する経路を強制する。
2. 接続先の既定 DB `data/db/massbank.sqlite3`（`MassBankDatabase.DEFAULT_DB_PATH`）は
   0 バイト・テーブル 0 件の空ファイルだった。
3. `MassBankDatabase._create_engine` が接続前に親ディレクトリを `mkdir` し、SQLite は接続時に
   ファイルが無ければ空ファイルを自動生成するため、DB 未構築でも例外が出ず、SQL 実行段階で
   初めて `no such table` になる。
4. DB を構築する `build_sqlite.py` はソース `massbank_records.tsv` / `massbank_peaks.json` を
   要求するが、それらは現状リポジトリに存在しない。

一方 `demo-interpret.py` は本来 **cache-first**：`--rebuild` を付けなければ既存の
`kg_evidence.json` を再利用し、DB / SPARQL / Azure に一切アクセスせず動く設計になっている。
今回のエラーは `--rebuild` を付けたことによる副作用にすぎない。

## ゴール

同梱デモデータ（`MSBNK-LCSB-LU119906`）を使って、

- (A) **オフライン自動テスト**：DB / SPARQL / Azure / 環境変数に一切依存せず、
  `main()` 全体（evidence 解決 → 読み込み → 解釈 → レンダリング）をフェイク LLM で通し、
  エンドツーエンドの配線を検証する。CI で常時回せる。
- (B) **手動デモ実行**：Azure 資格情報を設定すれば、同梱データを使って
  `python demo/demo-test/demo-interpret.py`（`--rebuild` なし）で最後まで実行できる。

## スコープ外（今回やらない）

- `--rebuild`（MassBank DB からの evidence 再構築）を通すこと。
- 空 DB を検出して分かりやすいエラーを出す「空 DB ガード」。
  （関連する改善だが本タスクの目的外。別途検討。）

## 現状の要点

- `demo-interpret.py` は cache-first。`resolve_evidence_path` が
  `--evidence` 指定 → キャッシュヒット → ビルダー実行、の順で evidence を解決する。
- 既定 input/output は `massbank_rdf/data/llm_input_from_msp/` 配下を指す。
- そのデモデータは `.gitignore:222` の `data/` により **git 管理外**。
  そのままでは CI・別クローンで欠落し、安定フィクスチャにならない。
- `main()` は `AzureOpenAIInterpreter` の生成と `load_config_from_env()`（env 必須）を
  直に握っており、オフラインで通せない。
- 既存テスト `tests/demo_interpret/TestDemoInterpret.py` は `resolve_evidence_path` を
  スタブビルダーで検証するのみ（実デモデータは未使用）。
- テストランナー `tests/run_tests.py` は `Test*.py` を discovery する。

## 設計

### 1. `main()` を 1 点の seam で差し替え可能にする（小さな DI リファクタ）

`demo-interpret.py` に interpreter 生成の seam を導入する。

```python
def _default_build_interpreter():
    """既定: env から config を作り Azure interpreter を返す。"""
    config = load_config_from_env()
    return AzureOpenAIInterpreter(config), config


def main(argv=None, *, build_interpreter=_default_build_interpreter) -> int:
    args = parse_args(argv)
    evidence_path = resolve_evidence_path(args)
    evidence = load_evidence(evidence_path)
    interpreter, config = build_interpreter()
    ...
    result = interpreter.interpret_kg_evidence(evidence)
    ...
```

- Azure / env 依存は **すべて `_default_build_interpreter()` の裏に隔離**される。
- 既定の CLI 挙動・出力は不変（`build_interpreter` 未指定時は従来通り）。
- `load_config_from_env()` の呼び出しタイミングが `main` 冒頭から seam 内へ移るが、
  結果は同じ（env 欠落時は同じ `SystemExit(1)` を出す）。
- テストは fake を注入して env も Azure もなしに `main()` を実行できる。

fake は最小インターフェース `interpret_kg_evidence(evidence) -> dict` を満たすオブジェクトと、
`deployment` 属性を持つ簡易 config（`types.SimpleNamespace(deployment="fake")`）を返せばよい。

### 2. デモデータを git 追跡（`git add -f`）

`.gitignore` の `data/` ルールは維持したまま、テスト・手動デモに必要なファイルだけを
`git add -f` で強制追跡する。追跡対象:

- `massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/kg_evidence.json`
  （オフラインテストが読む evidence 本体、〜20KB）
- `massbank_rdf/data/llm_input_from_msp/input_files/MSBNK-LCSB-LU119906.msp`
  （既定 input／手動デモ用、〜4KB）
- `massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/massbank_records.tsv`
  （evidence の由来参照・手動再現用、〜4KB）

合計 〜28KB。テストはこれら既定パスを直接参照するため、フィクスチャのコピーは作らない。

### 3. オフライン end-to-end テストを追加

`tests/demo_interpret/TestDemoInterpret.py` に、実デモデータを使うテストを追記する。

- `demo_interpret.EVIDENCE_FILENAME` / 既定パス、または `--evidence <kg_evidence.json>` で
  デモの evidence を指す。
- fake interpreter を `build_interpreter` 経由で注入。
- 検証項目:
  1. fake が受け取った evidence が実データの `features` を含む（＝正しい evidence が読まれた）。
  2. `main(...)` が `0` を返す。
  3. レンダリング出力（`render_text` 相当、または `--json`）が標準出力へ出る。
- DB / SPARQL / Azure / env は一切不要。既存のスタブビルダー系テストはそのまま維持する。
- `tests/run_tests.py` の `Test*.py` discovery で拾われる。

### 4. 手動デモ実行（追加コード不要）

設計 1 で既定挙動が不変のため、Azure 資格情報（`AZURE_OPENAI_ENDPOINT` /
`AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_DEPLOYMENT`）を設定すれば、
`python demo/demo-test/demo-interpret.py`（`--rebuild` なし）で同梱データの
`kg_evidence.json` を使い LLM 解釈まで実行できる。設計 2 によりデータが追跡されるため、
別クローンでも同様に実行可能。

## テスト方針

- オフライン e2e テスト（設計 3）を追加し、`python tests/run_tests.py` および
  単体 discovery で緑になることを確認する。
- 既存の `resolve_evidence_path` テスト群は回帰なく維持する。
- fake interpreter によりネットワーク・課金・環境依存はゼロ。

## リスク / 留意点

- `data/` 配下を `git add -f` するのは `.gitignore` 方針と部分的に矛盾する。
  対象を上記 3 ファイルに限定し、意図をコミットメッセージ／本 spec で明示する。
- `main()` の seam 追加は後方互換。既定引数のため既存呼び出し（`main()`）は影響なし。
