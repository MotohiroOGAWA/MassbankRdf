# demo-interpret オフラインテスト Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同梱デモデータ（MSBNK-LCSB-LU119906）を使い、`demo-interpret.py` の `main()` 全体を DB/SPARQL/Azure/env なしのオフラインで検証できるようにし、あわせて手動デモ実行も通せる状態にする。

**Architecture:** `main()` に interpreter 生成の 1 点 seam（`build_interpreter`）を導入して Azure/env 依存を隔離し、既定挙動を変えずにフェイク LLM を注入可能にする。テストは既定パス上の実デモデータ（git 追跡化する）を読み、フェイク interpreter で end-to-end を検証する。

**Tech Stack:** Python 3, `unittest`（`tests/run_tests.py` の `Test*.py` discovery）、venv インタプリタ `./.venv/Scripts/python.exe`。

## Global Constraints

- Python インタプリタは必ず `./.venv/Scripts/python.exe` を使う（素の `python` は壊れた Store スタブ）。
- `main()` の既定 CLI 挙動・出力・引数は不変に保つ（後方互換）。
- テストはネットワーク・課金・環境変数・DB・SPARQL に一切依存しない。
- 対象デモ record は `MSBNK-LCSB-LU119906`。feature0 の InChIKey は `LPHGQDQBBGAPDZ-UHFFFAOYSA-N`、feature 数は 3。
- 追跡するデモデータは以下 3 ファイルのみ（`git add -f`、`.gitignore` の `data/` ルールは維持）:
  - `massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/kg_evidence.json`
  - `massbank_rdf/data/llm_input_from_msp/input_files/MSBNK-LCSB-LU119906.msp`
  - `massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/massbank_records.tsv`

---

### Task 1: `main()` に interpreter 生成 seam を導入（DI リファクタ）

**Files:**
- Modify: `demo/demo-test/demo-interpret.py`（`main` 関数と新ヘルパ `_default_build_interpreter`）
- Test: `tests/demo_interpret/TestDemoInterpret.py`（新テストクラスを追記）

