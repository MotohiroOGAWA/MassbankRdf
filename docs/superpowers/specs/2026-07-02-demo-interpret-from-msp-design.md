# Design: `demo-interpret.py` — interpret demo MSP data end-to-end

Date: 2026-07-02
Status: Approved

## Problem

`demo/demo-test/demo-interpret.py` today only loads a pre-built compact
`kg_evidence.json` and sends it to `AzureOpenAIInterpreter`. It cannot start
from an MSP spectrum. The goal is to let the demo interpret the demo MSP data
directly: MSP → MassBank search + KG/DB lookup → LLM interpretation.

All database / knowledge-graph search must stay in `massbank_rdf/` code
(invoked via the existing `demo/llm_interpretation_input/` builders). The demo
script only orchestrates.

## Flow (per run)

1. Resolve an MSP input file. Default:
   `massbank_rdf/data/llm_input_from_msp/input_files/MSBNK-LCSB-LU119906.msp`.
   Override with `--input-file`.
2. Resolve an output dir. Default:
   `massbank_rdf/data/llm_input_from_msp/output_files/<msp-stem>/`.
   Override with `--output-dir`.
3. **Cache-first evidence:** if `<output-dir>/kg_evidence.json` exists and
   `--rebuild` was not passed, load it. Otherwise call
   `build_demo_data_from_msp_file(...)`, which runs MassBank search + KG/SPARQL
   lookup and writes `kg_evidence.json`, then load that file.
4. Send the compact evidence to `AzureOpenAIInterpreter.interpret_kg_evidence`
   and render via the existing text renderer (or `--json`).

## CLI surface

- `--input-file PATH` — MSP input (default: demo MSP).
- `--output-dir PATH` — where evidence is cached/built (default: derived from
  the MSP stem under `output_files/`).
- `--rebuild` — force re-running DB/KG search even if a cached
  `kg_evidence.json` exists.
- `--evidence PATH` — escape hatch: interpret an arbitrary pre-built evidence
  JSON directly, skipping the MSP/build path (preserves prior behavior). When
  given, `--input-file` / `--output-dir` / `--rebuild` are ignored.
- Search pass-through (forwarded to the builder): `--top-n`, `--kg-n`,
  `--kg-limit`, `--pathway-limit`, `--mz-tolerance`, `--min-matched-peaks`,
  `--precursor-tolerance`.
- `--json` — raw JSON output (unchanged).

## Components / boundaries

- `resolve_evidence(args) -> Path`: pure-ish orchestration deciding whether to
  reuse the cached evidence or trigger a build, returning the evidence path.
  Isolated so it can be unit-tested with a stub builder and a temp dir.
- `build_demo_data_from_msp_file(...)`: unchanged, reused as-is. Owns all DB/KG
  search.
- `AzureOpenAIInterpreter` + `render_text` / `load_config_from_env`: unchanged.

## Requirements to run

- Cache hit: only Azure OpenAI credentials.
- Fresh build: also requires a populated MassBank DB and live SPARQL endpoints
  (via GUI endpoint settings), same as the existing build script.

## Testing

- Unit test `resolve_evidence`:
  - cache hit (evidence exists, no `--rebuild`) → returns path, builder not
    called;
  - cache miss → builder called, returns produced path;
  - `--rebuild` with existing cache → builder called.
  Builder is stubbed; no DB/LLM/network involved. The hyphenated module is
  loaded via `importlib`.
- Manual: `--help` renders; `--evidence <existing>` reproduces prior behavior.

## Out of scope

- Batch/multi-MSP interpretation.
- Changing evidence schema or the interpreter.
