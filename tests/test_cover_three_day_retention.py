"""New three-day covers and preserved historical contracts, entirely offline."""
from copy import deepcopy
from datetime import datetime, timedelta
import base64
import json
import os
import unittest
from unittest import mock

from fastapi import HTTPException
from tests import test_cover_jobs as fixtures
from tests import test_cover_agent_artifacts as editable_fixtures

import cover_agent_artifacts as artifacts
import cover_jobs as jobs
import cover_service as service
import cover_settings as settings
import db
import durable_ai
import private_storage as storage


class ThreeDayRetentionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CoverJobsTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def legacy_settings(self):
        config = {**settings.editable_defaults(), "retention_seconds": 90 * 86400,
            "enabled": True, "execution_scope": "formal", "account_verified": True,
            "account_evidence_ref": "historical-offline-evidence"}
        state = {"scope": "production", "revision": 2, "active_revision": 2,
            "active": config, "draft": deepcopy(config), "previous": deepcopy(config), "source": "managed_database"}
        raw = json.dumps(state)
        db.execute("INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES(?,?,0,?)",
            ("noteai_cover_config_v1", raw, self.fixture.now.isoformat()))
        return config, raw

    def test_legacy_active_draft_read_is_immutable_but_new_quotes_are_three_days(self):
        config, raw = self.legacy_settings()
        with mock.patch.object(db, "execute", side_effect=AssertionError("Compatibility read wrote SQL")):
            state = settings.read()
            policy = settings.policy_snapshot()
            quote = jobs.quote_for_user(self.fixture.user, policy_snapshot=policy)
            view = settings.view()
        self.assertEqual(state["active"], config)
        self.assertEqual(state["draft"], config)
        self.assertEqual(view["active"]["retention_seconds"], 3 * 86400)
        self.assertEqual(view["draft"]["retention_seconds"], 3 * 86400)
        self.assertEqual(view["previous"], config)
        self.assertEqual(view["stored_active_retention_seconds"], 90 * 86400)
        self.assertEqual(settings.validate(view["active"]), view["active"])
        self.assertEqual(policy["retention_seconds"], 3 * 86400)
        self.assertEqual(quote["retention_seconds"], 3 * 86400)
        self.assertEqual(db.fetchone("SELECT value_json FROM system_settings WHERE key='noteai_cover_config_v1'")[0], raw)
        with self.assertRaises(HTTPException):
            settings.validate(config)  # New drafts cannot publish the old TTL.
        for value in (2 * 86400, 4 * 86400, float(90 * 86400)):
            changed = json.loads(raw)
            changed["active"]["retention_seconds"] = value
            db.execute("UPDATE system_settings SET value_json=? WHERE key='noteai_cover_config_v1'", (json.dumps(changed),))
            with self.assertRaises(HTTPException) as failure:
                settings.read()
            self.assertEqual(failure.exception.status_code, 503)

    def test_controlled_activation_of_old_draft_makes_new_policy_without_rewriting_history(self):
        config, _ = self.legacy_settings()
        outcome = settings.change("activate", "production", actor="noteai_admin",
            request_id="d83c7d48-3054-443b-836a-056e284d69bd", reason="Offline three-day policy transition", expected=2)
        self.assertEqual(outcome["after"]["active"]["retention_seconds"], 3 * 86400)
        self.assertEqual(outcome["after"]["previous"], config)
        self.assertEqual(settings.policy_snapshot()["retention_seconds"], 3 * 86400)

    def test_new_media_and_payload_caps_are_isolated_from_legacy_and_temporary(self):
        _, body = storage.load_media_bytes(self.fixture.source.id, user_id=self.fixture.user)
        current = storage.store_media_bytes(self.fixture.user, purpose="image", content_type="image/png",
            payload=body, item_count=1, ttl_seconds=3 * 86400, lifecycle="cover_3d_v1", now=self.fixture.now)
        legacy = storage.store_media_bytes(self.fixture.user, purpose="image", content_type="image/png",
            payload=body, item_count=1, ttl_seconds=90 * 86400, lifecycle="cover_v1", now=self.fixture.now)
        self.assertIn("/cover_3d_v1/", storage._reference_key(current))
        self.assertIn("/cover_v1/", storage._reference_key(legacy))
        self.assertEqual(storage.load_media_bytes(current.id, user_id=self.fixture.user,
            now=self.fixture.now + timedelta(days=3) - timedelta(microseconds=1))[1], body)
        with self.assertRaises(storage.MediaReferenceUnavailable):
            storage.load_media_bytes(current.id, user_id=self.fixture.user, now=self.fixture.now + timedelta(days=3))
        self.assertEqual(storage.load_media_bytes(legacy.id, user_id=self.fixture.user,
            now=self.fixture.now + timedelta(days=4))[1], body)
        with self.assertRaises(ValueError):
            storage.store_media_bytes(self.fixture.user, purpose="image", content_type="image/png",
                payload=body, item_count=1, ttl_seconds=3 * 86400 + 1, lifecycle="cover_3d_v1")
        store = storage.PrivateObjectPayloadStore()
        for lifecycle, seconds in (("temporary", 90 * 86400), ("cover_v1", 90 * 86400), ("cover_3d_v1", 3 * 86400)):
            ref = store.put(operation_id={"temporary":"c359ba1d-b8fc-4bc7-b0c9-ac654dca1bc3",
                "cover_v1":"85b3972f-b3cf-4d5c-998e-24c3e02ad454", "cover_3d_v1":"0924c5e4-bfab-4caa-b815-c1b918af017b"}[lifecycle],
                user_id=self.fixture.user, purpose="result", payload=b'{"offline":true}', item_count=1,
                ttl_seconds=seconds, lifecycle=lifecycle, now=self.fixture.now)
            self.assertEqual(store.get(ref, user_id=self.fixture.user), b'{"offline":true}')
            if lifecycle == "cover_3d_v1":
                with mock.patch.object(storage, "_utc", return_value=self.fixture.now + timedelta(days=3)):
                    with self.assertRaises(durable_ai.PayloadUnavailable):
                        store.get(ref, user_id=self.fixture.user)
        with self.assertRaises(ValueError):
            store.put(operation_id="6dfb8936-c691-4b54-ab00-afef36f2adc9", user_id=self.fixture.user,
                purpose="result", payload=b'{}', item_count=1, ttl_seconds=3 * 86400 + 1, lifecycle="cover_3d_v1")
        for prefix in ("v1/media/image/cover_3d_v1", "v1/payload/result/cover_3d_v1"):
            self.assertEqual(storage._object_prefix(prefix), prefix + "/")
        for item in self.fixture.backend.list("v1", limit=100)[0]:
            storage.validate_stored_object_descriptor(item)

    def test_legacy_snapshot_only_replays_its_original_request_without_new_reservation(self):
        self.fixture.policy["retention_seconds"] = 90 * 86400
        with mock.patch.object(jobs, "RETENTION_SECONDS", 90 * 86400):
            original = self.fixture.submit(key="old-retention-request")
        before = self.fixture.balances()
        row = db.fetchone("SELECT quote_version FROM cover_jobs WHERE id=?", (original["job_id"],))
        args = {"user_id": self.fixture.user, "report_type":"analyze", "report_id":self.fixture.report,
            "request_id":"old-retention-request", "source_refs":[self.fixture.source.id],
            "input_snapshot":self.fixture.input, "policy_snapshot":self.fixture.policy, "quote_version":row["quote_version"]}
        replay = jobs.submit_job(**args)
        self.assertFalse(replay["created"])
        self.assertEqual(replay["job_id"], original["job_id"])
        current_policy = {**self.fixture.policy, "retention_seconds":3 * 86400}
        current_replay = jobs.submit_job(**{**args, "policy_snapshot":current_policy})
        self.assertEqual(current_replay["job_id"], original["job_id"])
        self.assertFalse(current_replay["created"])
        for changed in ({"input_snapshot":{**self.fixture.input,"note_title":"changed"}},
                        {"policy_snapshot":{**current_policy,"provider":"ark"}}):
            with self.assertRaises(HTTPException) as conflict:
                jobs.submit_job(**{**args,"policy_snapshot":current_policy,**changed})
            self.assertEqual(conflict.exception.status_code, 409)
        with self.assertRaises(ValueError):
            jobs.submit_job(**{**args, "request_id":"new-request-cannot-use-legacy-policy"})
        self.assertEqual(self.fixture.balances(), before)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM cover_jobs")[0], 1)


