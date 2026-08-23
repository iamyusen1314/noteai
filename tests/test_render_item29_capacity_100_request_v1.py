import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import render_item29_capacity_100_request_v1 as renderer


PLAN_NONCE = "5c22acf5-1f6a-49e2-9787-036c1cbb43ea"
OPERATIONS = [
    str(uuid.uuid5(uuid.UUID(PLAN_NONCE), f"operation:{index:03d}"))
    for index in range(100)
]


def input_value(action="preflight", operations=None):
    return {
        "action": action,
        "plan_nonce": PLAN_NONCE,
        "item28_dependency": copy.deepcopy(
            renderer.FROZEN_ITEM28_DEPENDENCY
        ),
        "operation_ids": list(operations or []),
    }


class RenderItem29CapacityRequestTests(unittest.TestCase):
    def test_write_once_send_file_is_fixed_to_each_existing_host(self):
        expected = {
            "stage-api-c": renderer.API_C_INSTANCE,
            "stage-worker-c": renderer.WORKER_C_INSTANCE,
            "stage-worker-f": renderer.WORKER_F_INSTANCE,
        }
        for action, target in expected.items():
            with self.subTest(action=action):
                request, validation = renderer.render_request(input_value(action))
                self.assertEqual(set(request), renderer.SEND_FILE_KEYS)
                self.assertEqual(request["InstanceId"], [target])
                self.assertEqual(request["Name"], renderer.SOURCE_NAME)
                self.assertEqual(request["TargetDir"], "/run")
                self.assertEqual(request["FileMode"], "0400")
                self.assertIs(request["Overwrite"], False)
                self.assertEqual(validation["api"], "SendFile")

    def test_phase_targets_and_fresh_names_are_exact(self):
        expected = {
            "preflight": renderer.API_C_INSTANCE,
            "admit": renderer.API_C_INSTANCE,
            "admit-retry": renderer.API_C_INSTANCE,
            "resolve": renderer.API_C_INSTANCE,
            "dispatch": renderer.API_C_INSTANCE,
            "dispatch-retry": renderer.API_C_INSTANCE,
            "dispatch-readback": renderer.API_C_INSTANCE,
            "preclaim-c": renderer.WORKER_C_INSTANCE,
            "process-c": renderer.WORKER_C_INSTANCE,
            "preclaim-f": renderer.WORKER_F_INSTANCE,
            "process-f": renderer.WORKER_F_INSTANCE,
            "process-readback-c": renderer.WORKER_C_INSTANCE,
            "process-readback-f": renderer.WORKER_F_INSTANCE,
            "observe": renderer.API_C_INSTANCE,
            "cleanup": renderer.API_C_INSTANCE,
            "cleanup-retry": renderer.API_C_INSTANCE,
            "source-cleanup-worker-c": renderer.WORKER_C_INSTANCE,
            "source-cleanup-worker-f": renderer.WORKER_F_INSTANCE,
            "source-cleanup-api-c": renderer.API_C_INSTANCE,
        }
        for action, target in expected.items():
            operations = [] if action in renderer.NO_OPERATION_ACTIONS else OPERATIONS
            with self.subTest(action=action):
                request, validation = renderer.render_request(
                    input_value(action, operations)
                )
                self.assertEqual(set(request), renderer.RUN_COMMAND_KEYS)
                self.assertEqual(request["InstanceId"], [target])
                self.assertEqual(
                    request["Name"], f"noteai-item29-{action}-20260824-v1"
                )
                self.assertEqual(request["RepeatMode"], "Once")
                self.assertIs(request["KeepCommand"], True)
                self.assertEqual(validation["api"], "RunCommand")

    def test_wrapper_uses_fixed_image_minimum_database_env_and_no_provider_secret(self):
        request, _ = renderer.render_request(input_value("process-c", OPERATIONS))
        wrapper = base64.b64decode(request["CommandContent"]).decode("ascii")
        self.assertIn("--pull=never", wrapper)
        self.assertIn("--read-only", wrapper)
        self.assertIn("--cap-drop=ALL", wrapper)
        self.assertIn("--network=bridge", wrapper)
        self.assertIn(renderer.IMAGE, wrapper)
        self.assertIn(renderer.EXECUTOR_SHA256, wrapper)
        self.assertIn("grep '^DATABASE_URL='", wrapper)
        self.assertIn("/etc/noteai/private-storage.env", wrapper)
        self.assertNotIn("--env-file /etc/noteai/ai-worker.env", wrapper)
        self.assertIn("unset ANTHROPIC_API_KEY", wrapper)
        self.assertNotIn("ANTHROPIC_API_KEY=", wrapper)
        self.assertIn("NOTEAI_RUNTIME_ROLE='ai-worker'", wrapper)
        self.assertIn("NOTEAI_ITEM29_HOST_LABEL='Worker-C'", wrapper)
        self.assertIn("NOTEAI_SKIP_MODEL_ARTIFACT_CHECK=1", wrapper)
        self.assertIn("org.opencontainers.image.revision", wrapper)
        self.assertIn("com.noteai.runtime.role", wrapper)
        self.assertIn(".RepoDigests", wrapper)
        self.assertIn(".Config.Entrypoint", wrapper)
        self.assertIn(".Config.Cmd", wrapper)

    def test_dispatcher_never_receives_private_storage_environment(self):
        for action in ("dispatch", "dispatch-retry", "dispatch-readback"):
            with self.subTest(action=action):
                request, _ = renderer.render_request(
                    input_value(action, OPERATIONS)
                )
                wrapper = base64.b64decode(
                    request["CommandContent"]
                ).decode("ascii")
                self.assertIn("/etc/noteai/ai-dispatcher.env", wrapper)
                self.assertNotIn(
                    "--env-file /etc/noteai/private-storage.env", wrapper
                )
                self.assertIn("NOTEAI_DURABLE_AI_COMPONENT='dispatcher'", wrapper)

    def test_phase_wrappers_retain_source_and_remove_only_owned_container(self):
        for action in ("process-c", "process-f", "cleanup"):
            with self.subTest(action=action):
                request, _ = renderer.render_request(
                    input_value(action, OPERATIONS)
                )
                wrapper = base64.b64decode(
                    request["CommandContent"]
                ).decode("ascii")
                self.assertNotIn('/bin/rm -f "$src_gz"', wrapper)
                self.assertIn("noteai.task=item29-capacity-100-v1", wrapper)
                self.assertIn("docker rm -f", wrapper)
                self.assertIn('--cidfile "$cidfile"', wrapper)
                self.assertIn("bound=$(", wrapper)
                self.assertNotIn('docker rm -f "$container"', wrapper)
                self.assertIn('! /usr/bin/docker inspect "$container"', wrapper)
                self.assertIn('"$run_dir/database.env"', wrapper)
                self.assertIn('"$run_dir/storage.env"', wrapper)
                self.assertNotIn('"$run_dir"/*', wrapper)
                guarded = (
                    "noteai-ai-worker-acceptance"
                    if action.startswith("process")
                    else "noteai-ai-dispatcher-acceptance"
                )
                self.assertIn(guarded, wrapper)

    def test_source_cleanup_is_exact_idempotent_and_reads_back_zero(self):
        for action in (
            "source-cleanup-worker-c", "source-cleanup-worker-f",
            "source-cleanup-api-c",
        ):
            with self.subTest(action=action):
                request, validation = renderer.render_request(input_value(action))
                wrapper = base64.b64decode(
                    request["CommandContent"]
                ).decode("ascii")
                self.assertIn('/bin/rm -f "$src_gz"', wrapper)
                self.assertIn('[ ! -e "$src_gz" ]', wrapper)
                self.assertIn("source_residue_count", wrapper)
                self.assertIn("task_container_residue_count", wrapper)
                self.assertIn("task_container_removed_count", wrapper)
                self.assertIn("task_run_dir_removed_count", wrapper)
                self.assertIn("container ls -aq --no-trunc", wrapper)
                self.assertIn(".State.Running", wrapper)
                self.assertIn(renderer.IMAGE_CONFIG, wrapper)
                self.assertIn("700:0:0", wrapper)
                self.assertIn("-printf x -quit", wrapper)
                self.assertIn("container.cid executor.py database.env", wrapper)
                self.assertNotIn("docker run", wrapper)
                self.assertNotIn('docker rm -f "$cid"', wrapper)
                self.assertNotIn("rm -rf", wrapper)
                self.assertNotIn('"$run_dir"/*', wrapper)
                self.assertIs(validation["same_request_resubmit_allowed"], True)

    def test_source_cleanup_container_names_are_host_specific(self):
        expected = {
            "source-cleanup-api-c": (
                "/noteai-item29-admit-retry", "/noteai-item29-process-c"
            ),
            "source-cleanup-worker-c": (
                "/noteai-item29-process-c", "/noteai-item29-process-f"
            ),
            "source-cleanup-worker-f": (
                "/noteai-item29-process-f", "/noteai-item29-process-c"
            ),
        }
        for action, (allowed, forbidden) in expected.items():
            with self.subTest(action=action):
                request, _ = renderer.render_request(input_value(action))
                wrapper = base64.b64decode(
                    request["CommandContent"]
                ).decode("ascii")
                self.assertIn(allowed, wrapper)
                self.assertNotIn(forbidden, wrapper)

    def test_admit_retry_is_the_only_retryable_admission_action(self):
        normal, normal_validation = renderer.render_request(input_value("admit"))
        retry, retry_validation = renderer.render_request(
            input_value("admit-retry")
        )
        self.assertNotEqual(normal["ClientToken"], retry["ClientToken"])
        self.assertIs(normal_validation["same_request_resubmit_allowed"], False)
        self.assertIs(retry_validation["same_request_resubmit_allowed"], True)
        wrapper = base64.b64decode(retry["CommandContent"]).decode("ascii")
        self.assertIn("--phase 'admit'", wrapper)
        self.assertIn(renderer.TASK_ID, wrapper)

    def test_cleanup_retry_has_a_fresh_token_and_exact_same_phase(self):
        normal, normal_validation = renderer.render_request(
            input_value("cleanup", OPERATIONS)
        )
        retry, retry_validation = renderer.render_request(
            input_value("cleanup-retry", OPERATIONS)
        )
        self.assertNotEqual(normal["ClientToken"], retry["ClientToken"])
        self.assertIs(normal_validation["same_request_resubmit_allowed"], False)
        self.assertIs(retry_validation["same_request_resubmit_allowed"], True)
        wrapper = base64.b64decode(retry["CommandContent"]).decode("ascii")
        self.assertIn("--phase 'cleanup'", wrapper)
        self.assertIn("/etc/noteai/private-storage.env", wrapper)

    def test_dispatcher_and_worker_formal_containers_must_be_absent(self):
        dispatch, _ = renderer.render_request(
            input_value("dispatch-readback", OPERATIONS)
        )
        dispatch_wrapper = base64.b64decode(
            dispatch["CommandContent"]
        ).decode("ascii")
        self.assertIn("noteai-ai-dispatcher-acceptance", dispatch_wrapper)

        worker, _ = renderer.render_request(
            input_value("process-readback-c", OPERATIONS)
        )
        worker_wrapper = base64.b64decode(
            worker["CommandContent"]
        ).decode("ascii")
        self.assertIn("noteai-ai-worker-acceptance", worker_wrapper)

    def test_operation_cardinality_and_dependency_drift_fail_closed(self):
        invalid = [
            input_value("dispatch", []),
            input_value("observe", OPERATIONS[:99]),
            input_value("preflight", OPERATIONS),
        ]
        dependency = input_value()
        dependency["item28_dependency"]["evidence_sha256"] = "0" * 64
        invalid.append(dependency)
        duplicate = input_value("cleanup", OPERATIONS)
        duplicate["operation_ids"][-1] = duplicate["operation_ids"][0]
        invalid.append(duplicate)
        for value in invalid:
            with self.subTest(value=value["action"]):
                with self.assertRaises(renderer.RequestError):
                    renderer.render_request(value)

    def test_executor_identity_is_exact_and_symlink_is_rejected(self):
        raw = renderer.read_executor(ROOT)
        self.assertEqual(len(raw), renderer.EXECUTOR_BYTES)
        self.assertEqual(renderer._sha(raw), renderer.EXECUTOR_SHA256)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.py"
            target.write_bytes(raw)
            path = root / renderer.EXECUTOR_REF
            path.parent.mkdir(parents=True)
            path.symlink_to(target)
            with self.assertRaisesRegex(renderer.RequestError, "executor_identity"):
                renderer.read_executor(root)

    def test_canonical_parser_rejects_duplicate_and_noncanonical_json(self):
        value = input_value()
        self.assertEqual(renderer.parse_canonical(renderer.canonical(value)), value)
        for raw in (
            b'{"action":"preflight","action":"preflight"}\n',
            (json.dumps(value, indent=2) + "\n").encode("ascii"),
        ):
            with self.assertRaises(renderer.RequestError):
                renderer.parse_canonical(raw)


if __name__ == "__main__":
    unittest.main()
