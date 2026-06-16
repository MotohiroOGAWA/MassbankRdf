from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .kg_evidence_builder import (
    rehydrate_feature,
)
from .prompts import (
    DEFAULT_FEATURE_SYSTEM_PROMPT,
    DEFAULT_SUMMARY_SYSTEM_PROMPT,
    build_feature_user_prompt,
    build_summary_user_prompt,
)
from .schemas import (
    FeatureInterpretation,
    SampleInterpretationSummary,
)


@dataclass(frozen=True)
class AzureOpenAIInterpretationConfig:
    """Azure OpenAI configuration for GUI interpretation."""

    endpoint: str
    api_key: str
    deployment: str
    api_version: str = "2024-10-21"
    output_language: str = "Japanese"
    user_context: str = ""
    feature_system_prompt: str = DEFAULT_FEATURE_SYSTEM_PROMPT
    summary_system_prompt: str = DEFAULT_SUMMARY_SYSTEM_PROMPT


class AzureOpenAIInterpreter:
    """Run LLM interpretation using Azure OpenAI structured outputs."""

    def __init__(
        self,
        config: AzureOpenAIInterpretationConfig,
    ) -> None:
        self.config = config

    def _build_client(self):
        """Build Azure OpenAI client."""
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=self.config.endpoint,
            api_key=self.config.api_key,
            api_version=self.config.api_version,
        )

    def _parse(
        self,
        *,
        client: Any,
        system_prompt: str,
        user_content: str,
        schema: Any,
    ) -> tuple[Any, dict[str, Any]]:
        """Call Azure OpenAI structured output API."""
        completion = client.beta.chat.completions.parse(
            model=self.config.deployment,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            response_format=schema,
        )

        message = completion.choices[0].message

        if getattr(message, "refusal", None):
            raise RuntimeError(f"Model refused the request: {message.refusal}")

        if message.parsed is None:
            raise RuntimeError("Structured output parse failed: parsed=None")

        usage = completion.usage.model_dump() if completion.usage else {}

        return message.parsed, usage

    def interpret_kg_evidence(
        self,
        kg_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Interpret all KG evidence features and summarize them."""
        client = self._build_client()

        usage_total: dict[str, int] = {}
        feature_records: list[dict[str, Any]] = []
        interpretations: list[FeatureInterpretation] = []
        failures: list[dict[str, str]] = []

        features = kg_evidence.get("features", [])

        for feature in features:
            inchikey = str(feature.get("inchikey", ""))
            payload = rehydrate_feature(feature)

            try:
                user_prompt = build_feature_user_prompt(
                    feature_payload=payload,
                    user_context=self.config.user_context,
                    output_language=self.config.output_language,
                )

                interpretation, usage = self._parse(
                    client=client,
                    system_prompt=self.config.feature_system_prompt,
                    user_content=user_prompt,
                    schema=FeatureInterpretation,
                )

                self._accumulate_usage(usage_total, usage)

                payload_bytes = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")

                feature_records.append(
                    {
                        "inchikey": inchikey,
                        "interpretation": interpretation.model_dump(),
                        "input_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                        "usage": usage,
                    }
                )
                interpretations.append(interpretation)

            except Exception as exc:
                failures.append(
                    {
                        "inchikey": inchikey,
                        "error": str(exc),
                    }
                )

        summary = None

        if interpretations:
            try:
                summary_prompt = build_summary_user_prompt(
                    interpretations=[
                        interpretation.model_dump()
                        for interpretation in interpretations
                    ],
                    user_context=self.config.user_context,
                    output_language=self.config.output_language,
                )

                sample_summary, usage = self._parse(
                    client=client,
                    system_prompt=self.config.summary_system_prompt,
                    user_content=summary_prompt,
                    schema=SampleInterpretationSummary,
                )

                self._accumulate_usage(usage_total, usage)
                summary = sample_summary.model_dump()

            except Exception as exc:
                failures.append(
                    {
                        "inchikey": "__summary__",
                        "error": str(exc),
                    }
                )

        return {
            "metadata": {
                "source": "massbank_rdf_gui",
                "deployment": self.config.deployment,
                "api_version": self.config.api_version,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "feature_count": len(features),
                "succeeded": len(feature_records),
                "failed": len(failures),
                "usage_total": usage_total,
            },
            "summary": summary,
            "features": feature_records,
            "failures": failures,
        }

    def _accumulate_usage(
        self,
        total: dict[str, int],
        usage: dict[str, Any],
    ) -> None:
        """Accumulate token usage."""
        for key in [
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ]:
            value = usage.get(key)
            if value is not None:
                total[key] = total.get(key, 0) + int(value)