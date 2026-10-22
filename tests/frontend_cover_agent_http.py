"""Loopback-only v3 browser fixture: real API/SDK/CLI/accounting, model HTTP mocked.

This deliberately uses nine synthetic photographs, never merchant material.
One existing report and one completed cover are shared by PC/H5 browser checks.
No production startup, scheduler, extra cover worker or external model runs.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
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

import httpx
import uvicorn
from fastapi import HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "model"))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = ""

import api
import cover_agent_runtime as runtime
import cover_jobs as jobs
import cover_service as service
import cover_settings as settings
import db
import private_storage
from tests import test_cover_service as service_fixtures
from tests.test_cover_agent_runtime import ScriptedBridge, synthetic_png


TITLE = "原照独立图层中文排字测试"
TOKEN = "loopback-synthetic-cover-agent-only"


class MeteredScriptedBridge(ScriptedBridge):
    """Use the scripted responder only behind the real metered Ark transport."""
    instances = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wire_requests = []
        self.response_stage = None
        self.model_transport = httpx.MockTransport(self.respond_model)
        self.image_transport = httpx.MockTransport(self.respond_image)

    def model(self, payload, stage="design"):
        self.response_stage = stage
        # This owns the actual ordinal, before hook, physical admission, budget,
        # provider transport, usage row and known/UNKNOWN handling.
        return runtime.Bridge.model(self, payload, stage=stage)

    def respond_model(self, request):
        if request.url.path != "/api/v3/chat/completions":
            raise AssertionError("Unexpected model route in local fixture")
        ordinal = self.ordinal
        # ScriptedBridge's original test helper increments its own ordinal.
        # Reuse its response logic at this already-admitted ordinal, leaving
        # the production counter exactly unchanged rather than double counting.
        self.ordinal = ordinal - 1
        try:
            body, scripted_call_id = ScriptedBridge.model(self, json.loads(request.content), self.response_stage)
            if self.ordinal != ordinal:
                raise AssertionError("Scripted response changed the physical ordinal")
        finally:
            self.ordinal = ordinal
        call_id = str(uuid.uuid5(uuid.UUID(self.job_id),
            "editable:" + self.response_stage + ":" + str(ordinal)))
        row = db.fetchone("SELECT state FROM public_trial_calls WHERE id=?", (call_id,))
        if not row or row["state"] != "dispatched":
            raise AssertionError("Synthetic model response lacks the real original dispatch")
        body["usage"]["prompt_tokens_details"] = {"cached_tokens": 0}
        self.wire_requests.append({"stage": self.response_stage, "ordinal": ordinal,
            "physical_call_id": call_id, "scripted_response_id": scripted_call_id,
            "input_bound": self.requests[-1]["input_bound"],
            "image_hashes": self.requests[-1]["image_sha256"], "http_status": 200})
        return httpx.Response(200, json=body)

    def respond_image(self, request):
        if request.url.path != "/api/v3/images/generations":
            raise AssertionError("Unexpected concept route in local fixture")
        payload = json.loads(request.content)
        inputs = payload.get("image")
        if not isinstance(inputs, list) or len(inputs) != 9:
            raise AssertionError("Concept fixture must receive all nine actual source bytes")
        actual = {hashlib.sha256(base64.b64decode(value.split(",", 1)[1], validate=True)).hexdigest()
            for value in inputs}
        if actual != {source["sha256"] for source in self.sources}:
            raise AssertionError("Concept source identity differs from the original nine")
        concept = synthetic_png((1776, 2368), "#A1A8B1")
        self.wire_requests.append({"stage": "image", "input_images": 9,
            "model": payload["model"], "http_status": 200})
        return httpx.Response(200, json={"model": payload["model"],
            "data": [{"b64_json": base64.b64encode(concept).decode(), "size": "1776x2368"}],
            "usage": {"input_images": 9, "generated_images": 1}},
            headers={"x-request-id": "synthetic-local-agent-concept"})


def prepare(fixture):
    """Build one genuine local delivery before exposing its existing report UI."""
    references = []
    for index in range(9):
        color = "#" + format(0x406050 + index * 0x070309, "06x")
        raw = synthetic_png((2400, 1800), color)
        ref = private_storage.store_media_bytes(fixture.fixture.user, purpose="image", content_type="image/png",
            payload=raw, item_count=1, ttl_seconds=86400)
        references.append(ref.id)
    config = settings.editable_defaults()
    config.update(enabled=True, account_verified=True, account_evidence_ref="SYNTHETIC_LOCAL_HTTP_FIXTURE")
    fixture.fixture.policy = settings.policy_snapshot(config)
    result = {"ai_diagnosis": "离线合成九图报告，仅验证功能链路，不是商家或审美验收。",
        "suggested_titles": [TITLE], "ces_percentile": 73, "composite_score": 73,
        "grade": "良好", "weaknesses": [], "features": {},
        "expert_opinions": [{"role": "视觉专家", "opinion": "这些是程序合成技术图片。",
            "suggestions": ["保留原始图片及真实HTML文字，不编写商家事实。"]}],
        "source_media_refs": references,
        "source_media_items": [{"input_field": "cover_images", "image_index": index + 1, "media_ref": ref}
            for index, ref in enumerate(references)],
        "input_diagnostics": {"original_title": TITLE, "original_desc": "合成九图技术测试。",
            "has_independent_cover": True, "score_scope": "complete_note_input", "missing_dimensions": []}}
    db.execute("UPDATE saved_diagnoses SET note_title=?,domain=?,ces_percentile=73,composite_score=73,"
        "grade='良好',diagnosis_json=? WHERE id=? AND user_id=?",
        (TITLE, "其他", json.dumps(result, ensure_ascii=False), fixture.fixture.report, fixture.fixture.user))
    snapshot = {"title": TITLE, "body": "合成技术图验证，非真实商家样本。", "title_variants": [],
        "domain": "其他", "visual_advice": "全部为合成图片，保留原图身份及独立中文文字。",
        "source_items": result["source_media_items"]}
    task = fixture.fixture.submit(key="local-agent-http-one-original", source_refs=references, input_snapshot=snapshot)
    claim = jobs.claim_job(task["job_id"])
    if claim is None:
        raise RuntimeError("Local synthetic cover was not claimed")
    def run(**kwargs):
        return runtime.run_cover(**kwargs, bridge_class=MeteredScriptedBridge)
    completed = service._run_claim(claim, runtime=run)
    if not completed or completed["status"] != "completed":
        raise RuntimeError("Local synthetic metered SDK cover did not complete: "
            + json.dumps(completed, ensure_ascii=False))
    physical = db.fetchall("SELECT state,model_usage_record_id FROM public_trial_calls WHERE usage_record_id=?",
        (claim["charge"]["usage_id"],))
    if (len(physical) != 9 or any(row["state"] != "responded" for row in physical)
            or sum(row["model_usage_record_id"] is not None for row in physical) != 8
            or completed["billing"]["credits_used"] != 8):
        raise RuntimeError("Local synthetic original accounting contract failed")
    return {"report_id": fixture.fixture.report, "report_type": "analyze", "job_id": task["job_id"],
        "title": TITLE, "source_refs": references, "usage_id": claim["charge"]["usage_id"]}


def main():
    if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES"):
        raise RuntimeError("Explicit approved task-local SDK path is required")
    fixture = service_fixtures.CoverServiceIntegrationTests()
    fixture.setUp()
    routes_before = list(api.app.router.routes)
    overrides_before = dict(api.app.dependency_overrides)
    readiness = mock.patch.object(settings, "readiness", return_value=(True, ""))
    policy = None
    sock = None
    server = None
    thread = None
    try:
        delivery = prepare(fixture)
        policy = mock.patch.object(settings, "policy_snapshot", return_value=fixture.fixture.policy)
        readiness.start()
        policy.start()
        owner = dict(db.fetchone("SELECT * FROM users WHERE id=?", (fixture.fixture.user,)))
        async def test_owner(request: Request):
            if request.headers.get("authorization") != "Bearer " + TOKEN:
                raise HTTPException(401, "Synthetic loopback fixture identity required")
            return dict(owner)
        api.app.dependency_overrides[api._auth.get_current_user] = test_owner

        @api.app.get("/NoteAI_Pro_Demo_Framer.html", include_in_schema=False)
        async def html():
            text = (ROOT / "NoteAI_Pro_Demo_Framer.html").read_text()
            fixture_auth = "<script>localStorage.setItem('noteai_token'," + json.dumps(TOKEN) + ");</script>"
            return Response(text.replace("<head>", "<head>" + fixture_auth, 1), media_type="text/html")

        @api.app.get("/runtime-config.js", include_in_schema=False)
        async def runtime_config():
            return Response("window.NOTEAI_API_BASE=location.origin;window.NOTEAI_PUBLIC_PRODUCT=false;",
                media_type="application/javascript")

        @api.app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            return Response(status_code=204)

        api.app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="cover_agent_test_assets")

        @api.app.get("/__cover_agent_test__/state", include_in_schema=False)
        async def state():
            job = jobs.get_job(owner["id"], delivery["job_id"])
            return {"delivery": delivery, "job": job,
                "jobs": [dict(row) for row in db.fetchall("SELECT id,report_id,status,stage,usage_id,asset_revision FROM cover_jobs")],
                "usage": [dict(row) for row in db.fetchall("SELECT id,operation,credits_used,cost_mode,actual_model_cost_rmb "
                    "FROM usage_records WHERE operation='cover_generate'")],
                "balances": fixture.fixture.balances(),
                "model_calls": db.fetchone("SELECT count(*) FROM public_trial_calls")[0],
                "image_calls": db.fetchone("SELECT count(*) FROM cover_image_usage")[0],
                "supplier_requests": MeteredScriptedBridge.instances[-1].wire_requests,
                "auth": "SYNTHETIC_DEPENDENCY_OVERRIDE_NOT_REAL_LOGIN",
                "supplier": "MOCK_TRANSPORT_REAL_LOCAL_LEDGER_SDK_AND_CLI",
                "real_model_calls": 0, "merchant_materials": 0}

        @api.app.post("/__cover_agent_test__/stop", include_in_schema=False)
        async def stop():
            server.should_exit = True
            return {"ok": True}

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port,
            lifespan="off", loop="asyncio", http="h11", log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]},
            name="cover-agent-loopback", daemon=True)
        signal.signal(signal.SIGTERM, lambda *_: setattr(server, "should_exit", True))
        signal.signal(signal.SIGINT, lambda *_: setattr(server, "should_exit", True))
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        if not server.started:
            raise RuntimeError("Loopback synthetic v3 server did not start")
        print(json.dumps({"origin": "http://127.0.0.1:" + str(port), "path": "/NoteAI_Pro_Demo_Framer.html",
            "state_path": "/__cover_agent_test__/state", "stop_path": "/__cover_agent_test__/stop",
            "delivery": delivery, "database": str(db._DB_PATH), "model_calls": 9,
            "real_model_calls": 0, "notes": "One existing synthetic report/cover; PC and H5 reuse it. No new task."},
            ensure_ascii=False), flush=True)
        while thread.is_alive():
            thread.join(timeout=.2)
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        if sock is not None:
            sock.close()
        api.app.router.routes[:] = routes_before
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides_before)
        if policy is not None:
            policy.stop()
        readiness.stop()
        fixture.tearDown()


if __name__ == "__main__":
    main()
