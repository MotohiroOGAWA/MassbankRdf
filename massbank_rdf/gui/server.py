from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import uuid

import gradio as gr
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from .session_store import TemporarySessionStore
from .settings import (
    create_kg_lookup_service_from_endpoint_settings,
)

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

GUI_ROOT = Path(__file__).resolve().parent
MSP_JOB_OUTPUT_ROOT = Path(tempfile.gettempdir()) / "massbank_rdf_msp_jobs"

from .app import create_app as create_home_app
from .workflows.kg_search.page import create_app as create_kg_app
from .workflows.kg_search.input_page import create_app as create_kg_input_app
from .workflows.kg_search.result_page import create_app as create_kg_result_app
from .workflows.common_peak_annotation.page import create_app as create_common_peak_app
from .workflows.common_peak_annotation.input_page import create_app as create_common_peak_input_app
from .workflows.common_peak_annotation.result_page import create_app as create_common_peak_result_app
from .workflows.msp_kg.input_page import create_app as create_msp_kg_input_app
from .workflows.msp_kg.processor import build_batch_processor

APP_LAYOUT_STYLES = """
html,
body {
    color-scheme: light !important;
    background: #ffffff !important;
    color: #1f2933 !important;
}

footer {
    display: none !important;
}

.gradio-container {
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    background: #ffffff !important;
    color: #1f2933;
    font-family: Arial, Helvetica, sans-serif;
}

.massbank-page {
    box-sizing: border-box;
    width: 100%;
    padding: 24px clamp(18px, 4vw, 58px) 46px;
}

.massbank-hero {
    border-top: 5px solid #1f5f8b;
    background: linear-gradient(#f7fbfd, #ffffff);
    padding: 30px 4px 22px;
    border-bottom: 1px solid #d8e4eb;
}

.massbank-kicker {
    color: #c46a1a;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: .04em;
    text-transform: uppercase;
    margin-bottom: 8px;
}

.massbank-title-block h1 {
    color: #174f78;
    font-size: 42px;
    margin: 0 0 8px;
    font-weight: 700;
}

.massbank-title-block p {
    max-width: 980px;
    color: #3e4c59;
    font-size: 16px;
    line-height: 1.55;
    margin: 0;
}

.massbank-section {
    padding-top: 28px;
}

.massbank-section h2,
.massbank-page-heading h1 {
    color: #174f78;
    font-size: 28px;
    margin: 0 0 8px;
    font-weight: 700;
}

.massbank-page-heading {
    margin: 14px 0 22px;
    border-bottom: 1px solid #d8e4eb;
    padding-bottom: 14px;
}

.massbank-page-heading p {
    color: #52616d;
    margin: 0;
}

.massbank-rule {
    height: 1px;
    background: #d8e4eb;
    margin: 10px 0 18px;
}

.massbank-tool-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 22px 42px;
    width: 100%;
}

.massbank-tool-item {
    border-left: 4px solid #e6a23c;
    padding: 2px 0 4px 14px;
}

.massbank-tool-item h3 {
    color: #174f78;
    font-size: 18px;
    margin: 0 0 8px;
}

.massbank-tool-item h3 a {
    color: #174f78;
    text-decoration: none;
    font-weight: 700;
}

.massbank-tool-item h3 a:hover {
    color: #0b67a3;
    text-decoration: underline;
}

.massbank-tool-item p {
    margin: 0 0 10px;
    color: #3e4c59;
    line-height: 1.45;
    max-width: 820px;
}

.massbank-demo-box {
    background: #f7fbfd;
    border: 1px solid #d8e4eb;
    border-left: 4px solid #1f5f8b;
    padding: 10px 12px;
    color: #3e4c59;
    font-size: 14px;
    line-height: 1.5;
}

.massbank-link-nav {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 14px;
    font-size: 14px;
}

.massbank-link-nav a {
    color: #0b67a3;
    text-decoration: none;
    font-weight: 700;
}

.massbank-link-nav a:hover {
    text-decoration: underline;
}

#massbank-basic-search-button {
    width: 100% !important;
    background: #ffffff !important;
    color: #ff5126 !important;
    border: 2px solid #ff5126 !important;
    border-radius: 5px !important;
    font-weight: 700 !important;
    padding: 10px 16px !important;
    box-shadow: none !important;
}

#massbank-basic-search-button:hover {
    background: #ff5126 !important;
    color: #ffffff !important;
    border-color: #ff5126 !important;
}
"""

