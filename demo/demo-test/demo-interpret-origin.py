"""CLI demo: interpret demo MSP data with origin & plausibility judgment.

Derivative of ``demo-interpret.py`` that uses the demo-local interpretation
package (``demo.llm_interpretation``) instead of the production one, and renders
per-compound origin candidates and a sample-context biological-plausibility /
false-positive assessment.

Describe the sample origin via the ``LLM_USER_CONTEXT`` environment variable,
e.g. ``大腸がん患者の内壁（粘膜）由来サンプル``. Evidence building is cache-first,
identical to ``demo-interpret.py``.

Environment variables
---------------------
Required (always, for the LLM call):
    AZURE_OPENAI_ENDPOINT      e.g. https://<resource>.openai.azure.com
    AZURE_OPENAI_API_KEY       your Azure OpenAI API key
    AZURE_OPENAI_DEPLOYMENT    deployment name of a structured-output model
Optional:
    AZURE_OPENAI_API_VERSION   defaults to 2024-10-21
    LLM_OUTPUT_LANGUAGE        defaults to Japanese
    LLM_USER_CONTEXT           sample origin / context (defaults to empty)

Usage
-----
    python demo/demo-test/demo-interpret-origin.py
    python demo/demo-test/demo-interpret-origin.py --evidence path/to/kg_evidence.json
    python demo/demo-test/demo-interpret-origin.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Make the repository root importable when run as a script from anywhere.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.llm_interpretation import (  # noqa: E402
    AzureOpenAIInterpretationConfig,
    AzureOpenAIInterpreter,
)
from demo.llm_interpretation_input.build_demo_input_from_msp import (  # noqa: E402
    build_demo_data_from_msp_file,
)


_LLM_INPUT_ROOT = (
    REPO_ROOT / "massbank_rdf" / "data" / "llm_input_from_msp"
)

DEFAULT_INPUT_PATH = (
    _LLM_INPUT_ROOT / "input_files" / "MSBNK-LCSB-LU119906.msp"
)

DEFAULT_OUTPUT_ROOT = _LLM_INPUT_ROOT / "output_files"

EVIDENCE_FILENAME = "kg_evidence.json"

REQUIRED_ENV_VARS = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Interpret demo MSP data with origin & plausibility judgment: "
            "MSP -> KG evidence -> interpretation. Evidence building is cache-first."
        ),
    )
    parser.add_argument(
        "--input-file",
        dest="input_file",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"MSP input file to interpret (default: {DEFAULT_INPUT_PATH}).",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help=(
            "Directory where KG evidence is cached/built "
            "(default: <output_files>/<msp-stem>)."
        ),
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a fresh MassBank + KG lookup even if cached evidence exists.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help=(
            "Interpret this pre-built kg_evidence.json directly, skipping the "
            "MSP/build path. Overrides --input-file/--output-dir/--rebuild."
        ),
    )
    parser.add_argument("--top-n", dest="top_n", type=int, default=10)
    parser.add_argument("--kg-n", dest="kg_n", type=int, default=3)
    parser.add_argument("--kg-limit", dest="kg_limit", type=int, default=100)
    parser.add_argument(
        "--pathway-limit",
        dest="pathway_limit",
        type=int,
        default=100,
        help="Maximum number of PubChem pathways fetched per InChIKey.",
    )
    parser.add_argument(
        "--mz-tolerance", dest="mz_tolerance", type=float, default=0.01
    )
    parser.add_argument(
        "--min-matched-peaks", dest="min_matched_peaks", type=int, default=1
    )
    parser.add_argument(
        "--precursor-tolerance",
        dest="precursor_tolerance",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw interpretation result as JSON instead of text.",
    )
    return parser.parse_args(argv)


def default_output_dir(input_file: Path) -> Path:
    """Default cache/build directory for an MSP file: one dir per MSP stem."""
    return DEFAULT_OUTPUT_ROOT / Path(input_file).stem


def resolve_evidence_path(
    args: argparse.Namespace,
    *,
    builder=build_demo_data_from_msp_file,
) -> Path:
    """Return the KG evidence path to interpret, building it if needed."""
    if args.evidence is not None:
        return Path(args.evidence)

    input_file = Path(args.input_file)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir is not None
        else default_output_dir(input_file)
    )
    evidence_path = output_dir / EVIDENCE_FILENAME

    if evidence_path.is_file() and not args.rebuild:
        print(f"Using cached KG evidence: {evidence_path}", file=sys.stderr)
        return evidence_path

    if not input_file.is_file():
        print(f"MSP input file not found: {input_file}", file=sys.stderr)
        raise SystemExit(1)

    print(
        f"Building KG evidence from MSP: {input_file} -> {output_dir} "
        f"(this runs MassBank search + KG/SPARQL lookup)...",
        file=sys.stderr,
    )
    builder(
        input_file=input_file,
        output_dir=output_dir,
        run_kg_lookup=True,
        top_n=args.top_n,
        mz_tolerance=args.mz_tolerance,
        min_matched_peaks=args.min_matched_peaks,
        kg_n=args.kg_n,
        kg_limit=args.kg_limit,
        precursor_tolerance=args.precursor_tolerance,
        pathway_per_inchikey_limit=args.pathway_limit,
    )
    return evidence_path


def load_config_from_env() -> AzureOpenAIInterpretationConfig:
    """Build the interpreter config from environment variables."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        _exit_missing_env(missing)

    return AzureOpenAIInterpretationConfig(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].strip(),
        api_key=os.environ["AZURE_OPENAI_API_KEY"].strip(),
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"].strip(),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21").strip(),
        output_language=os.environ.get("LLM_OUTPUT_LANGUAGE", "Japanese").strip()
        or "Japanese",
        user_context=os.environ.get("LLM_USER_CONTEXT", ""),
    )


