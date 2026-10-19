"""Offline integration with real ledger/storage/renderer and mocked HTTP only.

Passing these cases proves local wiring and recovery boundaries. It does not
prove supplier entitlement, real output quality, PostgreSQL, or phone saving.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest import mock

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media
import billing
import cover_jobs as jobs
import cover_runtime as runtime
import cover_seedream as seedream
import cover_service as service
import db
import model_admission
import private_storage as storage
import public_product
from tests import test_cover_jobs as job_fixtures
from tests.test_cover_runtime import approved_qc, plan


class CoverServiceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = job_fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.fixture.input = {"title": "周末咖啡时光", "body": "本人拍摄素材，仅作本地离线测试。",
            "domain": "美食", "visual_advice": "保留原图，不增加设施或商品。", "title_variants": ["咖啡时光"]}
        self.env = mock.patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1",
            "NOTEAI_ARK_API_KEY": "offline-fixture", "NOTEAI_PUBLIC_PRODUCT": "0"})
        self.env.start()
        self.assertFalse(public_product.enabled())
        self.no_network = mock.patch("socket.socket.connect", side_effect=AssertionError("External network forbidden in offline cover service tests"))
        self.no_network.start()
        self.admission = model_admission.Admission(model_admission.Limits(physical=2, seedream=1))
        self.admission_patch = mock.patch.object(model_admission, "current", return_value=self.admission)
        self.admission_patch.start()
        self.requests = []
        self.request_lock = threading.Lock()
        stream = io.BytesIO()
        Image.new("RGB", (1776, 2368), "#A49376").save(stream, "PNG")
        self.background = stream.getvalue()
        self.runtime_calls = 0

    def tearDown(self):
        self.admission_patch.stop()
        self.no_network.stop()
        self.env.stop()
        self.fixture.tearDown()

    def submit(self, **kwargs):
        return self.fixture.submit(**kwargs)

    def other_report(self):
        report = str(uuid.uuid4())
        db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)",
            (report, self.fixture.other, "另一位用户咖啡", "美食", '{"visual":"本人图"}', self.fixture.now.isoformat()))
        return report

    def wrapper(self, *, route="photo", design_failure=False, image_unknown=False, pause_design=None,
                qc=None, request_observer=None):
        def run(**kwargs):
            self.runtime_calls += 1
            reference = kwargs["sources"][0]["media_ref"]
            design = {**plan(reference, route), "text": kwargs["report"]["title"],
                      "photo_bbox": [.04, .27, .96, .73]}
            def handle(request):
                with self.request_lock:
                    self.requests.append({"path": request.url.path,
                        "model": json.loads(request.content)["model"], "job_id": kwargs["job_id"]})
                if request_observer:
                    request_observer(request, kwargs)
                payload = json.loads(request.content)
                if request.url.path.endswith("/images/generations"):
                    if image_unknown:
                        raise httpx.ReadTimeout("offline fixture UNKNOWN", request=request)
                    import base64
                    return httpx.Response(200, json={"model": seedream.MODEL,
                        "data": [{"b64_json": base64.b64encode(self.background).decode(), "size": "1776x2368"}],
                        "usage": {"input_images": 1, "generated_images": 1}},
                        headers={"x-request-id": "offline-image-request"})
                self.assertEqual(payload["model"], ark_media.MODEL)
                prompt = payload["messages"][0]["content"][-1]["text"]
                is_design = "你为已有小红书报告设计" in prompt
                if is_design and pause_design:
                    pause_design(kwargs["job_id"])
                if is_design and design_failure:
                    return httpx.Response(403, json={"error": {"code": "AccessDenied"}})
                content = design if is_design else (qc or approved_qc())
                return httpx.Response(200, json={"model": ark_media.MODEL,
                    "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
                        "content": json.dumps(content, ensure_ascii=False)}}],
                    "usage": {"prompt_tokens": 800 if is_design else 400, "completion_tokens": 160,
                              "prompt_tokens_details": {"cached_tokens": 0}}})
            transport = httpx.MockTransport(handle)
            return runtime.run_cover(**kwargs, design_transport=transport,
                qc_transport=transport, seedream_transport=transport)
        return run

    def calls(self, job_id):
        return [dict(row) for row in db.fetchall("SELECT c.* FROM public_trial_calls c JOIN cover_jobs j "
            "ON j.usage_id=c.usage_record_id WHERE j.id=? ORDER BY c.created_at,c.id", (job_id,))]

    def test_photo_real_adapters_storage_and_unique_eight_after_save(self):
        before = self.fixture.balances()
        task = self.submit(key="service-photo")
        self.assertEqual(self.fixture.balances(), before)
        claim = jobs.claim_job(task["job_id"])
        result = service._run_claim(claim, runtime=self.wrapper())
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["billing"]["credits_used"], 8)
        self.assertEqual(self.fixture.balances()[1], 8)
        calls = self.calls(task["job_id"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(row["state"] == "responded" and row["http_status"] == 200 and row["model_usage_record_id"] for row in calls))
        self.assertEqual(db.fetchone("SELECT count(*) FROM model_usage_records")[0], 2)
        self.assertEqual(db.fetchone("SELECT count(*) FROM cover_image_usage")[0], 0)
        final_ref = jobs.asset_reference(self.fixture.user, task["job_id"])
        final, body = storage.load_media_bytes(final_ref, user_id=self.fixture.user, purpose="image")
        with Image.open(io.BytesIO(body)) as image:
            self.assertEqual(image.size, (1776, 2368))
        self.assertGreaterEqual(datetime.fromisoformat(final.expires_at) - self.fixture.now, timedelta(days=89))
        self.assertEqual(jobs.get_job(self.fixture.user, task["job_id"])["status"], "completed")
        duplicate = self.submit(key="service-photo")
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["job_id"], task["job_id"])
        self.assertIsNone(jobs.claim_job(task["job_id"]))
        self.assertEqual(service._run_claim(claim, runtime=self.wrapper())["job_id"], task["job_id"])
        self.assertIsNone(service.run_next(runtime=self.wrapper()))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.fixture.balances()[1], 8)
        self.assertEqual(self.admission.operations, {})
        self.assertEqual(self.admission.calls.active, {})

    def test_seedream_real_wire_image_accounting_is_separate_from_text_and_three_calls(self):
        task = self.submit(key="service-background")
        result = service.run_next(runtime=self.wrapper(route="seedream_background"))
        self.assertEqual(result["status"], "completed", result)
        calls = self.calls(task["job_id"])
        self.assertEqual(len(calls), 3)
        text = [row for row in calls if row["model_usage_record_id"]]
        image = [row for row in calls if not row["model_usage_record_id"]]
        self.assertEqual(len(text), 2)
        self.assertEqual(len(image), 1)
        self.assertTrue(jobs.image_call_settled(db, image[0]["id"]))
        row = db.fetchone("SELECT * FROM cover_image_usage WHERE id=?", (image[0]["id"],))
        self.assertEqual((row["state"], row["output_images"], row["billed_images"]), ("responded", 1, 1))
        self.assertIsNone(row["actual_cost"])
        self.assertEqual(row["cost_status"], "estimated")
        self.assertEqual(row["provider_request_id"], "offline-image-request")
        usage = db.fetchone("SELECT * FROM usage_records WHERE id=?", (row["usage_id"],))
        text_cost = db.fetchone("SELECT sum(known_cost_rmb) FROM model_usage_records WHERE usage_record_id=?", (row["usage_id"],))[0]
        self.assertAlmostEqual(usage["estimated_cost_rmb"], text_cost + .60)
        self.assertAlmostEqual(usage["actual_model_cost_rmb"], text_cost)
        self.assertNotEqual(usage["cost_mode"], "actual")
        self.assertEqual(usage["model_calls"], 3)
        self.assertEqual(json.loads(image[0]["provenance_json"])["provider"], "seedream")
        self.assertEqual(result["billing"]["credits_used"], 8)
        self.assertEqual(db.fetchone("SELECT count(*) FROM model_usage_records")[0], 2)
        self.assertEqual([row["path"] for row in self.requests], ["/api/v3/chat/completions", "/api/v3/images/generations", "/api/v3/chat/completions"])

    def test_many_queued_jobs_from_busy_user_do_not_hide_another_user(self):
        billing.grant_credits(self.fixture.user, 512, 'offline fairness fixture')
        policy = {**self.fixture.policy, 'budget_id': jobs.FORMAL_BUDGET_ID}
        for index in range(32):
            self.fixture.submit(key='formal-busy-'+str(index), policy_snapshot=policy,
                quote_version=jobs.policy_quote_version(policy))
        other = self.fixture.submit(key='formal-other', user_id=self.fixture.other,
            report_id=self.other_report(), source_refs=[self.fixture.image(self.fixture.other, small=True).id],
            policy_snapshot=policy, quote_version=jobs.policy_quote_version(policy))
        held, _ = self.admission.register(self.fixture.user, 'original-report', route='/generate/stream')
        try:
            with mock.patch.object(service, '_run_claim', return_value={'selected': True}) as run:
                self.assertEqual(service.run_next(), {'selected': True})
                self.assertEqual(run.call_args.args[0]['request_id'], other['job_id'])
        finally:
            self.admission.finish(held)

    def test_known_design_denial_releases_hold_without_a_usable_charge(self):
        task = self.submit(key="service-design-fail")
        result = service.run_next(runtime=self.wrapper(design_failure=True))
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["billing"]["credits_used"], 0)
        self.assertEqual(result["billing"]["status"], "released")
        self.assertEqual(self.fixture.balances()[1], 0)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.calls(task["job_id"])[0]["state"], "responded")
        self.assertEqual(db.fetchone("SELECT count(*) FROM cover_asset_revisions")[0], 0)
        self.assertIsNone(service.run_next(runtime=self.wrapper()))

    def test_private_save_failure_after_quality_check_never_settles_user_credits(self):
        task = self.submit(key="service-store-failed")
        before = self.fixture.balances()
        with mock.patch.object(service, "_store_image", side_effect=storage.ObjectStorageUnavailable("PRIVATE_OBJECT_WRITE_FAILED")):
            result = service.run_next(runtime=self.wrapper())
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["billing"]["status"], "released")
        self.assertEqual(result["billing"]["credits_used"], 0)
        self.assertEqual(self.fixture.balances(), before)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(db.fetchone("SELECT count(*) FROM cover_asset_revisions")[0], 0)
        self.assertIsNone(service.run_next(runtime=self.wrapper()))
        self.assertEqual(len(self.requests), 2)

    def test_image_unknown_does_not_qc_or_replay_after_reopen_and_worker_poll(self):
        task = self.submit(key="service-image-unknown")
        result = service.run_next(runtime=self.wrapper(route="seedream_background", image_unknown=True))
        self.assertEqual(result["status"], "outcome_unknown", result)
        self.assertEqual(result["billing"]["credits_used"], 0)
        self.assertFalse(result["has_final"])
        self.assertEqual(len(self.requests), 2)
        image = db.fetchone("SELECT * FROM cover_image_usage")
        self.assertEqual(image["state"], "unknown")
        self.assertIsNone(image["actual_cost"])
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls WHERE id=?", (image["id"],))[0], "unknown")
        self.assertEqual(jobs.get_job(self.fixture.user, task["job_id"])["status"], "outcome_unknown")
        duplicate = self.submit(key="service-image-unknown")
        self.assertFalse(duplicate["created"])
        for _ in range(2):
            self.assertIsNone(service.run_next(runtime=self.wrapper()))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_same_user_original_report_keeps_cover_queued_and_other_user_can_run(self):
        task = self.submit(key="service-queued-owner")
        other_report = self.other_report()
        other_source = self.fixture.image(self.fixture.other, small=True)
        other = self.submit(key="service-other-user", user_id=self.fixture.other,
            report_id=other_report, source_refs=[other_source.id])
        original, owns = self.admission.register(self.fixture.user, "original-report", route="/generate/stream")
        try:
            result = service.run_next(runtime=self.wrapper())
            self.assertEqual(result["job_id"], other["job_id"])
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(jobs.get_job(self.fixture.user, task["job_id"])["status"], "queued")
            self.assertIsNone(service.run_next(runtime=self.wrapper()))
            self.assertEqual({request["job_id"] for request in self.requests}, {other["job_id"]})
        finally:
            self.admission.finish(original)
        result = service.run_next(runtime=self.wrapper())
        self.assertEqual(result["job_id"], task["job_id"])
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(self.admission.operations, {})

    def test_cover_waits_for_original_report_physical_slot_before_any_provider_dispatch(self):
        self.admission = model_admission.Admission(model_admission.Limits(physical=1, seedream=1))
        self.admission_patch.stop()
        self.admission_patch = mock.patch.object(model_admission, "current", return_value=self.admission)
        self.admission_patch.start()
        task = self.submit(key="service-report-physical-slot")
        report, _ = self.admission.register(self.fixture.other, "physical-original-report", route="/analyze/stream")
        ticket = self.admission.calls.acquire(report, str(uuid.uuid4()), "claude")
        entered = threading.Event()
        wrapper = self.wrapper(request_observer=lambda *_args: entered.set())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.run_next, runtime=wrapper)
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    with self.admission.calls.lock:
                        if self.admission.calls._tickets():
                            break
                    entered.wait(.01)
                with self.admission.calls.lock:
                    self.assertEqual(len(self.admission.calls.active), 1)
                    self.assertEqual(len(self.admission.calls._tickets()), 1)
                self.assertFalse(entered.is_set())
                self.assertEqual(self.calls(task["job_id"]), [])
            finally:
                self.admission.calls.release(ticket)
                self.admission.finish(report)
            result = future.result(timeout=10)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.admission.operations, {})

    def test_two_users_share_physical_two_but_seedream_one_without_losing_unique_credits(self):
        first = self.submit(key="service-two-users-1")
        other_report = self.other_report()
        other_source = self.fixture.image(self.fixture.other, small=True)
        second = self.submit(key="service-two-users-2", user_id=self.fixture.other,
            report_id=other_report, source_refs=[other_source.id])
        claims = [jobs.claim_job(task["job_id"]) for task in (first, second)]
        designs = threading.Barrier(2)
        first_image = threading.Event()
        release_image = threading.Event()
        peaks = {"physical": 0, "seedream": 0}
        image_counter = [0]
        lock = threading.Lock()

        def observer(request, _kwargs):
            with self.admission.calls.lock:
                active = list(self.admission.calls.active.values())
                with lock:
                    peaks["physical"] = max(peaks["physical"], len(active))
                    peaks["seedream"] = max(peaks["seedream"], sum(item.provider == "seedream" for item in active))
            self.assertLessEqual(db.fetchone("SELECT count(*) FROM public_trial_calls WHERE state='dispatched'")[0], 2)
            if request.url.path.endswith("/images/generations"):
                with lock:
                    image_counter[0] += 1
                    number = image_counter[0]
                if number == 1:
                    first_image.set()
                    self.assertTrue(release_image.wait(5))

        wrapper = self.wrapper(route="seedream_background", pause_design=lambda _job: designs.wait(timeout=5),
                               request_observer=observer)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(service._run_claim, claim, runtime=wrapper) for claim in claims]
            try:
                self.assertTrue(first_image.wait(5))
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    with self.admission.calls.lock:
                        if any(ticket.provider == "seedream" for ticket in self.admission.calls._tickets()):
                            break
                    release_image.wait(.01)
                with self.admission.calls.lock:
                    self.assertTrue(any(ticket.provider == "seedream" for ticket in self.admission.calls._tickets()))
                    self.assertEqual(sum(ticket.provider == "seedream" for ticket in self.admission.calls.active.values()), 1)
            finally:
                release_image.set()
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual([result["status"] for result in results], ["completed", "completed"], results)
        self.assertEqual(peaks, {"physical": 2, "seedream": 1})
        self.assertEqual(len(self.requests), 6)
        self.assertEqual([result["billing"]["credits_used"] for result in results], [8, 8])
        self.assertEqual(db.fetchone("SELECT count(*) FROM model_usage_records")[0], 4)
        self.assertEqual(db.fetchone("SELECT count(*) FROM cover_image_usage")[0], 2)
        self.assertEqual(self.admission.operations, {})
        self.assertEqual(self.admission.calls.active, {})

    def test_free_adjustment_keeps_deadline_base_and_ledger_without_new_http(self):
        task = self.submit(key="service-adjust")
        result = service.run_next(runtime=self.wrapper())
        self.assertEqual(result["status"], "completed", result)
        before_calls = self.calls(task["job_id"])
        before_balance = self.fixture.balances()
        base_ref = jobs.asset_reference(self.fixture.user, task["job_id"], base=True)
        old_ref = jobs.asset_reference(self.fixture.user, task["job_id"])
        adjusted = service.adjust(self.fixture.user, task["job_id"], text="咖啡\n时光", position="top", expected_revision=1)
        self.assertEqual(adjusted["asset_revision"], 2)
        self.assertEqual(adjusted["expires_at"], result["expires_at"])
        self.assertEqual(jobs.asset_reference(self.fixture.user, task["job_id"], base=True), base_ref)
        self.assertEqual(jobs.asset_reference(self.fixture.user, task["job_id"], revision=1), old_ref)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.calls(task["job_id"]), before_calls)
        self.assertEqual(self.fixture.balances(), before_balance)
        self.assertEqual(jobs.get_job(self.fixture.user, task["job_id"])["asset_revision"], 2)

    def test_bottom_move_uses_safe_existing_white_space_without_changing_photo_or_calling_model(self):
        task = self.submit(key="service-safe-bottom")
        result = service.run_next(runtime=self.wrapper())
        self.assertEqual(result["status"], "completed", result)
        base = jobs.asset_reference(self.fixture.user, task["job_id"], base=True)
        old = jobs.asset_reference(self.fixture.user, task["job_id"])
        _, before = storage.load_media_bytes(old, user_id=self.fixture.user, purpose="image")
        row = db.fetchone("SELECT layout_json FROM cover_jobs WHERE id=?", (task["job_id"],))
        layout = json.loads(row["layout_json"])
        result = service.adjust(self.fixture.user, task["job_id"], text="咖啡时光", position="bottom", expected_revision=1)
        self.assertEqual(result["asset_revision"], 2)
        self.assertEqual(jobs.asset_reference(self.fixture.user, task["job_id"], base=True), base)
        new = jobs.asset_reference(self.fixture.user, task["job_id"])
        _, after = storage.load_media_bytes(new, user_id=self.fixture.user, purpose="image")
        with Image.open(io.BytesIO(before)) as original, Image.open(io.BytesIO(after)) as updated:
            self.assertEqual(original.crop(tuple(layout["photo_pixels"])).tobytes(),
                             updated.crop(tuple(layout["photo_pixels"])).tobytes())
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.fixture.balances()[1], 8)


if __name__ == "__main__":
    unittest.main()
