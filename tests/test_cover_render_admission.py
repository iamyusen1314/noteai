"""Real shared renderer/CPU queues with controlled browser work; no provider."""
import concurrent.futures
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_agent_artifacts as artifacts
import model_admission
import public_product


class CoverRenderAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_PRODUCT": "0", "NOTEAI_MODEL_CAPACITY_ENABLED": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.manager = model_admission.Admission(model_admission.Limits(media_workers=2))
        self.current = mock.patch.object(model_admission, "current", return_value=self.manager)
        self.current.start()
        self.addCleanup(self.current.stop)
        self.network = mock.patch("socket.socket.connect", side_effect=AssertionError("No external calls"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def invoke(self, user, function):
        operation, owns = self.manager.register(user, "local-render-" + user, route="/covers")
        invocation = public_product.Invocation(user, "local-render-" + user, route="/covers")
        invocation.admission_state = operation
        marker = public_product._invocation.set(invocation)
        try:
            return function(operation)
        finally:
            public_product._invocation.reset(marker)
            if owns:
                self.manager.finish(operation)

    def test_waiting_for_report_cpu_keeps_no_extra_browser_and_timeout_releases_everything(self):
        report, _ = self.manager.register("report-owner", "report-original", route="/generate")
        tickets = [self.manager.media.acquire(report, "report-cpu-" + str(i), "media_worker") for i in range(2)]
        entered = []
        try:
            def blocked(operation):
                with artifacts.render_slot(deadline=time.monotonic() + .05):
                    entered.append(operation)
            with self.assertRaisesRegex(ValueError, "COVER_EDITABLE_RENDER_BUSY"):
                self.invoke("cover-owner", blocked)
            self.assertEqual(entered, [])
            self.assertEqual(len(self.manager.media.active), 2)
            self.assertEqual(self.manager.media._tickets(), [])
        finally:
            for ticket in tickets:
                self.manager.media.release(ticket)
            self.manager.finish(report)
        self.invoke("later-owner", lambda operation: self.acquire_once(operation))
        self.assertEqual(self.manager.media.active, {})
        self.assertEqual(self.manager.operations, {})

    def acquire_once(self, operation):
        with artifacts.render_slot(deadline=time.monotonic() + 1):
            self.assertEqual(len(self.manager.media.active), 1)
            self.assertIs(next(iter(self.manager.media.active.values())).operation, operation)

    def test_initial_renderer_and_free_edit_share_one_slot_until_failure_cleanup(self):
        initial_entered, release_initial, second_started = threading.Event(), threading.Event(), threading.Event()
        overlap = []

        def initial(operation):
            with artifacts.render_slot(deadline=time.monotonic() + 3):
                self.assertEqual(len(self.manager.media.active), 1)
                initial_entered.set()
                if not release_initial.wait(2):
                    raise AssertionError("Original browser cleanup was not released")
                raise RuntimeError("controlled-renderer-failure-after-cleanup")

        def edit(operation):
            second_started.set()
            with artifacts.render_slot(deadline=time.monotonic() + .1):
                overlap.append(True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.invoke, "initial-owner", initial)
            self.assertTrue(initial_entered.wait(1))
            second = pool.submit(self.invoke, "edit-owner", edit)
            self.assertTrue(second_started.wait(1))
            try:
                with self.assertRaisesRegex(ValueError, "COVER_EDITABLE_RENDER_BUSY"):
                    second.result(timeout=1)
                self.assertEqual(overlap, [])
                self.assertEqual(len(self.manager.media.active), 1)
            finally:
                release_initial.set()
            with self.assertRaisesRegex(RuntimeError, "controlled-renderer-failure"):
                first.result(timeout=1)
        self.invoke("next-owner", lambda operation: self.acquire_once(operation))
        self.assertEqual(self.manager.media.active, {})
        self.assertEqual(self.manager.media._tickets(), [])
        self.assertEqual(self.manager.operations, {})

    def test_cancelled_owner_cannot_enter_and_does_not_hold_renderer_or_cpu(self):
        def cancelled(operation):
            self.manager.cancel(operation)
            with artifacts.render_slot(deadline=time.monotonic() + 1):
                self.fail("Cancelled owner entered local renderer")
        with self.assertRaisesRegex(ValueError, "COVER_EDITABLE_RENDER_BUSY"):
            self.invoke("cancelled-owner", cancelled)
        self.invoke("other-owner", lambda operation: self.acquire_once(operation))
        self.assertEqual(self.manager.media.active, {})
        self.assertEqual(self.manager.operations, {})

    def test_cli_timeout_cleans_original_process_group_before_releasing_permits(self):
        import cover_agent_runtime
        original_popen = subprocess.Popen
        original_stop = cover_agent_runtime._stop_host
        cleanup_observations = []
        processes = []

        class ShortCommunication:
            def __init__(self, *args, **kwargs):
                self.process = original_popen(*args, **kwargs)
                processes.append(self.process)

            def __getattr__(self, name):
                return getattr(self.process, name)

            def communicate(self, body, timeout):
                return self.process.communicate(body, timeout=.25)

        def stop(process):
            cleanup_observations.append(len(self.manager.media.active))
            original_stop(process)
            cleanup_observations.append(len(self.manager.media.active))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover_editable").mkdir()
            # A real process plus descendant stands in for a hung local CLI.
            # The renderer, provider and browser are not mocked as successful.
            (root / "cover_editable/cli.mjs").write_text(
                "import subprocess,sys,time\n"
                "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                "time.sleep(60)\n")
            with mock.patch.object(artifacts, "ROOT", root), \
                    mock.patch.dict(os.environ, {"NOTEAI_COVER_NODE": sys.executable}), \
                    mock.patch.object(artifacts.subprocess, "Popen", ShortCommunication), \
                    mock.patch.object(cover_agent_runtime, "_stop_host", side_effect=stop):
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.invoke("timeout-owner", lambda operation: artifacts.cli("edit", {
                        "output_root": str(root / "revisions")}))
        self.assertEqual(cleanup_observations, [1, 1])
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.invoke("after-timeout", lambda operation: self.acquire_once(operation))
        self.assertEqual(self.manager.media.active, {})
        self.assertEqual(self.manager.operations, {})

    def test_actual_local_cli_renders_and_releases_original_cpu_ticket_without_extra_cleanup(self):
        import cover_agent_runtime
        from tests.test_cover_agent_artifacts import AgentTitleCLIContractTests
        fixture = AgentTitleCLIContractTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with mock.patch.dict(os.environ, {**fixture.env, "NOTEAI_COVER_NODE": fixture.node}), \
                mock.patch.object(cover_agent_runtime, "_stop_host", wraps=cover_agent_runtime._stop_host) as stop:
            result = self.invoke("actual-cli-owner", lambda operation: artifacts.cli("render", fixture.request))
        self.assertTrue(result["ok"])
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["external_requests"], 0)
        final, encoded, layout = artifacts.capture(result, expected_sources={
            "synthetic-source-1": artifacts.digest(fixture.photo)})
        self.assertEqual(artifacts.digest(final), layout["final_sha256"])
        self.assertTrue(encoded)
        stop.assert_not_called()
        self.assertEqual(self.manager.media.active, {})
        self.assertEqual(self.manager.operations, {})

    def test_uncertain_cli_cleanup_keeps_lease_even_when_outer_cleanup_error_replaces_exception(self):
        import cover_agent_runtime
        old_slot = artifacts._EDIT_SLOT
        old_quarantine = artifacts._QUARANTINED_RENDERERS
        # Only this test's genuine queue and semaphore are quarantined. The
        # production module's renderer is never consumed by this failure case.
        slot = threading.BoundedSemaphore(1)
        fake_process = mock.Mock()
        fake_process.communicate.side_effect = subprocess.TimeoutExpired("test-cli", .1)

        def uncertain(operation):
            with artifacts.render_slot(deadline=time.monotonic() + 1):
                try:
                    artifacts.cli("edit", {"output_root": str(Path(directory) / "revisions")}, _has_slot=True)
                finally:
                    raise OSError("controlled-outer-cleanup-error")

        with mock.patch.object(artifacts, "_EDIT_SLOT", slot), \
                mock.patch.object(artifacts, "_QUARANTINED_RENDERERS", []), \
                mock.patch.object(artifacts.subprocess, "Popen", return_value=fake_process), \
                mock.patch.object(cover_agent_runtime, "_stop_host", side_effect=PermissionError("controlled")), \
                tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(OSError, "controlled-outer-cleanup-error"):
                self.invoke("uncertain-owner", uncertain)
            self.assertEqual(len(artifacts._QUARANTINED_RENDERERS), 1)
            self.assertEqual(len(self.manager.media.active), 1)
            self.assertFalse(slot.acquire(blocking=False))
            self.assertEqual(len(self.manager.operations), 1)
            # Controlled fixture teardown only; this does not represent a
            # production recovery or authorize retry of an unknown process.
            queue, ticket, retained_slot = artifacts._QUARANTINED_RENDERERS[0]
            queue.release(ticket)
            retained_slot.release()
        self.assertIs(artifacts._EDIT_SLOT, old_slot)
        self.assertIs(artifacts._QUARANTINED_RENDERERS, old_quarantine)
