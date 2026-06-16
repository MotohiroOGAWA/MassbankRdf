from __future__ import annotations

from dataclasses import dataclass

import gradio as gr


@dataclass(frozen=True)
class LlmConfigComponents:
    """Gradio components for LLM interpretation settings."""

    enabled: gr.Checkbox
    output_language: gr.Dropdown
    azure_openai_endpoint: gr.Textbox
    azure_openai_deployment: gr.Textbox
    azure_openai_api_version: gr.Textbox
    azure_openai_api_key: gr.Textbox
    user_context: gr.Textbox

    @property
    def inputs(self) -> list:
        """Return components as Gradio input list."""
        return [
            self.enabled,
            self.output_language,
            self.azure_openai_endpoint,
            self.azure_openai_deployment,
            self.azure_openai_api_version,
            self.azure_openai_api_key,
            self.user_context,
        ]


def create_llm_config_panel() -> LlmConfigComponents:
    """Create shared LLM interpretation config panel."""
    gr.HTML("<h3>LLM Interpretation</h3>")

    with gr.Row():
        llm_enabled = gr.Checkbox(
            label="Run LLM interpretation after KG lookup",
            value=False,
        )

        llm_output_language = gr.Dropdown(
            label="Output language",
            choices=[
                "English",
                "Japanese",
            ],
            value="English",
        )

    with gr.Row():
        azure_openai_endpoint = gr.Textbox(
            label="Azure OpenAI endpoint",
            placeholder="https://xxxxx.openai.azure.com/",
        )

        azure_openai_deployment = gr.Textbox(
            label="Azure OpenAI deployment",
            placeholder="gpt-4.1-mini",
        )

    with gr.Row():
        azure_openai_api_version = gr.Textbox(
            label="Azure OpenAI API version",
            value="2024-10-21",
        )

        azure_openai_api_key = gr.Textbox(
            label="Azure OpenAI API key",
            type="password",
        )

    llm_user_context = gr.Textbox(
        label="Interpretation context",
        lines=5,
        placeholder=(
            "Example: This sample is from palm oil oxidation experiment. "
            "Focus on odor-related metabolites and lipid oxidation."
        ),
    )

    return LlmConfigComponents(
        enabled=llm_enabled,
        output_language=llm_output_language,
        azure_openai_endpoint=azure_openai_endpoint,
        azure_openai_deployment=azure_openai_deployment,
        azure_openai_api_version=azure_openai_api_version,
        azure_openai_api_key=azure_openai_api_key,
        user_context=llm_user_context,
    )


def build_llm_config(
    *,
    enabled: bool,
    output_language: str,
    azure_openai_endpoint: str,
    azure_openai_deployment: str,
    azure_openai_api_version: str,
    azure_openai_api_key: str,
    user_context: str,
) -> dict:
    """Build serializable LLM config for session payload."""
    return {
        "enabled": bool(enabled),
        "provider": "azure_openai",
        "endpoint": (azure_openai_endpoint or "").strip(),
        "deployment": (azure_openai_deployment or "").strip(),
        "api_version": (azure_openai_api_version or "2024-10-21").strip(),
        "api_key": (azure_openai_api_key or "").strip(),
        "output_language": output_language or "Japanese",
        "user_context": user_context or "",
    }