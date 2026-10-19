"""Test-only loopback API/static harness; never run as a deployment server.

Uses the existing isolated service fixture and explicit auth dependency override.
Uvicorn lifespan is OFF: no production startup, scheduler or worker is started.
All supplier transports are MockTransport; Python outbound connects are denied.
"""
from __future__ import annotations

import asyncio
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


def main():
    fixture = service_fixtures.CoverServiceIntegrationTests()
    fixture.setUp()
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
        result = {"ai_diagnosis": "离线合成素材的已保存原报告，不是真实模型诊断验收。",
            "suggested_titles": ["周末咖啡时光"], "ces_percentile": 73, "composite_score": 73,
            "grade": "良好", "weaknesses": [], "features": {},
            "expert_opinions": [{"role": "视觉专家", "opinion": "用本人素材保留完整主体，上下留文字空间。",
                "suggestions": ["不虚构设施、菜品或服务"]}],
            "source_media_refs": [fixture.fixture.source.id],
            "source_media_items": [{"input_field": "cover_image", "image_index": 1,
                "media_ref": fixture.fixture.source.id}],
            "input_diagnostics": {"original_title": label + " 本人咖啡素材", "original_desc": "这是程序合成素材。",
                "has_independent_cover": True, "score_scope": "complete_note_input", "missing_dimensions": []}}
        db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,ces_percentile,composite_score,grade,diagnosis_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (report_id, owner["id"], label + " 本人咖啡素材", "美食", 73, 73, "良好",
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
            "supplier_requests": fixture.requests, "balances": fixture.fixture.balances(),
            "model_calls": db.fetchone("SELECT count(*) FROM public_trial_calls")[0],
            "image_calls": db.fetchone("SELECT count(*) FROM cover_image_usage")[0],
            "auth": "TEST_ONLY_DEPENDENCY_OVERRIDE_NOT_REAL_LOGIN", "supplier": "MOCK_TRANSPORT_NO_EXTERNAL_MODEL"}

    @api.app.post("/__cover_test__/run-next", include_in_schema=False)
    async def run_next():
        result = await asyncio.to_thread(service.run_next, runtime=fixture.wrapper(route="photo"))
        return {"result": result}

    @api.app.post("/__cover_test__/stop", include_in_schema=False)
    async def stop():
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
            "owner_id": owner["id"], "token": token}), flush=True)
        while thread.is_alive():
            thread.join(timeout=.2)
    finally:
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