def _exit_missing_env(missing: list[str]) -> None:
    lines = [
        "Missing required environment variable(s):",
        *(f"  - {name}" for name in missing),
        "",
        "Set them for the current PowerShell session, e.g.:",
    ]
    example = {
        "AZURE_OPENAI_ENDPOINT": "https://<your-resource>.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "<your-api-key>",
        "AZURE_OPENAI_DEPLOYMENT": "<your-deployment-name>",
    }
    for name in missing:
        lines.append(f'  $env:{name} = "{example.get(name, "<value>")}"')
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(1)


def _default_build_interpreter():
    """Build the real Azure interpreter from environment configuration."""
    config = load_config_from_env()
    return AzureOpenAIInterpreter(config), config


def load_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file():
        print(f"Evidence file not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _print_list(title: str, items: Any, indent: str = "  ") -> None:
    if not items:
        return
    print(f"{indent}{title}:")
    if isinstance(items, list):
        for item in items:
            print(f"{indent}  - {item}")
    else:
        print(f"{indent}  {items}")


def _print_origin_candidates(candidates: Any, indent: str = "  ") -> None:
    if not candidates:
        return
    print(f"{indent}Origin candidates:")
    for candidate in candidates:
        origin = candidate.get("origin")
        likelihood = candidate.get("likelihood")
        provenance = candidate.get("provenance")
        rationale = candidate.get("rationale")
        print(
            f"{indent}  - {origin}  likelihood={likelihood}  "
            f"[{provenance}] — {rationale}"
        )
        _print_list("evidence", candidate.get("supporting_evidence"), indent + "    ")


def _print_plausibility(assessment: Any, indent: str = "  ") -> None:
    if not assessment:
        return
    verdict = assessment.get("plausibility")
    confidence = assessment.get("confidence")
    flag = " [FALSE POSITIVE]" if assessment.get("is_biological_false_positive") else ""
    print(f"{indent}Plausibility: {verdict} (conf={confidence}){flag}")
    if assessment.get("rationale"):
        print(f"{indent}  {assessment['rationale']}")


def render_text(result: dict[str, Any]) -> None:
    metadata = result.get("metadata", {})
    summary = result.get("summary")
    features = result.get("features", [])
    failures = result.get("failures", [])

    print("=" * 72)
    print("LLM INTERPRETATION")
    print("=" * 72)
    print(
        f"deployment={metadata.get('deployment')} "
        f"features={metadata.get('feature_count')} "
        f"succeeded={metadata.get('succeeded')} "
        f"failed={metadata.get('failed')}"
    )

    if summary:
        print("\n" + "-" * 72)
        print("SAMPLE SUMMARY")
        print("-" * 72)
        if summary.get("overview"):
            print(summary["overview"])
        _print_list("Shared pathways", summary.get("shared_pathways"))
        _print_list("Shared disease themes", summary.get("shared_disease_themes"))
        _print_list("Notable findings", summary.get("notable_findings"))
        _print_list("Likely false positives", summary.get("likely_false_positives"))
        if summary.get("origin_overview"):
            _print_list("Origin overview", summary["origin_overview"])
        _print_list("Caveats", summary.get("caveats"))

    for record in features:
        interpretation = record.get("interpretation", {})
        print("\n" + "-" * 72)
        print(f"FEATURE  {record.get('inchikey')}")
        print("-" * 72)
        if interpretation.get("compound_summary"):
            print(interpretation["compound_summary"])
        _print_plausibility(interpretation.get("sample_context_assessment"))
        _print_origin_candidates(interpretation.get("origin_candidates"))
        _print_list("Biological roles", interpretation.get("biological_roles"))
        _print_list("Pathway insights", interpretation.get("pathway_insights"))
        _print_list("Disease associations", interpretation.get("disease_associations"))
        if interpretation.get("biospecimen_notes"):
            _print_list("Biospecimen notes", interpretation["biospecimen_notes"])
        _print_list("Caveats", interpretation.get("caveats"))
        if interpretation.get("overall_assessment"):
            _print_list("Overall assessment", interpretation["overall_assessment"])

    if failures:
        print("\n" + "-" * 72)
        print("FAILURES")
        print("-" * 72)
        for failure in failures:
            print(f"  - {failure.get('inchikey')}: {failure.get('error')}")

    usage = metadata.get("usage_total") or {}
    if usage:
        print("\n" + "-" * 72)
        print(
            "Token usage: "
            f"prompt={usage.get('prompt_tokens')} "
            f"completion={usage.get('completion_tokens')} "
            f"total={usage.get('total_tokens')}"
        )


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


if __name__ == "__main__":
    raise SystemExit(main())