**Interfaces:**
- Consumes: 既存 `resolve_evidence_path(args, builder=...)`, `load_evidence(path)`, `render_text(result)`, `load_config_from_env()`, `AzureOpenAIInterpreter`。
- Produces:
  - `_default_build_interpreter() -> tuple[interpreter, config]`（interpreter は `interpret_kg_evidence(dict) -> dict` を持つ。config は `deployment` 属性を持つ）。
  - `main(argv: list[str] | None = None, *, build_interpreter=_default_build_interpreter) -> int`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/demo_interpret/TestDemoInterpret.py` の末尾（`if __name__ == "__main__":` の前）に追記する。ファイル冒頭には既に `import argparse, importlib.util, json, tempfile, unittest` と `from pathlib import Path`、`demo_interpret = _load_module()` がある。追加で `import io` と `from contextlib import redirect_stdout` を冒頭の import 群に足す。

```python
class MainInjectionTests(unittest.TestCase):
    def _fake_result(self) -> dict:
        return {
            "metadata": {
                "deployment": "fake-deployment",
                "feature_count": 1,
                "succeeded": 1,
                "failed": 0,
                "usage_total": {},
            },
            "summary": {"overview": "fake overview"},
            "features": [
                {"inchikey": "FAKE", "interpretation": {"compound_summary": "ok"}}
            ],
            "failures": [],
        }

    def test_main_uses_injected_interpreter_and_returns_zero(self) -> None:
        import types

        received: dict = {}

        class _FakeInterpreter:
            def interpret_kg_evidence(self, evidence):
                received["evidence"] = evidence
                return MainInjectionTests()._fake_result()

        def _build_interpreter():
            config = types.SimpleNamespace(deployment="fake-deployment")
            return _FakeInterpreter(), config

        with tempfile.TemporaryDirectory() as tmp:
            evidence_path = Path(tmp) / "kg_evidence.json"
            evidence_path.write_text(
                json.dumps({"metadata": {}, "features": [{"inchikey": "X"}]}),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = demo_interpret.main(
                    ["--evidence", str(evidence_path)],
                    build_interpreter=_build_interpreter,
                )

        self.assertEqual(code, 0)
        self.assertEqual(
            received["evidence"], {"metadata": {}, "features": [{"inchikey": "X"}]}
        )
        self.assertIn("LLM INTERPRETATION", buffer.getvalue())
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `./.venv/Scripts/python.exe -m unittest tests.demo_interpret.TestDemoInterpret.MainInjectionTests -v`
Expected: FAIL（`main()` が `build_interpreter` 引数を受け付けない → `TypeError: main() got an unexpected keyword argument 'build_interpreter'`）

- [ ] **Step 3: 最小実装 — seam を追加**

`demo/demo-test/demo-interpret.py` の `main` を以下に置き換える。あわせて `load_config_from_env` 定義の直後（または `main` の直前）に `_default_build_interpreter` を追加する。

```python
def _default_build_interpreter():
    """Build the real Azure interpreter from environment configuration.

    Returns the interpreter and its config. All Azure/env dependencies live
    behind this seam so tests can inject a fake and run fully offline.
    """
    config = load_config_from_env()
    return AzureOpenAIInterpreter(config), config


def main(argv: list[str] | None = None, *, build_interpreter=_default_build_interpreter) -> int:
    args = parse_args(argv)
    evidence_path = resolve_evidence_path(args)
    evidence = load_evidence(evidence_path)

    interpreter, config = build_interpreter()

    print(
        f"Interpreting {len(evidence.get('features', []))} feature(s) "
        f"from {evidence_path} using deployment '{config.deployment}'...",
        file=sys.stderr,
    )

    result = interpreter.interpret_kg_evidence(evidence)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render_text(result)

    return 0
```

注意: 元の `main` にあった `config = load_config_from_env()` 行は削除する（seam 内へ移動済み）。`resolve_evidence_path` / `load_evidence` / `render_text` の呼び出し順・出力は従来どおり。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `./.venv/Scripts/python.exe -m unittest tests.demo_interpret.TestDemoInterpret.MainInjectionTests -v`
Expected: PASS

- [ ] **Step 5: 既存テストの回帰確認**

Run: `./.venv/Scripts/python.exe -m unittest tests.demo_interpret.TestDemoInterpret -v`
Expected: 既存 `ResolveEvidencePathTests` 5 件 + 新規 1 件がすべて PASS

- [ ] **Step 6: コミット**

```bash
git add demo/demo-test/demo-interpret.py tests/demo_interpret/TestDemoInterpret.py tests/demo_interpret/__init__.py
git commit -m "refactor(demo): inject interpreter into demo-interpret main() for offline tests"
```

---

### Task 2: デモデータを git 追跡し、実データを使うオフライン e2e テストを追加

**Files:**
- Track (git add -f): 上記 Global Constraints の 3 ファイル
- Test: `tests/demo_interpret/TestDemoInterpret.py`（`MainInjectionTests` に実データ検証を1件追加）

**Interfaces:**
- Consumes: Task 1 の `demo_interpret.main(argv, *, build_interpreter=...)`、`demo_interpret.DEFAULT_OUTPUT_ROOT`、`demo_interpret.EVIDENCE_FILENAME`。
- Produces: なし（テスト＋追跡データのみ）。

- [ ] **Step 1: デモデータを git 追跡（`.gitignore` の data/ を回避）**

Run:
```bash
git add -f \
  massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/kg_evidence.json \
  massbank_rdf/data/llm_input_from_msp/input_files/MSBNK-LCSB-LU119906.msp \
  massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/massbank_records.tsv
git status --short
```
Expected: 上記 3 ファイルが `A`（added）で表示される。

- [ ] **Step 2: 実データを使う失敗テストを書く**

`tests/demo_interpret/TestDemoInterpret.py` の `MainInjectionTests` クラス内に追記する。

```python
    def test_main_interprets_shipped_demo_evidence_offline(self) -> None:
        import types

        received: dict = {}

        class _FakeInterpreter:
            def interpret_kg_evidence(self, evidence):
                received["evidence"] = evidence
                return MainInjectionTests()._fake_result()

        def _build_interpreter():
            config = types.SimpleNamespace(deployment="fake-deployment")
            return _FakeInterpreter(), config

        evidence_path = (
            demo_interpret.DEFAULT_OUTPUT_ROOT
            / "MSBNK-LCSB-LU119906"
            / demo_interpret.EVIDENCE_FILENAME
        )
        self.assertTrue(
            evidence_path.is_file(),
            f"shipped demo evidence missing: {evidence_path}",
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = demo_interpret.main(
                ["--evidence", str(evidence_path)],
                build_interpreter=_build_interpreter,
            )

        self.assertEqual(code, 0)
        features = received["evidence"].get("features", [])
        self.assertEqual(len(features), 3)
        inchikeys = {f.get("inchikey") for f in features}
        self.assertIn("LPHGQDQBBGAPDZ-UHFFFAOYSA-N", inchikeys)
        self.assertIn("LLM INTERPRETATION", buffer.getvalue())
```

- [ ] **Step 3: テストを実行して成功を確認**

Run: `./.venv/Scripts/python.exe -m unittest tests.demo_interpret.TestDemoInterpret.MainInjectionTests.test_main_interprets_shipped_demo_evidence_offline -v`
Expected: PASS（実 `kg_evidence.json` が読まれ、features=3、対象 InChIKey を含む）

- [ ] **Step 4: 全テスト discovery で緑を確認**

Run: `./.venv/Scripts/python.exe tests/run_tests.py`
Expected: 失敗 0（`tests/demo_interpret` を含む全 `Test*.py` が PASS）

- [ ] **Step 5: コミット**

```bash
git add -f massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/kg_evidence.json massbank_rdf/data/llm_input_from_msp/input_files/MSBNK-LCSB-LU119906.msp massbank_rdf/data/llm_input_from_msp/output_files/MSBNK-LCSB-LU119906/massbank_records.tsv
git add tests/demo_interpret/TestDemoInterpret.py
git commit -m "test(demo): offline end-to-end interpret test on shipped demo data"
```

---

### Task 3: 手動デモ実行の疎通確認（コード変更なし）

**Files:**
- なし（既定挙動確認のみ）

**Interfaces:**
- Consumes: Task 1 の `main()`（既定 `build_interpreter`）、cache-first の `resolve_evidence_path`。
- Produces: なし。

- [ ] **Step 1: cache-first 経路が env 無しで evidence 解決まで到達することを確認**

env 変数（AZURE_*）を設定していない状態で、`--rebuild` なし実行が「LLM 呼び出しの直前（env 欠落）」まで進むことを確認する。これは DB を呼ばず cached evidence を使う経路が生きている証拠。

Run: `./.venv/Scripts/python.exe demo/demo-test/demo-interpret.py`
Expected: stderr に `Using cached KG evidence: ...MSBNK-LCSB-LU119906/kg_evidence.json` が出た後、env 未設定なら `Missing required environment variable(s):` で終了する（`no such table` は出ない）。

- [ ] **Step 2: 結果を記録（コミット不要）**

上記出力で「cached evidence を使い DB エラーが出ない」ことを確認できれば手動デモ経路は疎通。Azure 資格情報を設定すれば同コマンドで LLM 解釈まで到達する（本 Step では課金回避のため実行しない）。

---

## Self-Review

- **Spec coverage:** 設計 1（main DI）→ Task 1。設計 2（git 追跡）→ Task 2 Step 1/5。設計 3（オフライン e2e）→ Task 2 Step 2-4。設計 4（手動デモ）→ Task 3。スコープ外（--rebuild/空DBガード）はタスク化せず。網羅。
- **Placeholder scan:** すべての code/コマンドステップに実コードと期待出力あり。TBD/TODO 無し。
- **Type consistency:** `_default_build_interpreter` と fake はいずれも `(interpreter, config)` を返し、`config.deployment` と `interpret_kg_evidence(dict)->dict` を一貫使用。`main` シグネチャは全タスクで `main(argv, *, build_interpreter=...)` に統一。
