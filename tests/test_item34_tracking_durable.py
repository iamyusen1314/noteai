import base64
import copy
import errno
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import run_item34_tracking_durable as durable


class MemoryJournal:
    def __init__(self, fail=None):
        self.events = []
        self.fail = fail

    def write(self, event, **data):
        if event == self.fail or self.fail == "all":
            raise OSError("simulated_disk_failure")
        self.events.append((event, copy.deepcopy(data)))


class DurableTrackingTests(unittest.TestCase):
    def setUp(self):
        self.original = {"present": False, "sha256": None, "updated_at": None, "value_b64": None}
        raw = b'{"enabled":true}'
        self.active = {"present": True, "sha256": hashlib.sha256(raw).hexdigest(),
                       "updated_at": "2026-09-07T06:00:00+00:00",
                       "value_b64": base64.b64encode(raw).decode()}
        self.saved = {"event": "authorization", "image": "registry.invalid/app@sha256:" + "a" * 64,
                      "stage": "24h", "track_id": "00000000-0000-4000-8000-000000000001",
                      "initial_private": {"config": self.original},
                      "active_config_updated_at": self.active["updated_at"],
                      "authorization": {"transition_id": "b" * 64}}
        test = self
        self.transitions = []
        self.current = copy.deepcopy(self.active)

        class Adapter:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                self.runtime_state = {"running": False}
                self.initial_private = copy.deepcopy(test.saved["initial_private"])
                self.active_config_updated_at = test.saved["active_config_updated_at"]
                self.latest_private = {"config": copy.deepcopy(test.current)}
                self.last_worker = {"run": {"run_id": "actual-run"}}

            def authorization(self):
                return copy.deepcopy(test.saved["authorization"])

            def read_snapshot(self, *, phase):
                test.assertEqual(phase, "failure")
                self.latest_private = {"config": copy.deepcopy(test.current)}
                return {"attempts": {"rows": []}}

            def transition(self, phase, authorization):
                test.transitions.append((phase, self.active_config_updated_at, authorization))
                if phase == "restore":
                    test.current = copy.deepcopy(test.original)
                return {"phase": phase}

            def cleanup_known_worker(self):
                test.transitions.append(("cleanup",))

            def run_worker(self, argv):
                test.fail("recovery must never call provider")

        self.adapter = Adapter
        self.wrapper = SimpleNamespace(
            HostAdapter=Adapter, STAGES={"24h", "3d"}, LOCK_PATH=Path("unused"),
            _exclusive_lock=lambda path: nullcontext(),
            _quiesce_named_container=lambda name: {"after_running": False},
            _service_state=lambda: {"running": False}, ACTIVE_CONFIG={"enabled": True},
            _sha256=lambda data: hashlib.sha256(data).hexdigest(),
            _canonical_json=lambda value: json.dumps(value, separators=(",", ":")).encode(),
        )

    def test_authorization_is_durable_before_activation(self):
        journal = MemoryJournal()
        adapter = durable.logging_adapter(self.adapter, journal)(**{
            key: self.saved[key] for key in ("image", "stage", "track_id")})
        authorization = adapter.authorization()
        self.assertEqual(journal.events[0][0], "authorization")
        self.assertEqual(journal.events[0][1]["active_config_updated_at"], self.active["updated_at"])
        self.assertEqual(authorization, self.saved["authorization"])

    def test_failed_authorization_fsync_prevents_activation(self):
        adapter = durable.logging_adapter(self.adapter, MemoryJournal("authorization"))(**{
            key: self.saved[key] for key in ("image", "stage", "track_id")})
        with self.assertRaises(OSError):
            adapter.authorization()
        self.assertEqual(self.transitions, [])

    def test_logging_failure_does_not_block_safety_restore(self):
        adapter = durable.logging_adapter(self.adapter, MemoryJournal("all"))(**{
            key: self.saved[key] for key in ("image", "stage", "track_id")})
        with self.assertRaises(OSError):
            adapter.transition("restore", self.saved["authorization"])
        self.assertEqual(self.current, self.original)

    def test_preserves_worker_before_cleanup(self):
        journal = MemoryJournal()
        adapter = durable.logging_adapter(self.adapter, journal)(**{
            key: self.saved[key] for key in ("image", "stage", "track_id")})
        adapter.cleanup_known_worker()
        self.assertEqual(journal.events[0][1]["worker"], adapter.last_worker)
        self.assertEqual(self.transitions, [("cleanup",)])

    def test_restore_uses_saved_cas_and_does_not_generate_authorization(self):
        with patch.object(self.adapter, "authorization", side_effect=AssertionError("must not regenerate")):
            result = durable.restore(self.wrapper, MemoryJournal(), self.saved)
        self.assertTrue(result["configuration_restored"])
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(self.transitions, [("restore", self.active["updated_at"], self.saved["authorization"])])

    def test_restore_already_original_is_read_only(self):
        self.current = copy.deepcopy(self.original)
        result = durable.restore(self.wrapper, MemoryJournal(), self.saved)
        self.assertFalse(result["configuration_write_used"])
        self.assertEqual(self.transitions, [])

    def test_restore_refuses_concurrent_config(self):
        self.current["updated_at"] = "2026-09-07T06:01:00+00:00"
        with self.assertRaisesRegex(ValueError, "compare_and_swap"):
            durable.restore(self.wrapper, MemoryJournal(), self.saved)
        self.assertEqual(self.transitions, [])

    def test_recovery_log_failure_restores_but_does_not_claim_durability(self):
        with self.assertRaisesRegex(OSError, "not_durable"):
            durable.restore(self.wrapper, MemoryJournal("all"), self.saved)
        self.assertEqual(self.current, self.original)

    def test_restore_cli_storage_failure_still_restores_and_reports_unknown(self):
        for failure in ("create", "start"):
            self.current = copy.deepcopy(self.active)
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "24h.host.jsonl"
                source.write_text(json.dumps(self.saved) + "\n")
                source.chmod(0o600)
                target = Path(directory) / "24h.restore.jsonl"
                with patch.object(os, "geteuid", return_value=0), \
                     patch.object(durable, "saved_authorization", return_value=self.saved), \
                     patch.object(durable, "load_wrapper", return_value=self.wrapper):
                    error = OSError(errno.ENOSPC, "disk_full")
                    if failure == "create":
                        storage = patch.object(durable, "Journal", side_effect=error)
                    else:
                        journal = MemoryJournal()
                        journal.write = lambda *args, **kwargs: (_ for _ in ()).throw(error)
                        journal.close = lambda: None
                        storage = patch.object(durable, "Journal", return_value=journal)
                    with storage, self.assertRaisesRegex(OSError, "not_durable"):
                        durable.main(["restore", "--journal", str(target), "--restore-from", str(source)])
                self.assertEqual(self.current, self.original)

    def test_existing_recovery_journal_is_not_bypassed(self):
        with patch.object(os, "geteuid", return_value=0), \
             patch.object(durable, "saved_authorization", return_value=self.saved), \
             patch.object(durable, "load_wrapper", return_value=self.wrapper), \
             patch.object(durable, "Journal", side_effect=FileExistsError(errno.EEXIST, "exists")):
            with self.assertRaises(FileExistsError):
                durable.main(["restore", "--journal", "/unused/result", "--restore-from", "/unused/source"])
        self.assertEqual(self.transitions, [])

    def test_real_wrapper_failure_path_still_sets_session_stop_after_disk_failure(self):
        wrapper = durable.load_wrapper(prospective=True)
        stopped = []
        calls = []
        test = self

        class Adapter(self.adapter):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.worker_name = "noteai-item34-tracking-24h"

            def read_snapshot(self, *, phase):
                self.latest_private = {"failure": {"status": "failed", "error_code": "challenge"}}
                return {}

            def run_worker(self, argv):
                calls.append(argv)
                self.last_worker = {"result": {"attempted": 1}}
                return {"exit_code": 1}

            failure_readback = wrapper.HostAdapter.failure_readback

            def read_transition_state(self):
                return {}

            def schedule_3d(self, *args):
                test.fail("failed sample must not schedule 3d")

            def persist_session_block(self, failure):
                stopped.append(failure)

        class BreakAfterWorker(MemoryJournal):
            def write(self, event, **data):
                if event == "worker_result":
                    self.fail = "all"
                return super().write(event, **data)

        def checkpoint(**kwargs):
            kwargs["run_worker"](("python", "crawler_worker.py", "--once", "--limit", "1"))
            test.fail("disk failure must prevent success")

        with patch.object(os, "geteuid", return_value=0), \
             patch.object(wrapper, "_exclusive_lock", return_value=nullcontext()), \
             patch.object(wrapper, "HostAdapter", Adapter), \
             patch.object(wrapper, "_quiesce_named_container", return_value={"after_running": False}), \
             patch.object(wrapper.checkpoint, "execute_24h_checkpoint", side_effect=checkpoint):
            with self.assertRaises(wrapper.ProductionAdapterError):
                durable.execute(wrapper, BreakAfterWorker(), stage="24h",
                                track_id=self.saved["track_id"], image=self.saved["image"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(stopped, [{"status": "failed", "error_code": "challenge"}])

    def test_journal_is_private_exclusive_and_crash_tail_is_not_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "24h.host.jsonl"
            journal = durable.Journal(path)
            journal.write("authorization", **{k: v for k, v in self.saved.items() if k != "event"})
            journal.close()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                durable.Journal(path)
            with path.open("ab") as stream:
                stream.write(b'{"event":"result","result":{"status":"SUCCEEDED"}}')
            self.assertEqual(durable.saved_authorization(path)["authorization"], self.saved["authorization"])

    def test_journal_fsync_failure_blocks_further_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = durable.Journal(Path(directory) / "run.jsonl")
            try:
                with patch.object(os, "fsync", side_effect=OSError("disk")):
                    with self.assertRaises(OSError):
                        journal.write("authorization", **{k: v for k, v in self.saved.items() if k != "event"})
                with self.assertRaisesRegex(OSError, "previously_failed"):
                    journal.write("result", result={"status": "SUCCEEDED"})
            finally:
                journal.close()

    def test_legacy_hash_is_frozen_and_prospective_source_binding_is_exact(self):
        self.assertEqual(durable.WRAPPER_SHA256,'3d9e65c4535226a0a7d4c499558bff1d19ed69ebbbcf647a657700aff8c85e8a')
        self.assertEqual(hashlib.sha256(durable.WRAPPER.read_bytes()).hexdigest(), durable.PROSPECTIVE_WRAPPER_SHA256)
        with self.assertRaisesRegex(ValueError,'approved_wrapper_changed'):durable.load_wrapper()

    def test_prospective_recovery_restores_exact_config_even_with_unknown_sampling(self):
        from tests.test_item34_tracking_checkpoint_executor import prospective_binding
        binding=prospective_binding();saved={**self.saved,'track_id':binding['track_id'],'observation_binding':binding}
        test=self
        class Adapter(self.adapter):
            def read_config_snapshot(self):return {'config':copy.deepcopy(test.current)}
            def read_snapshot(self,**kwargs):raise ValueError('generation history changed')
        self.wrapper.HostAdapter=Adapter
        self.wrapper._worker_name=lambda stage:'noteai-item34-tracking-g1-'+stage
        stops=[]
        self.wrapper._quiesce_worker=lambda name,image:stops.append((name,image)) or {'after_running':False}
        with durable.checkpoint.observation_context(binding):
            result=durable.restore(self.wrapper,MemoryJournal(),saved)
        self.assertTrue(result['configuration_restored'])
        self.assertEqual(result['sampling_acceptance'],'UNKNOWN')
        self.assertEqual(len(self.transitions),1)
        self.assertEqual(stops,[('noteai-item34-tracking-g1-24h',saved['image'])])

    def test_cross_binding_saved_track_is_rejected_before_any_stop(self):
        from tests.test_item34_tracking_checkpoint_executor import prospective_binding
        binding=prospective_binding();saved={**self.saved,'observation_binding':binding}
        with durable.checkpoint.observation_context(binding), \
             patch.object(self.wrapper,'_quiesce_named_container') as stop:
            with self.assertRaisesRegex(ValueError,'saved_observation_binding'):
                durable.restore(self.wrapper,MemoryJournal(),saved)
            stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
