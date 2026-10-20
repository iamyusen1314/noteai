"""Test-only loopback API/static harness; never run as a deployment server.

Uses the existing isolated service fixture and explicit auth dependency override.
Uvicorn lifespan is OFF: no production startup, scheduler or worker is started.
All supplier transports are MockTransport; Python outbound connects are denied.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time
import uuid
from unittest import mock

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn
import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "model"))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = ""
from tests import test_cover_service as service_fixtures
import api
import billing
import cover_jobs as jobs
import cover_service as service
import cover_settings as settings
import db
import ark_media
import cover_runtime
import private_storage
from tests.test_cover_design import model_brief
from tests.test_cover_runtime import approved_qc


SOURCE_MANIFEST = Path("/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/source-nine-readonly/SOURCE-READONLY-INVENTORY.json")


def v2_sources(fixture):
    """Explicit local-only real-photo fixture; fail rather than substitute images."""
    manifest = Path(os.environ.get("NOTEAI_COVER_HTTP_SOURCE_MANIFEST", str(SOURCE_MANIFEST)))
    records = json.loads(manifest.read_text())["files"]
    if len(records) != 9 or [item["index"] for item in records] != list(range(1, 10)):
        raise ValueError("v2 fixture requires the ordered nine-photo inventory")
    result = []
    for item in records:
        payload = Path(item["path"]).read_bytes()
        if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise ValueError("v2 fixture source differs from readonly inventory")
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.size != (item["width"], item["height"]):
                raise ValueError("v2 fixture dimensions differ from inventory")
        reference = private_storage.store_media_bytes(fixture.fixture.user, purpose="image",
            content_type="image/png" if payload.startswith(b"\x89PNG") else "image/jpeg",
            payload=payload, item_count=1, ttl_seconds=86400)
        result.append({**item, "media_ref": reference.id})
    return result


def v2_plan(source_refs):
    """Deterministic director response, matching the inspected two-photo sample.

    Real photos seven and nine are retained by the actual product renderer.
    This is a wire fixture, not evidence of a real model's design judgment.
    """
    selected = [source_refs[6], source_refs[8]]
    brief = model_brief(selected[0])
    brief.update(industry="休闲娱乐", subtype="庭院汤泉", reader_question="庭院环境有什么看点",
        visual_strategy="两幅原图明确分景，文字层级置于图间，保留真实主体",
        source_reasons=[{"source_ref": reference, "reason": "实拍清晰且主体完整"} for reference in selected])
    return {"schema_version": 2, "route": "photo", "text": "高楼里的\n日式庭院汤泉",
        "background_color": "#F6F1E8", "design_brief": brief,
        "photos": [
            {"source_ref": selected[0], "crop": [0, 0, 1, 1],
             "subject_bbox": [.3, .2, .85, .83], "bbox": [.015, .015, .985, .43]},
            {"source_ref": selected[1], "crop": [0, 0, 1, 1],
             "subject_bbox": [.04, .15, .96, .95], "bbox": [.015, .58, .985, .995]}],
        "text_layers": [
            {"text": "高楼里的", "bbox": [.055, .437, .945, .486], "font_id": "SourceHanSerifSC-Regular",
             "font_size": 66, "align": "left", "color": "#294A3D"},
            {"text": "日式庭院汤泉", "bbox": [.055, .484, .945, .579], "font_id": "SourceHanSansSC-Bold",
             "font_size": 156, "align": "left", "color": "#294A3D", "stroke_width": 1}]}


def v2_runtime(fixture):
    def run(**kwargs):
        fixture.runtime_calls += 1
        design = v2_plan([source["media_ref"] for source in kwargs["sources"]])
        stages = []

        def handle(request):
            payload = json.loads(request.content)
            if payload["model"] != ark_media.MODEL or not request.url.path.endswith("/chat/completions"):
                raise AssertionError("only the existing Lite design/QC wire may be called")
            stage = "design" if not stages else "qc"
            stages.append(stage)
            parts = payload["messages"][0]["content"]
            image_count = sum(part.get("type") == "image_url" for part in parts)
            if len(stages) > 2 or image_count != (9 if stage == "design" else 4):
                raise AssertionError("unexpected v2 supplier call count/source visibility")
            fixture.requests.append({"path": request.url.path, "model": payload["model"],
                "job_id": kwargs["job_id"], "stage": stage, "image_parts": image_count})
            if stage == "design" and not fixture.browser_design_release.wait(15):
                raise AssertionError("browser did not release the local design-state observation gate")
            content = design if stage == "design" else approved_qc()
            return httpx.Response(200, json={"model": ark_media.MODEL,
                "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
                    "content": json.dumps(content, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 800, "completion_tokens": 160,
                    "prompt_tokens_details": {"cached_tokens": 0}}})

        transport = httpx.MockTransport(handle)
        return cover_runtime.run_cover(**kwargs, design_transport=transport, qc_transport=transport,
            seedream_transport=transport)
    return run


def main():
    mode = os.environ.get("NOTEAI_COVER_HTTP_MODE", "legacy_v1")
    if mode not in {"legacy_v1", "source_photo_v2"}:
        raise ValueError("explicit supported cover harness mode required")
    fixture = service_fixtures.CoverServiceIntegrationTests()
    fixture.setUp()
    fixture.browser_design_release = threading.Event()
    sources = v2_sources(fixture) if mode == "source_photo_v2" else [{"media_ref": fixture.fixture.source.id}]
    if mode == "source_photo_v2":
        fixture.fixture.policy = {**fixture.fixture.policy, "design_version": 2}
    token = "loopback-cover-fixture-token"
    routes_before = list(api.app.router.routes)
    overrides_before = dict(api.app.dependency_overrides)
    readiness = mock.patch.object(settings, "readiness", return_value=(True, ""))
    policy = mock.patch.object(settings, "policy_snapshot", return_value=fixture.fixture.policy)
    readiness.start()
    policy.start()
    owner = dict(db.fetchone("SELECT * FROM users WHERE id=?", (fixture.fixture.user,)))
    reports = []
    for label in ("PC", "H5"):
        report_id = str(uuid.uuid4())
        title = "高楼里的日式庭院汤泉" if mode == "source_photo_v2" else "周末咖啡时光"
        original = label + (" 本人九图实拍素材" if mode == "source_photo_v2" else " 本人咖啡素材")
        description = "本人庭院与汤泉实拍素材，仅作本地离线链路验证。" if mode == "source_photo_v2" else "这是程序合成素材。"
        domain = "休闲娱乐" if mode == "source_photo_v2" else "美食"
        result = {"ai_diagnosis": "离线夹具已保存原报告，不是真实模型诊断验收。",
            "suggested_titles": [title], "ces_percentile": 73, "composite_score": 73,
            "grade": "良好", "weaknesses": [], "features": {},
            "expert_opinions": [{"role": "视觉专家", "opinion": "用本人素材保留完整主体，按实际照片比例构图。",
                "suggestions": ["不虚构设施、菜品或服务"]}],
            "source_media_refs": [item["media_ref"] for item in sources],
            "source_media_items": [{"input_field": "cover_images" if mode == "source_photo_v2" else "cover_image",
                "image_index": index + 1, "media_ref": item["media_ref"]} for index, item in enumerate(sources)],
            "input_diagnostics": {"original_title": original, "original_desc": description,
                "has_independent_cover": True, "score_scope": "complete_note_input", "missing_dimensions": []}}
        db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,ces_percentile,composite_score,grade,diagnosis_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (report_id, owner["id"], original, domain, 73, 73, "良好",
             json.dumps(result, ensure_ascii=False), fixture.fixture.now.isoformat()))
        reports.append({"label": label, "report_id": report_id, "report_type": "analyze"})

    async def test_owner(request: Request):
        if request.headers.get("authorization") != "Bearer " + token:
            raise HTTPException(401, "local fixture identity required")
        return dict(owner)

    api.app.dependency_overrides[api._auth.get_current_user] = test_owner

    @api.app.get("/NoteAI_Pro_Demo_Framer.html", include_in_schema=False)
    async def test_html():
        return FileResponse(ROOT / "NoteAI_Pro_Demo_Framer.html", media_type="text/html")

    @api.app.get("/runtime-config.js", include_in_schema=False)
    async def runtime_config():
        return Response("window.NOTEAI_API_BASE=location.origin;window.NOTEAI_PUBLIC_PRODUCT=false;", media_type="application/javascript")

    @api.app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    api.app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="cover_test_assets")

    @api.app.get("/__cover_test__/state", include_in_schema=False)
    async def state():
        cover_rows = [dict(row) for row in db.fetchall("SELECT id,report_id,status,stage,usage_id,asset_revision FROM cover_jobs ORDER BY created_at,id")]
        usage_rows = [dict(row) for row in db.fetchall("SELECT id,operation,credits_used AS charged_credits,cost_mode,actual_model_cost_rmb,estimated_cost_rmb FROM usage_records WHERE operation='cover_generate' ORDER BY recorded_at,id")]
        return {"reports": reports, "owner_id": owner["id"], "token": token,
            "jobs": cover_rows, "usage": usage_rows,
            "mode": mode, "sources": sources,
            "layouts": {row["id"]: jobs.get_layout(owner["id"], row["id"]) for row in cover_rows if row["status"] == "completed"},
            "supplier_requests": fixture.requests, "balances": fixture.fixture.balances(),
            "model_calls": db.fetchone("SELECT count(*) FROM public_trial_calls")[0],
            "image_calls": db.fetchone("SELECT count(*) FROM cover_image_usage")[0],
            "auth": "TEST_ONLY_DEPENDENCY_OVERRIDE_NOT_REAL_LOGIN", "supplier": "MOCK_TRANSPORT_NO_EXTERNAL_MODEL"}

    @api.app.post("/__cover_test__/run-next", include_in_schema=False)
    async def run_next():
        fixture.browser_design_release.clear()
        runtime = v2_runtime(fixture) if mode == "source_photo_v2" else fixture.wrapper(route="photo")
        result = await asyncio.to_thread(service.run_next, runtime=runtime)
        return {"result": result}

    @api.app.post("/__cover_test__/release-design", include_in_schema=False)
    async def release_design():
        fixture.browser_design_release.set()
        return {"ok": True}

    @api.app.post("/__cover_test__/stop", include_in_schema=False)
    async def stop():
        fixture.browser_design_release.set()
        server.should_exit = True
        return {"ok": True}

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(api.app, host="127.0.0.1", port=port, lifespan="off", loop="asyncio", http="h11", log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="cover-loopback-api", daemon=True)
    signal.signal(signal.SIGTERM, lambda *_args: setattr(server, "should_exit", True))
    signal.signal(signal.SIGINT, lambda *_args: setattr(server, "should_exit", True))
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        if not server.started:
            raise RuntimeError("loopback uvicorn did not start")
        print(json.dumps({"origin": "http://127.0.0.1:" + str(port), "reports": reports,
            "owner_id": owner["id"], "token": token, "mode": mode, "source_count": len(sources),
            "title": title}), flush=True)
        while thread.is_alive():
            thread.join(timeout=.2)
    finally:
        fixture.browser_design_release.set()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        api.app.router.routes[:] = routes_before
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides_before)
        policy.stop()
        readiness.stop()
        fixture.tearDown()


if __name__ == "__main__":
    main()
