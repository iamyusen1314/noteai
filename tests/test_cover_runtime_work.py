"""PID1 work observation with real local edit persistence; no supplier calls."""
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_agent_artifacts as artifacts
import cover_jobs as jobs
import cover_service as service
import db
import model_admission as admission
import public_product
from tests import test_cover_agent_artifacts as fixtures


class CoverRuntimeWorkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AgentArtifactTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.env = mock.patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1",
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
            "NOTEAI_COVER_AGENT_STATE_ROOT": str(Path(self.fixture.fixture.temp.name) / "agent-state")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.manager = admission.Admission(admission.Limits(physical=1, media_workers=1))
        self.instance = mock.patch.object(admission, "_instance", self.manager)
        self.instance.start()
        self.addCleanup(self.instance.stop)
        self.network = mock.patch("socket.socket.connect", side_effect=AssertionError("No supplier network"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def candidate(self, bundle, layout):
        value = json.loads(bundle)
        manifest = json.loads(base64.b64decode(value["files"]["render-manifest.json"]))
        manifest.update(revision="runtime-work-edit", qc_status="USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
        raw = json.dumps(manifest).encode()
        value["files"]["render-manifest.json"] = base64.b64encode(raw).decode()
        value["manifest_sha256"] = artifacts.digest(raw)
        updated = deepcopy(layout)
        updated.update(manifest_sha256=artifacts.digest(raw), qc_status="USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
        updated.pop("editable_ref", None)
        return base64.b64decode(value["files"]["out/poster.png"]), json.dumps(value).encode(), updated

    def edit(self, task):
        # Normal authenticated identity, deliberately not a paid/registered task.
        invocation = public_product.Invocation(self.fixture.fixture.user, str(uuid.uuid4()), route="/covers/adjust")
        marker = public_product._invocation.set(invocation)
        try:
            return service.adjust(self.fixture.fixture.user, task["job_id"], text="真实门店", position=None,
                expected_revision=1, layer_id="title")
        finally:
            public_product._invocation.reset(marker)

    def test_free_edit_remains_visible_through_source_png_and_cas_without_new_paid_task(self):
        task, _, _, bundle, layout, original = self.fixture.complete()
        fixture = self.fixture.fixture
        balances = fixture.balances()
        calls = [dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls ORDER BY id")]
        entered = [threading.Event() for _ in range(3)]
        released = [threading.Event() for _ in range(3)]
        functions = (artifacts.store, service._store_image, jobs.update_adjusted_asset)

        def block(index):
            def controlled(*args, **kwargs):
                entered[index].set()
                if not released[index].wait(5):
                    raise AssertionError("Local persistence stage was not released")
                return functions[index](*args, **kwargs)
            return controlled

        with mock.patch.object(artifacts, "cli", return_value={}), \
                mock.patch.object(artifacts, "capture", return_value=self.candidate(bundle, layout)), \
                mock.patch.object(artifacts, "store", side_effect=block(0)), \
                mock.patch.object(service, "_store_image", side_effect=block(1)), \
                mock.patch.object(jobs, "update_adjusted_asset", side_effect=block(2)), \
                ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.edit, task)
            try:
                for index in range(3):
                    self.assertTrue(entered[index].wait(3), (index, future.exception() if future.done() else None))
                    snapshot = service.work_snapshot()
                    self.assertTrue(snapshot["confirmed"])
                    self.assertTrue(snapshot["active"])
                    self.assertEqual(snapshot["counts"]["cover_adjustments"], 1)
                    self.assertEqual(snapshot["counts"]["media_active"], 0)
                    self.assertEqual(self.manager.operations, {})
                    released[index].set()
                result = future.result(3)
            finally:
                for event in released:
                    event.set()
        self.assertEqual(result["asset_revision"], 2)
        self.assertEqual(result["expires_at"], original["expires_at"])
        self.assertEqual(fixture.balances(), balances)
        self.assertEqual([dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls ORDER BY id")], calls)
        self.assertFalse(service.work_snapshot()["active"])
        self.assertEqual(inspect.signature(service.adjust), inspect.signature(service.adjust.__wrapped__))
        print("COVER_RUNTIME_WORK_EDIT_PROOF=" + json.dumps({"source_save_visible": True,
            "png_save_visible": True, "cas_visible": True, "unregistered_operation": True,
            "expiry_and_unique_billing_unchanged": True, "supplier_calls": 0}, sort_keys=True))

    def test_persistence_failures_always_release_full_adjustment_count(self):
        task, _, _, bundle, layout, _ = self.fixture.complete()
        candidate = self.candidate(bundle, layout)
        targets = ((artifacts, "store"), (service, "_store_image"), (jobs, "update_adjusted_asset"))
        for owner, name in targets:
            with self.subTest(stage=name):
                def fail(*args, **kwargs):
                    self.assertEqual(service.work_snapshot()["counts"]["cover_adjustments"], 1)
                    raise OSError("CONTROLLED_LOCAL_PERSISTENCE_FAILURE")
                with mock.patch.object(artifacts, "cli", return_value={}), \
                        mock.patch.object(artifacts, "capture", return_value=candidate), \
                        mock.patch.object(owner, name, side_effect=fail):
                    with self.assertRaises(OSError):
                        self.edit(task)
                self.assertFalse(service.work_snapshot()["active"])
                self.assertEqual(jobs.get_job(self.fixture.fixture.user, task["job_id"])["asset_revision"], 1)
        print("COVER_RUNTIME_WORK_FAILURE_PROOF=" + json.dumps({"source_png_cas_finally": True,
            "old_revision_preserved": True, "supplier_calls": 0}, sort_keys=True))

    def test_snapshot_reads_actual_queue_locks_without_db_io_or_instantiating_manager(self):
        operations = [admission.Operation("private-owner-" + str(i), str(uuid.uuid4())) for i in range(2)]
        tickets = []
        for name in ("calls", "media", "buffers", "gateway_bodies", "gateway_dns"):
            queue = getattr(self.manager, name)
            for operation in operations:
                tickets.append((queue, queue.enqueue(operation, str(uuid.uuid4()), "doubao", weight=queue.capacity)))
        before = [(ticket.granted, ticket.closed, operation.outstanding)
            for _, ticket in tickets for operation in (ticket.operation,)]
        try:
            with mock.patch.object(admission, "current", side_effect=AssertionError("Do not instantiate")), \
                    mock.patch.object(db, "transaction", side_effect=AssertionError("No DB probe")), \
                    mock.patch.object(db, "fetchone", side_effect=AssertionError("No DB probe")), \
                    mock.patch.object(db, "fetchall", side_effect=AssertionError("No DB probe")), \
                    mock.patch.object(db, "execute", side_effect=AssertionError("No DB write")):
                snapshot = service.work_snapshot()
                for name in ("calls", "media", "buffers", "gateway_bodies", "gateway_dns"):
                    self.assertEqual(snapshot["counts"][name + "_active"], 1)
                    self.assertEqual(snapshot["counts"][name + "_waiting"], 1)
                self.assertEqual(before, [(ticket.granted, ticket.closed, ticket.operation.outstanding)
                    for _, ticket in tickets])
                with mock.patch.object(admission, "_instance", None):
                    self.assertFalse(service.work_snapshot()["active"])
                    self.assertIsNone(admission._instance)
            serialized = json.dumps(snapshot)
            self.assertNotIn("private-owner", serialized)
            self.assertTrue(all(type(value) is int and value >= 0 for value in snapshot["counts"].values()))
        finally:
            for queue, ticket in tickets:
                queue.release(ticket)
        print("COVER_RUNTIME_WORK_QUEUES_PROOF=" + json.dumps({"five_real_queues": True,
            "active_and_waiting": True, "no_queue_mutation_or_new_manager": True,
            "database_calls": 0, "supplier_calls": 0}, sort_keys=True))

    def test_actual_readiness_function_keeps_ready_truth_when_work_observation_fails(self):
        # Compile the actual health function, avoiding unrelated API import/setup.
        tree = ast.parse((Path(__file__).resolve().parents[1] / "model/api.py").read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name == "_readiness_payload")
        namespace = {"_database_readiness_probe": SimpleNamespace(result=lambda: {"ok": True}),
            "USE_V04_COMPOSITE": True, "get_v04_composite_model": lambda: object(),
            "_health_model_label": lambda: "local-fixture"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "actual_api_readiness", "exec"), namespace)
        readiness = namespace["_readiness_payload"]
        with mock.patch.object(admission, "current", side_effect=AssertionError("Do not instantiate")), \
                mock.patch.object(db, "transaction", side_effect=AssertionError("No extra DB probe")):
            healthy, status = readiness()
            self.assertEqual((status, healthy["status"]), (200, "ready"))
            self.assertTrue(healthy["runtime_work"]["confirmed"])
            with mock.patch.object(service, "work_snapshot", side_effect=RuntimeError("PRIVATE_ERROR_MUST_NOT_LEAK")):
                unconfirmed, status = readiness()
                self.assertEqual((status, unconfirmed["status"]), (200, "ready"))
                self.assertEqual(unconfirmed["checks"], healthy["checks"])
                self.assertEqual(unconfirmed["runtime_work"], {"schema": "noteai.runtime_work", "version": 1,
                    "confirmed": False, "counts": {}, "active": None})
                self.assertNotIn("PRIVATE_ERROR", json.dumps(unconfirmed))
            namespace["_database_readiness_probe"] = SimpleNamespace(result=lambda: {"ok": False})
            unready, status = readiness()
            self.assertEqual((status, unready["status"]), (503, "not_ready"))
            self.assertTrue(unready["runtime_work"]["confirmed"])
        print("COVER_RUNTIME_WORK_HEALTH_PROOF=" + json.dumps({"actual_function_ast": True,
            "ready_truth_unchanged": True, "observation_failure_unconfirmed": True,
            "no_private_error_leak": True, "supplier_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
