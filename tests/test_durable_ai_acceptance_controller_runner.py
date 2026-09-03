import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deploy.production import durable_ai_acceptance_controller_runner as runner


NONCE = "00000000-0000-4000-8000-000000000017"
OPERATION_ID = "00000000-0000-4000-8000-000000000117"
DATABASE_URL = "postgresql://noteai_app:synthetic@db.invalid:5432/noteai"


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        command,
        *,
        check,
        capture_output,
        text,
        input=None,
        timeout=None,
    ):
        self.calls.append((tuple(command), input))
        if command[:4] == [
            "/usr/bin/docker", "--context=default", "image", "inspect"
        ]:
            payload = [{
                "Id": runner.units.IMAGE_CONFIG,
                "Os": "linux",
                "Architecture": "amd64",
                "RepoDigests": [runner.units.IMAGE_REF],
                "Config": {
                    "User": "noteai",
                    "Labels": {
                        "org.opencontainers.image.revision": runner.units.C17_COMMIT,
                        "com.noteai.runtime.role": "ai-worker",
                    },
                    "Entrypoint": ["/app/scripts/docker_entrypoint.sh"],
                    "Cmd": ["python", "durable_ai_worker.py", "--once"],
                },
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[:4] == [
            "/usr/bin/docker", "--context=default", "container", "ls"
        ]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["/usr/bin/docker", "--context=default", "run"]:
            result = {
                "status": "admitted",
                "nonce": NONCE,
                "operation_id": OPERATION_ID,
                "provider_calls": 0,
                "anchor_created": True,
                "private_object_anchor_writes": 1,
                "private_object_anchor_reads": 1,
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
        raise AssertionError(command)


class TimeoutRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.after_timeout = False
        self.removed = False

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), kwargs.get("input")))
        if command[:4] == [
            "/usr/bin/docker", "--context=default", "image", "inspect"
        ]:
            return super().__call__(command, **kwargs)
        if command[:3] == ["/usr/bin/docker", "--context=default", "run"]:
            self.after_timeout = True
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))
        if command[:4] == [
            "/usr/bin/docker", "--context=default", "container", "ls"
        ]:
            if not self.after_timeout or self.removed:
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 0, "0123456789ab\n", "")
        if command[:4] == [
            "/usr/bin/docker", "--context=default", "container", "inspect"
        ]:
            payload = [{
                "Name": f"/{runner.CONTAINER_NAME}",
                "Image": runner.units.IMAGE_CONFIG,
                "Config": {
                    "Image": runner.units.IMAGE_REF,
                    "Labels": {
                        "com.noteai.acceptance": "durable-ai-controller-v1",
                        "com.noteai.acceptance.nonce": NONCE,
                        "com.noteai.acceptance.action": "admit",
                    },
                },
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[:5] == [
            "/usr/bin/docker",
            "--context=default",
            "container",
            "rm",
            "--force",
        ]:
            self.removed = True
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(command)


class AcceptanceControllerRunnerTests(unittest.TestCase):
    def test_direct_script_help_is_runnable_without_app_dependencies(self):
        completed = subprocess.run(
            [sys.executable, str(Path(runner.__file__).resolve()), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def _fixture(self, raw: str):
        root = Path(raw)
        api = root / "api.env"
        storage = root / "private-storage.env"
        source = root / "durable_ai_acceptance.py"
        api.write_text(
            f"DATABASE_URL={DATABASE_URL}\n"
            "ANTHROPIC_API_KEY=redacted",
            encoding="utf-8",
        )
        storage.write_text(
            "NOTEAI_PRIVATE_STORAGE_BACKEND=aliyun_oss\n"
            "NOTEAI_OSS_PRIVATE_BUCKET=synthetic-private\n"
            "NOTEAI_OSS_REGION=cn-shenzhen\n"
            "NOTEAI_OSS_ENDPOINT=https://oss-cn-shenzhen-internal.aliyuncs.com\n"
            "NOTEAI_OSS_RAM_ROLE=synthetic-role\n"
            "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH=1\n"
            "NOTEAI_OSS_KEY_PREFIX=noteai-private\n",
            encoding="utf-8",
        )
        source.write_bytes(runner.CONTROLLER_SOURCE.read_bytes())
        for path, mode in ((api, 0o600), (storage, 0o600), (source, 0o644)):
            path.chmod(mode)
        return api, storage, source

    def test_admit_streams_only_database_url_and_uses_fixed_image(self):
        with tempfile.TemporaryDirectory() as raw:
            api, storage, source = self._fixture(raw)
            fake = FakeRunner()
            result = runner.run_controller(
                "admit",
                NONCE,
                api_env=api,
                storage_env=storage,
                controller_source=source,
                expected_uid=os.geteuid(),
                require_root=False,
                lock_path=Path(raw) / "controller.lock",
                runner=fake,
            )
        self.assertEqual(result["operation_id"], OPERATION_ID)
        docker_run = next(call for call in fake.calls if call[0][2] == "run")
        command, stdin = docker_run
        flattened = " ".join(command)
        self.assertEqual(stdin, f"DATABASE_URL={DATABASE_URL}\n")
        self.assertNotIn("redacted", flattened)
        self.assertNotIn("redacted", stdin)
        self.assertNotIn(DATABASE_URL, flattened)
        self.assertIn(runner.units.IMAGE_REF, command)
        self.assertIn("--env-file=/dev/stdin", command)
        self.assertIn(
            "--env=NOTEAI_DURABLE_AI_ACCEPTANCE_MUTATION_CONFIRM="
            + runner.CONTROLLER_TASK_ID,
            command,
        )
        self.assertIn(
            f"--env={runner.CONTROLLER_CARRIER_ENV}="
            f"{runner.CONTROLLER_CARRIER_ROLE}",
            command,
        )
        self.assertNotIn("--privileged", command)

    def test_storage_env_rejects_provider_secret_or_key_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            _api, storage, _source = self._fixture(raw)
            storage.write_text(
                storage.read_text(encoding="utf-8")
                + "MOONSHOT_API_KEY=test-key",
                encoding="utf-8",
            )
            with self.assertRaises(runner.AcceptanceControllerRunnerError):
                runner._validate_storage_env(storage)

    def test_api_database_url_rejects_query_target_override(self):
        with tempfile.TemporaryDirectory() as raw:
            api, _storage, _source = self._fixture(raw)
            api.write_text(
                f"DATABASE_URL={DATABASE_URL}?host=evil.invalid\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                runner.AcceptanceControllerRunnerError,
                "api_database_url",
            ):
                runner._database_env(api)

    def test_noncanonical_nonce_is_rejected_before_docker(self):
        with tempfile.TemporaryDirectory() as raw:
            api, storage, source = self._fixture(raw)
            fake = FakeRunner()
            with self.assertRaisesRegex(
                runner.AcceptanceControllerRunnerError, "nonce_shape"
            ):
                runner.run_controller(
                    "admit",
                    "17",
                    api_env=api,
                    storage_env=storage,
                    controller_source=source,
                    expected_uid=os.geteuid(),
                    require_root=False,
                    lock_path=Path(raw) / "controller.lock",
                    runner=fake,
                )
            self.assertEqual(fake.calls, [])

    def test_delete_requires_canonical_known_operation_before_docker(self):
        with tempfile.TemporaryDirectory() as raw:
            api, storage, source = self._fixture(raw)
            fake = FakeRunner()
            with self.assertRaisesRegex(
                runner.AcceptanceControllerRunnerError,
                "operation_id",
            ):
                runner.run_controller(
                    "delete-primary",
                    NONCE,
                    api_env=api,
                    storage_env=storage,
                    controller_source=source,
                    expected_uid=os.geteuid(),
                    require_root=False,
                    lock_path=Path(raw) / "controller.lock",
                    runner=fake,
                )
            self.assertEqual(fake.calls, [])

    def test_read_only_resolvers_have_exact_arguments_and_results(self):
        resolve_admit = runner._controller_args(
            "resolve-admit",
            NONCE,
            None,
        )
        self.assertEqual(
            resolve_admit,
            ["--resolve-admit", "--nonce", NONCE],
        )
        resolved = runner._validate_result(
            "resolve-admit",
            NONCE,
            None,
            {
                "status": "admission_resolved",
                "nonce": NONCE,
                "operation_id": OPERATION_ID,
                "read_only": True,
                "provider_calls": 0,
            },
        )
        self.assertEqual(resolved["operation_id"], OPERATION_ID)
        resolve_delete = runner._controller_args(
            "resolve-delete",
            NONCE,
            OPERATION_ID,
        )
        self.assertEqual(
            resolve_delete[-2:],
            ["--operation-id", OPERATION_ID],
        )
        deleted = runner._validate_result(
            "resolve-delete",
            NONCE,
            OPERATION_ID,
            {
                "status": "primary_deleted",
                "nonce": NONCE,
                "operation_id": OPERATION_ID,
                "read_only": True,
                "provider_calls": 0,
            },
        )
        self.assertEqual(deleted["status"], "primary_deleted")

    def test_mutation_timeout_cleans_exact_container_and_is_no_retry_unknown(self):
        with tempfile.TemporaryDirectory() as raw:
            api, storage, source = self._fixture(raw)
            fake = TimeoutRunner()
            with self.assertRaisesRegex(
                runner.AcceptanceControllerRunnerError,
                "controller_mutation_outcome_unknown",
            ):
                runner.run_controller(
                    "admit",
                    NONCE,
                    api_env=api,
                    storage_env=storage,
                    controller_source=source,
                    expected_uid=os.geteuid(),
                    require_root=False,
                    lock_path=Path(raw) / "controller.lock",
                    runner=fake,
                )
            self.assertTrue(fake.removed)
            commands = [call[0] for call in fake.calls]
            self.assertIn(
                (
                    "/usr/bin/docker",
                    "--context=default",
                    "container",
                    "rm",
                    "--force",
                    "0123456789ab",
                ),
                commands,
            )

    def test_container_list_error_with_not_found_text_is_unknown(self):
        def failed_list(command, *, check, capture_output, text):
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "docker context default not found",
            )

        with self.assertRaisesRegex(
            runner.AcceptanceControllerRunnerError,
            "container_state_unknown",
        ):
            runner._container_absent(runner=failed_list)


if __name__ == "__main__":
    unittest.main()