def _with_app_layout(blocks: gr.Blocks) -> gr.Blocks:
    blocks.css = "\n\n".join(filter(None, [APP_LAYOUT_STYLES, blocks.css]))
    blocks.config = blocks.get_config_file()
    return blocks


def create_server() -> FastAPI:
    app = FastAPI()

    kg_session_store = TemporarySessionStore(
        ttl_seconds=60 * 60,
    )
    common_peak_session_store = TemporarySessionStore(
        ttl_seconds=60 * 60,
    )
    msp_kg_session_store = TemporarySessionStore(ttl_seconds=60 * 60)

    kg_lookup_service = create_kg_lookup_service_from_endpoint_settings(
        timeout=600,
    )
    msp_batch_processor = build_batch_processor(
        msp_kg_session_store,
        kg_lookup_service,
    )

    @app.middleware("http")
    async def add_session_ids(
        request: Request,
        call_next,
    ) -> Response:
        kg_session_id = request.cookies.get("kg_session_id")
        common_peak_session_id = request.cookies.get("common_peak_session_id")
        msp_kg_session_id = request.cookies.get("msp_kg_session_id")

        response = await call_next(request)

        if not kg_session_id:
            response.set_cookie(
                key="kg_session_id",
                value=uuid.uuid4().hex,
                httponly=True,
                samesite="lax",
                max_age=60 * 60,
            )

        if not common_peak_session_id:
            response.set_cookie(
                key="common_peak_session_id",
                value=uuid.uuid4().hex,
                httponly=True,
                samesite="lax",
                max_age=60 * 60,
            )

        if not msp_kg_session_id:
            response.set_cookie(
                key="msp_kg_session_id",
                value=uuid.uuid4().hex,
                httponly=True,
                samesite="lax",
                max_age=60 * 60,
            )

        return response

    @app.get("/kg")
    @app.get("/kg/")
    def redirect_kg():
        return RedirectResponse(url="/kg/input/")

    @app.get("/common-peak")
    @app.get("/common-peak/")
    def redirect_common_peak():
        return RedirectResponse(url="/common-peak/input/")

    @app.get("/msp-kg")
    @app.get("/msp-kg/")
    def redirect_msp_kg():
        return RedirectResponse(url="/msp-kg/input/")

    gr.mount_gradio_app(
        app,
        _with_app_layout(
            create_msp_kg_input_app(
                session_store=msp_kg_session_store,
                kg_lookup_service=kg_lookup_service,
            )
        ),
        path="/msp-kg/input",
        allowed_paths=[str(GUI_ROOT)],
    )

    gr.mount_gradio_app(
        app,
        _with_app_layout(
            create_kg_result_app(
                session_store=msp_kg_session_store,
                kg_lookup_service=kg_lookup_service,
                session_cookie_name="msp_kg_session_id",
                workflow_title="MSP Knowledge Graph Annotation",
                input_path="/msp-kg/input/",
                preload_fn=msp_batch_processor,
            )
        ),
        path="/msp-kg/result",
        allowed_paths=[str(GUI_ROOT), str(MSP_JOB_OUTPUT_ROOT)],
    )

    gr.mount_gradio_app(
        app,
        _with_app_layout(
            create_kg_input_app(session_store=kg_session_store)
        ),
        path="/kg/input",
        allowed_paths=[str(GUI_ROOT)],
    )

    gr.mount_gradio_app(
        app,
        _with_app_layout(
            create_kg_result_app(
                session_store=kg_session_store,
                kg_lookup_service=kg_lookup_service,
            )
        ),
        path="/kg/result",
        allowed_paths=[str(GUI_ROOT)],
    )

    gr.mount_gradio_app(
        app,
        _with_app_layout(
            create_common_peak_input_app(
                session_store=common_peak_session_store,
            )
        ),
        path="/common-peak/input",
        allowed_paths=[str(GUI_ROOT)],
    )

    gr.mount_gradio_app(
        app,
        _with_app_layout(
            create_common_peak_result_app(
                session_store=common_peak_session_store,
                kg_lookup_service=kg_lookup_service,
            )
        ),
        path="/common-peak/result",
        allowed_paths=[str(GUI_ROOT)],
    )

    gr.mount_gradio_app(
        app,
        _with_app_layout(create_home_app()),
        path="/",
        allowed_paths=[str(GUI_ROOT)],
    )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MassBank RDF GUI app.")
    parser.add_argument("--port", type=int, default=7860, help="Port to listen on.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(create_server(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
