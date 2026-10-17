"""Affected endpoint/storage tests; all model transports remain synthetic."""
import asyncio
import json
import os
import sys
import threading
from datetime import timedelta
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from contextlib import ExitStack

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"model"))
import api
import billing
import db
import idempotency
import postdelivery
import task_clarification
from tests import test_postdelivery_reservation as fixtures


class PostDeliveryApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PostDeliveryReservationTests();self.fixture.setUp()
        self.user={"id":self.fixture.user}
        self.env=mock.patch.dict(os.environ,{"NOTEAI_POSTDELIVERY_SETTLEMENT":"1",
            "NOTEAI_TASK_CLARIFICATION_ENABLED":"1","NOTEAI_PUBLIC_PRODUCT":"0"})
        self.env.start()

    def tearDown(self):
        self.env.stop();self.fixture.tearDown()

    def response(self):
        return api.AnalyzeResponse(ces_percentile=71.2,composite_score=71.2,grade="良好",features={},
            weaknesses=[],ai_diagnosis="真实结构的模拟诊断",suggested_titles=["原方案标题"],
            suggested_body="原方案正文",improvement_plan="原改进计划",model_used="synthetic")

    def active_call(self):
        usage=billing._ACTIVE_USAGE_ID.get()
        self.fixture.known_call({"charge":{"usage_id":usage}})

    async def collect(self,response):
        return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in response.body_iterator]

    def test_headerless_generation_gets_one_server_task_and_saves_before_fixed_charge(self):
        before=[]
        async def pipeline(**kwargs):
            before.append(billing.get_quota_status(self.user["id"])["monthly_credits_used"])
            self.active_call()
            yield {"type":"stage","stage":"p1","progress":10}
            yield {"type":"complete","note_title":"模拟标题","note_body":"模拟正文", "ces_percentile":72,"grade":"良好"}
        async def run():
            response=await api.generate_stream_endpoint(api.GenerateInput(domain="休闲娱乐体验",brief="真实素材"),self.user,None,None)
            return await self.collect(response)
        with mock.patch.object(api,"_generate_pipeline_stream",new=pipeline),mock.patch.object(api,"_maybe_enrich_facts",new=mock.AsyncMock(return_value=None)),mock.patch.object(api,"_compute_market_timing_for_delivery",return_value=None),mock.patch.object(api._memory,"build_memory_prompt",return_value=""),mock.patch.object(api._memory,"check_and_record_achievements"):
            events=asyncio.run(run())
        created=next(event for event in events if event["type"]=="task_created")
        complete=next(event for event in events if event["type"]=="complete")
        self.assertEqual(before,[0])
        self.assertEqual((created["billing"]["status"],created["billing"]["credits_used"],created["billing"]["reserved_credits"]),("reserved",0,8))
        self.assertEqual((complete["billing"]["status"],complete["billing"]["credits_used"]),("committed",8))
        self.assertEqual(complete["saved_note_id"],created["task_id"])
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes")[0],1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM usage_records")[0],1)
        saved=json.loads(db.fetchone("SELECT generate_ctx_json FROM chat_sessions WHERE id=?",(created["task_id"],))[0])[task_clarification.KEY]
        self.assertEqual(saved["result"]["billing"]["status"],"committed")
        state=asyncio.run(api.read_chat_task(created["task_id"],self.user))
        self.assertEqual((state["status"],state["billing"]["status"]),("completed","committed"))

    def test_server_id_is_stable_in_the_same_scope_and_bad_explicit_id_is_not_replaced(self):
        scope={"path":"/generate/stream","headers":[]}
        postdelivery.ensure_request_id(scope);first=scope["headers"][:]
        postdelivery.ensure_request_id(scope)
        self.assertEqual(scope["headers"],first)
        self.assertTrue(dict(first)[b"x-request-id"].startswith(b"server-"))
        invalid={"path":"/generate/stream","headers":[(b"x-request-id",b"bad")]}
        postdelivery.ensure_request_id(invalid)
        self.assertEqual(invalid["headers"],[(b"x-request-id",b"bad")])

    def test_public_boundary_headerless_request_keeps_normal_auth_and_returns_server_id(self):
        from fastapi.testclient import TestClient
        import public_account
        async def pipeline(**kwargs):
            self.active_call()
            yield {"type":"complete","note_title":"模拟标题","note_body":"模拟正文", "ces_percentile":72,"grade":"良好"}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ,{"NOTEAI_PUBLIC_PRODUCT":"1",
                "NOTEAI_PUBLIC_ACCOUNT_ONLY":"0","NOTEAI_PUBLIC_ORIGINS":"https://noteaipro.com",
                "NOTEAI_MODEL_CONFIG_ENABLED":"0"}))
            user=api._auth.create_user("postdelivery-boundary","SyntheticOnlyPassword42!",phone="+8613800138999",
                phone_verified=True,contract_version=public_account.PRODUCT_CONTRACT_VERSION,privacy_accepted=True)
            self.user={"id":user["id"]};self.fixture.user=user["id"]
            stack.enter_context(mock.patch.object(api,"_generate_pipeline_stream",new=pipeline))
            stack.enter_context(mock.patch.object(api,"_maybe_enrich_facts",new=mock.AsyncMock(return_value=None)))
            stack.enter_context(mock.patch.object(api,"_compute_market_timing_for_delivery",return_value=None))
            stack.enter_context(mock.patch.object(api._memory,"build_memory_prompt",return_value=""))
            stack.enter_context(mock.patch.object(api._memory,"check_and_record_achievements"))
            denied=TestClient(api.app).post("/generate/stream",json={"brief":"模拟输入"},headers={"Origin":"https://noteaipro.com"})
            self.assertEqual(denied.status_code,401)
            client=TestClient(api.app,headers={"Origin":"https://noteaipro.com",
                "Authorization":"Bearer "+api._auth.create_token(user["id"])})
            response=client.post("/generate/stream",json={"brief":"模拟输入"})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.headers["x-request-id"].startswith("server-"))
        events=[json.loads(chunk.removeprefix("data: ").strip()) for chunk in response.text.split("\n\n") if chunk.startswith("data: ")]
        complete=next(event for event in events if event["type"]=="complete")
        self.assertEqual((complete["billing"]["credits_used"],complete["billing"]["status"]),(8,"committed"))
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes WHERE user_id=?",(self.user["id"],))[0],1)

    def test_headerless_sync_generation_uses_same_saved_report_settlement(self):
        async def pipeline(**kwargs):
            self.active_call()
            yield {"type":"complete","note_title":"模拟标题","note_body":"模拟正文", "ces_percentile":72,"grade":"良好"}
        with mock.patch.object(api,"_generate_pipeline_stream",new=pipeline),mock.patch.object(api,"_maybe_enrich_facts",new=mock.AsyncMock(return_value=None)),mock.patch.object(api,"_compute_market_timing_for_delivery",return_value=None),mock.patch.object(api._memory,"build_memory_prompt",return_value=""),mock.patch.object(api._memory,"check_and_record_achievements"):
            result=asyncio.run(api.generate(api.GenerateInput(brief="模拟输入"),self.user,None,None))
        self.assertEqual((result.billing["status"],result.billing["credits_used"]),("committed",8))
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes WHERE id=?",(result.saved_note_id,))[0],1)

    def test_diagnosis_report_and_six_credits_share_one_transaction(self):
        req=api.AnalyzeInput(note_title="原题",desc="原文",domain="休闲娱乐体验")
        claim=api._paid_request_claim("diagnosis-reservation",user_id=self.user["id"],operation="analyze",payload=req)
        self.fixture.known_call(claim)
        response=self.response()
        with mock.patch.object(api._memory,"check_and_record_achievements"):
            api._persist_postdelivery_diagnosis(claim,response,self.user,req,"原文",False)
        self.assertEqual((response.saved_note_id,response.diagnosis_id),(claim["request_id"],claim["request_id"]))
        self.assertEqual(response.billing["credits_used"],6)
        self.assertTrue(idempotency.mark_completed(claim,confirm_existing=True))
        reopened=asyncio.run(api.get_diagnosis(claim["request_id"],self.user))
        self.assertEqual(reopened["billing"]["status"],"committed")
        self.assertEqual(reopened["desc"],"原文")
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user["id"],))[0],6)

    def test_second_diagnosis_insert_failure_rolls_back_note_report_and_customer_consumption(self):
        req=api.AnalyzeInput(note_title="原题",desc="原文",domain="休闲娱乐体验")
        claim=api._paid_request_claim("diagnosis-save-fail",user_id=self.user["id"],operation="analyze",payload=req)
        self.fixture.known_call(claim)
        execute=db.Transaction.execute
        def fail_report(tx,statement,*args,**kwargs):
            if statement.startswith("INSERT INTO saved_diagnoses"):
                raise RuntimeError("synthetic report insert failed")
            return execute(tx,statement,*args,**kwargs)
        with mock.patch.object(db.Transaction,"execute",new=fail_report):
            with self.assertRaisesRegex(RuntimeError,"report insert failed"):
                api._persist_postdelivery_diagnosis(claim,self.response(),self.user,req,"原文",False)
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes")[0],0)
        self.assertEqual(db.fetchone("SELECT count(*) FROM saved_diagnoses")[0],0)
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user["id"],))[0],0)
        claim["_execution_drained"]=True
        idempotency.mark_failed_and_refund(claim,failure_code="request_failed")
        receipt=billing.get_charge_receipt(self.user["id"],"analyze",claim["charge"],claim["request_id"])
        self.assertEqual((receipt["status"],receipt["credits_used"],receipt["refunded_credits"]),("released",0,0))

    def test_generation_error_source_is_closed_before_hold_release_and_never_refunded(self):
        claim=self.fixture.reserve()
        settled=[]
        async def source():
            try:yield 'data: '+json.dumps({"type":"error","message":"synthetic failure"})+'\n\n'
            finally:settled.append(True)
        async def run():
            return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in
                api._idempotent_sse_stream(source(),claim,success_types={"complete"})]
        events=asyncio.run(run())
        self.assertEqual(settled,[True])
        self.assertEqual((events[-1]["refund_status"],events[-1]["billing"]["status"]),("released","released"))
        self.assertIn("本次未扣积分",events[-1]["message"])
        self.assertEqual(db.fetchone("SELECT count(*) FROM credit_transactions WHERE type='refund'")[0],0)

    def test_diagnosis_parent_cancellation_joins_issued_experts_before_returning(self):
        async def run():
            started=[];settled=[];ready=asyncio.Event()
            async def expert(*args,**kwargs):
                started.append(True)
                if len(started)==4:ready.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await asyncio.sleep(0)
                    settled.append(True)
                    raise
            with ExitStack() as stack:
                for name in ("_agent_content","_agent_visual","_agent_growth","_agent_user"):
                    stack.enter_context(mock.patch.object(api,name,new=expert))
                stack.enter_context(mock.patch.object(api,"_get_dk",return_value={}))
                task=asyncio.create_task(api._run_five_agents(api.NoteInput(note_title="题",desc="文",domain="休闲娱乐体验"),
                    70,"良好",[],{},None,None,{},{}))
                await asyncio.wait_for(ready.wait(),2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                self.assertEqual(len(settled),4)
        asyncio.run(run())

    def test_semantic_worker_cancellation_joins_before_original_hold_release(self):
        # A real executor thread represents the already-issued semantic request.
        # No provider/HTTP occurs: only its controlled completion is simulated.
        for operation in ("generate", "analyze"):
            with self.subTest(operation=operation):
                req = (api.GenerateInput(domain="休闲娱乐体验", brief="模拟素材")
                    if operation == "generate" else
                    api.AnalyzeInput(note_title="模拟原题", desc="模拟原文", domain="休闲娱乐体验"))
                claim = api._paid_request_claim("semantic-drain-" + operation,
                    user_id=self.user["id"], operation=operation, payload=req)
                finished = []
                async def run():
                    ready = asyncio.Event()
                    release = threading.Event()
                    loop = asyncio.get_running_loop()
                    def semantic(**kwargs):
                        self.assertEqual((kwargs["trace_step"], kwargs["max_tokens"]),
                            ("semantic_features", 120))
                        loop.call_soon_threadsafe(ready.set)
                        if not release.wait(3):
                            raise RuntimeError("synthetic semantic barrier was not released")
                        finished.append(operation)
                        return json.dumps({key: 0.5 for key in api.SEMANTIC_FEATURE_COLS})
                    async def source():
                        yield 'data: ' + json.dumps({"type":"stage", "stage":"semantic"}) + '\n\n'
                        if operation == "generate":
                            await api._score_generated_note("模拟标题", "模拟正文", req.domain, "", None, {})
                        else:
                            await api._run_analyze_pipeline(req, self.user, billing_charge=claim["charge"],
                                billing_managed=True, reservation_claim=claim)
                        raise AssertionError("cancelled semantic call must not advance or save a report")
                    async def consume():
                        return [chunk async for chunk in api._idempotent_sse_stream(
                            source(), claim, success_types={"complete"})]
                    with ExitStack() as stack:
                        stack.enter_context(mock.patch.object(api._mr, "call_semantic_sync", side_effect=semantic))
                        stack.enter_context(mock.patch.object(api, "_maybe_enrich_facts", new=mock.AsyncMock(return_value=None)))
                        stack.enter_context(mock.patch.object(api, "_compute_market_timing_for_delivery", return_value=None))
                        task = asyncio.create_task(consume())
                        try:
                            await asyncio.wait_for(ready.wait(), 2)
                            task.cancel()
                            for _ in range(3):
                                await asyncio.sleep(0)
                            self.assertFalse(task.done(), "issued semantic worker must be joined before release")
                            held = billing.get_charge_receipt(self.user["id"], operation,
                                claim["charge"], claim["request_id"])
                            self.assertEqual((held["status"], held["credits_used"]), ("reserved", 0))
                            self.assertEqual(finished, [])
                        finally:
                            release.set()
                            outcome = (await asyncio.gather(task, return_exceptions=True))[0]
                        self.assertIsInstance(outcome, asyncio.CancelledError)
                asyncio.run(run())
                self.assertEqual(finished, [operation])
                released = billing.get_charge_receipt(self.user["id"], operation,
                    claim["charge"], claim["request_id"])
                self.assertEqual((released["status"], released["credits_used"], released["refunded_credits"]),
                    ("released", 0, 0))
                self.assertEqual(db.fetchone("SELECT count(*) FROM notes WHERE id=?", (claim["request_id"],))[0], 0)
                self.assertEqual(db.fetchone("SELECT count(*) FROM credit_transactions WHERE type='refund'")[0], 0)

    def test_clarification_resume_keeps_original_hold_usage_and_heartbeat_contract(self):
        claim=self.fixture.reserve(key="clarify-reservation");self.fixture.known_call(claim)
        question={"field":"package_scope","question":"双人套餐包含门票吗？","source_quote":"双人套餐门票另有组合","object":"双人套餐","time_range":"10月"}
        marker=task_clarification.execution.set({"claim":claim})
        try:
            with self.assertRaises(task_clarification.WaitingForInput) as paused:
                task_clarification.pause({"pipeline":"generate_stream","domain":"休闲娱乐体验","local_time":""},
                    [{"role":"内容专家","raw":"<clarifications>"+json.dumps([question],ensure_ascii=False)+"</clarifications>"}],
                    source="双人套餐门票另有组合",merchant="测试商户")
        finally:task_clarification.execution.reset(marker)
        event=paused.exception.event
        duplicate=postdelivery.reserve_claim(user_id=self.user["id"],operation="generate",
            request_id="clarify-reservation",payload={"fixture":True})
        self.assertEqual(duplicate["session_id"],claim["request_id"])
        resumed,task=task_clarification.resume(self.user["id"],claim["request_id"],event["version"],
            [{"question_id":event["questions"][0]["question_id"],"status":"omitted"}])
        self.assertEqual((resumed["state"],resumed["settlement_mode"],resumed["charge"]["usage_id"]),
            ("reservation_owner","reservation_v1",claim["charge"]["usage_id"]))
        row=db.fetchone("SELECT lease_expires_at FROM idempotency_requests WHERE id=?",(claim["request_id"],))
        now=idempotency._parse_lease_clock(row[0])-timedelta(seconds=700)
        self.assertTrue(idempotency.touch_active_claim(resumed,last_progress_at=now.isoformat(),now=now))
        result={"note_title":"模拟标题","note_body":"模拟正文","ces_percentile":70,"grade":"良好"}
        task_clarification.save_result(resumed,result)
        self.assertEqual(result["billing"]["credits_used"],8)
        self.assertEqual(db.fetchone("SELECT count(*) FROM usage_records")[0],1)

    def pause_claim(self):
        claim=self.fixture.reserve();self.fixture.known_call(claim)
        question={"field":"package_scope","question":"套餐包含门票吗？","source_quote":"双人套餐门票另有组合","object":"双人套餐","time_range":"10月"}
        marker=task_clarification.execution.set({"claim":claim})
        try:
            with self.assertRaises(task_clarification.WaitingForInput) as paused:
                task_clarification.pause({"pipeline":"generate_stream","domain":"休闲娱乐体验","local_time":""},
                    [{"role":"内容专家","raw":"<clarifications>"+json.dumps([question],ensure_ascii=False)+"</clarifications>"}],
                    source="双人套餐门票另有组合")
        finally:task_clarification.execution.reset(marker)
        return claim,paused.exception.event

    def test_waiting_owner_can_abandon_v1_without_consumption_or_supplier_replay(self):
        claim,event=self.pause_claim()
        with mock.patch.object(api._public_product,"queue_status",return_value={"active":True,"can_cancel":False}):
            state=asyncio.run(api.read_chat_task(claim["request_id"],self.user))
            self.assertFalse(state["can_cancel"])
            denied=asyncio.run(api.cancel_chat_task(claim["request_id"],self.user))
            self.assertFalse(denied["cancel_requested"])
            self.assertEqual(billing.get_quota_status(self.user["id"])["monthly_credits_reserved"],8)
        state=asyncio.run(api.read_chat_task(claim["request_id"],self.user))
        self.assertTrue(state["can_cancel"])
        with self.assertRaises(Exception) as wrong_owner:
            asyncio.run(api.cancel_chat_task(claim["request_id"],{"id":"different-owner"}))
        self.assertEqual(wrong_owner.exception.status_code,404)
        result=asyncio.run(api.cancel_chat_task(claim["request_id"],self.user))
        self.assertEqual((result["refund_status"],result["billing"]["credits_used"]),("released",0))
        state=asyncio.run(api.read_chat_task(claim["request_id"],self.user))
        self.assertEqual((state["status"],state["billing"]["status"]),("failed","released"))
        with self.assertRaises(Exception):
            task_clarification.resume(self.user["id"],claim["request_id"],event["version"],
                [{"question_id":event["questions"][0]["question_id"],"status":"omitted"}])
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user["id"],))[0],0)

    def test_waiting_resume_and_abandon_are_mutually_exclusive(self):
        claim,event=self.pause_claim()
        def resume():
            try:
                value=task_clarification.resume(self.user["id"],claim["request_id"],event["version"],
                    [{"question_id":event["questions"][0]["question_id"],"status":"omitted"}])
                return ("resumed",value[0])
            except Exception as exc:
                self.assertEqual(exc.status_code,409);return ("resume_lost",None)
        def cancel():
            return ("cancelled",postdelivery.cancel_waiting_reservation(self.user["id"],claim["request_id"]))
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(resume);b=pool.submit(cancel);resumed=a.result();cancelled=b.result()
        row=db.fetchone("SELECT status,refund_applied FROM idempotency_requests WHERE id=?",(claim["request_id"],))
        if resumed[0]=="resumed":
            self.assertIsNone(cancelled[1]);self.assertEqual((row["status"],row["refund_applied"]),("running",0))
        else:
            self.assertEqual(cancelled[1]["status"],"released");self.assertEqual((row["status"],row["refund_applied"]),("failed",1))

    def test_duplicate_new_and_legacy_waiting_keep_original_session_in_409(self):
        req=api.GenerateInput(brief="固定真实输入")
        new=api._paid_request_claim("new-waiting-key",user_id=self.user["id"],operation="generate",payload=req)
        db.execute("UPDATE idempotency_requests SET status='waiting_for_input' WHERE id=?",(new["request_id"],))
        billing.grant_credits(self.user["id"],8,"isolated old mode fixture")
        with mock.patch.dict(os.environ,{"NOTEAI_POSTDELIVERY_SETTLEMENT":"0"}):
            old=api._paid_request_claim("old-waiting-key",user_id=self.user["id"],operation="generate",payload=req)
        db.execute("UPDATE idempotency_requests SET status='waiting_for_input' WHERE id=?",(old["request_id"],))
        for key,claim in (("new-waiting-key",new),("old-waiting-key",old)):
            with self.assertRaises(Exception) as duplicate:
                api._paid_request_claim(key,user_id=self.user["id"],operation="generate",payload=req)
            self.assertEqual(duplicate.exception.status_code,409)
            self.assertEqual(duplicate.exception.detail["session_id"],claim["request_id"])


if __name__=="__main__":unittest.main()