class LegacyEditableRetentionTests(unittest.TestCase):
    def test_legacy_inflight_runtime_keeps_frozen_ninety_day_assets_and_threshold(self):
        flow = editable_fixtures.AgentArtifactTests()
        flow.setUp()
        try:
            flow.fixture.policy["retention_seconds"] = 90 * 86400
            media_put, bundle_put = storage.store_media_bytes, artifacts.store
            def historical_media(*args, **kwargs):
                return media_put(*args, **{**kwargs,"ttl_seconds":90 * 86400,"lifecycle":"cover_v1"})
            def historical_bundle(*args, **kwargs):
                return bundle_put(*args, **{**kwargs,"ttl_seconds":90 * 86400,"lifecycle":"cover_v1"})
            with mock.patch.object(jobs,"RETENTION_SECONDS",90 * 86400), \
                    mock.patch.object(storage,"store_media_bytes",side_effect=historical_media), \
                    mock.patch.object(artifacts,"store",side_effect=historical_bundle):
                task, claim, old_final, bundle, layout = flow.prepared()
            body = flow.fixture.backend.get(storage._reference_key(old_final), max_bytes=storage.MAX_IMAGE_BYTES)[0]
            value = json.loads(bundle)
            manifest = json.loads(base64.b64decode(value["files"]["render-manifest.json"]))
            manifest["revision"] = "offline-inflight-result"
            raw = json.dumps(manifest).encode()
            value["files"]["render-manifest.json"] = base64.b64encode(raw).decode()
            value["manifest_sha256"] = artifacts.digest(raw)
            layout = {**layout,"manifest_sha256":artifacts.digest(raw)}
            layout.pop("editable_ref")
            def stub_runtime(**kwargs):
                flow.settle(claim)
                kwargs["hooks"].on_candidate({"final_sha256":layout["final_sha256"],
                    "source_hashes":layout["source_hashes"],"qc":None},body)
                qc = {key:True for key in ("approved","text_matches","facts_preserved","subject_preserved")}
                qc.update(issues=[],local_adjustment=None,design_checks={key:True for key in service.cover_runtime._DESIGN_CHECKS},
                    final_sha256=layout["final_sha256"],source_hashes=layout["source_hashes"])
                return service.cover_runtime.CoverResult(body,body,layout,{"schema_version":3},qc,[],[],
                    {"editable_bundle":json.dumps(value).encode()})
            with mock.patch.dict(os.environ,{"NOTEAI_COVER_AGENT_STATE_ROOT":flow.fixture.temp.name + "/agent"}):
                result = service._run_claim(claim,runtime=stub_runtime)
            self.assertEqual(result["status"],"completed",result)
            self.assertEqual(result["billing"]["credits_used"],8)
            row = db.fetchone("SELECT final_media_ref,base_media_ref,design_json,policy_json FROM cover_jobs WHERE id=?",(task["job_id"],))
            self.assertEqual(json.loads(row["policy_json"])["retention_seconds"],90 * 86400)
            design = json.loads(row["design_json"])
            refs = [row["final_media_ref"],row["base_media_ref"],design["candidate_evidence"][0]["media_ref"]]
            for ref_id in refs:
                ref,_ = storage.load_media_bytes(ref_id,user_id=flow.fixture.user)
                self.assertEqual(datetime.fromisoformat(ref.expires_at)-datetime.fromisoformat(ref.created_at),timedelta(days=90))
                self.assertIn("/cover_v1/",storage._reference_key(ref))
            final_layout = jobs.get_layout(flow.fixture.user,task["job_id"])
            descriptor = artifacts.reference(final_layout["editable_ref"])
            self.assertEqual(datetime.fromisoformat(descriptor.expires_at)-datetime.fromisoformat(descriptor.created_at),timedelta(days=90))
            self.assertIn("/cover_v1/",storage._reference_key(descriptor,payload=True))
            self.assertGreater(datetime.fromisoformat(result["expires_at"]),flow.fixture.now+timedelta(days=89))
            # A legacy claim cannot be finalized with only three-day assets.
            with mock.patch.object(jobs,"get_job",return_value=None), \
                    mock.patch.object(jobs,"_verified_image",return_value=type("Ref",(),{"expires_at":(flow.fixture.now+timedelta(days=3)).isoformat()})()), \
                    mock.patch.object(jobs,"_owner_row",return_value={"id":task["job_id"],"status":"running","policy_json":row["policy_json"]}):
                with self.assertRaisesRegex(ValueError,"approved retention"):
                    jobs.complete_job(claim,final_media_ref="fixture",base_media_ref="fixture",layout=final_layout,qc_passed=True)
        finally:
            flow.tearDown()

    def test_old_ninety_day_free_edit_keeps_original_deadline_and_namespace(self):
        flow = editable_fixtures.AgentArtifactTests()
        flow.setUp()
        try:
            flow.fixture.policy["retention_seconds"] = 90 * 86400
            original_media, original_bundle = storage.store_media_bytes, artifacts.store
            def historical_media(*args, **kwargs):
                if kwargs.get("lifecycle") == "cover_3d_v1":
                    kwargs.update(ttl_seconds=90 * 86400, lifecycle="cover_v1")
                return original_media(*args, **kwargs)
            def historical_bundle(*args, **kwargs):
                return original_bundle(*args, **{**kwargs, "ttl_seconds":90 * 86400, "lifecycle":"cover_v1"})
            # Create faithful old metadata through the prior writer contract;
            # the test never mutates saved object metadata or frozen history.
            with mock.patch.object(jobs, "RETENTION_SECONDS", 90 * 86400), \
                    mock.patch.object(storage, "store_media_bytes", side_effect=historical_media), \
                    mock.patch.object(artifacts, "store", side_effect=historical_bundle):
                task, _, final, bundle, layout, saved = flow.complete()
            balances = flow.fixture.balances()
            count = db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0]
            value = json.loads(bundle)
            manifest = json.loads(base64.b64decode(value["files"]["render-manifest.json"]))
            manifest["qc_status"] = "USER_ADJUSTED_NOT_VISUALLY_REVIEWED"
            raw = json.dumps(manifest).encode()
            value["files"]["render-manifest.json"] = base64.b64encode(raw).decode()
            value["manifest_sha256"] = artifacts.digest(raw)
            edited_bundle = json.dumps(value).encode()
            edited_layout = {**layout, "manifest_sha256":artifacts.digest(raw),
                "qc_status":"USER_ADJUSTED_NOT_VISUALLY_REVIEWED"}
            edited_layout.pop("editable_ref")
            with mock.patch.object(artifacts, "cli", return_value={}), \
                    mock.patch.object(artifacts, "capture", return_value=(flow.fixture.backend.get(
                        storage._reference_key(final), max_bytes=storage.MAX_IMAGE_BYTES)[0], edited_bundle, edited_layout)):
                updated = service.adjust(flow.fixture.user, task["job_id"], text="真实门店", position=None,
                    expected_revision=1, layer_id="title")
            self.assertEqual(updated["expires_at"], saved["expires_at"])
            self.assertEqual(updated["asset_revision"], 2)
            final_ref = jobs.asset_reference(flow.fixture.user, task["job_id"])
            reference, _ = storage.load_media_bytes(final_ref, user_id=flow.fixture.user)
            self.assertIn("/cover_v1/", storage._reference_key(reference))
            current = jobs.get_layout(flow.fixture.user, task["job_id"])
            source = artifacts.reference(current["editable_ref"])
            self.assertIn("/cover_v1/", storage._reference_key(source, payload=True))
            self.assertGreaterEqual(source.expires_at, saved["expires_at"])
            self.assertGreater(datetime.fromisoformat(source.expires_at), flow.fixture.now + timedelta(days=89))
            self.assertEqual(flow.fixture.balances(), balances)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], count)
            self.assertEqual(artifacts.validate_saved(flow.fixture.user, current), edited_bundle)
        finally:
            flow.tearDown()


if __name__ == "__main__":
    unittest.main()
