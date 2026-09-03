import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deploy.production import durable_ai_unit_installer as installer


OPERATION_ID = "00000000-0000-4000-8000-000000000017"


class FakeRunner:
    def __init__(
        self,
        *,
        formal_root=None,
        acceptance_root=None,
        fragment_override=None,
        drop_ins="",
        container_error=None,
        unit_state="inactive",
    ):
        self.commands = []
        self.formal_root = formal_root
        self.acceptance_root = acceptance_root
        self.fragment_override = fragment_override
        self.drop_ins = drop_ins
        self.container_error = container_error
        self.unit_state = unit_state

    def __call__(self, command, *, check, capture_output, text):
        self.commands.append(tuple(command))
        if command[:4] == [
            "/usr/bin/docker", "--context=default", "image", "inspect"
        ]:
            payload = [{
                "Id": installer.IMAGE_CONFIG,
                "Os": "linux",
                "Architecture": "amd64",
                "RepoDigests": [installer.IMAGE_REF],
                "Config": {
                    "User": "noteai",
                    "Labels": {
                        "org.opencontainers.image.revision": installer.C17_COMMIT,
                        "com.noteai.runtime.role": "ai-worker",
                    },
                    "Entrypoint": ["/app/scripts/docker_entrypoint.sh"],
                    "Cmd": ["python", "durable_ai_worker.py", "--once"],
                },
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:2] == ["is-active"]:
            return subprocess.CompletedProcess(
                command,
                3,
                f"{self.unit_state}\n",
                "",
            )
        if command[1:2] == ["is-enabled"]:
            if "-acceptance." in command[2]:
                return subprocess.CompletedProcess(command, 0, "static\n", "")
            return subprocess.CompletedProcess(command, 1, "disabled\n", "")
        if command[1:2] == ["show"]:
            unit_name = command[2]
            root = (
                self.acceptance_root
                if "-acceptance." in unit_name
                else self.formal_root
            )
            return subprocess.CompletedProcess(
                command,
                0,
                "LoadState=loaded\n"
                f"FragmentPath={self.fragment_override or root / unit_name}\n"
                f"DropInPaths={self.drop_ins}\n",
                "",
            )
        if command[1:2] == ["daemon-reload"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:2] == ["reset-failed"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["/usr/bin/systemd-analyze", "verify"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:4] == [
            "/usr/bin/docker", "--context=default", "container", "ls"
        ]:
            return subprocess.CompletedProcess(
                command,
                1 if self.container_error else 0,
                "",
                self.container_error or "",
            )
        raise AssertionError(command)


class DurableAiUnitInstallerTests(unittest.TestCase):
    def test_direct_script_help_is_runnable(self):
        completed = subprocess.run(
            [sys.executable, str(Path(installer.__file__).resolve()), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_render_binds_exact_manifest_and_fixed_host_actions(self):
        dispatcher = installer.render_unit(
            "API-C", "acceptance", operation_id=OPERATION_ID
        )
        worker_c = installer.render_unit(
            "Worker-C", "acceptance", operation_id=OPERATION_ID
        )
        worker_f = installer.render_unit(
            "Worker-F", "acceptance", operation_id=OPERATION_ID
        )
        for rendered in (dispatcher, worker_c, worker_f):
            self.assertEqual(rendered.count(installer.IMAGE_REF), 2)
            self.assertNotIn("@@NOTEAI_", rendered)
            self.assertNotIn(installer.IMAGE_CONFIG, rendered)
        self.assertIn("hold_after_payload", worker_c)
        self.assertIn("fail_before_provider", worker_f)
        self.assertNotIn("NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION", dispatcher)

    def test_formal_units_are_fixed_suspended_and_accept_no_operation(self):
        for host in installer.HOST_COMPONENT:
            rendered = installer.render_unit(host, "formal")
            self.assertIn("NOTEAI_DURABLE_AI_SUSPENDED=1", rendered)
            self.assertIn("Restart=no", rendered)
            self.assertNotIn("NOTEAI_DURABLE_AI_ACCEPTANCE_MODE", rendered)
            self.assertEqual(rendered.count("ExecStartPost=/usr/bin/sleep 5"), 1)
            self.assertEqual(
                rendered.count("ExecStopPost=-/usr/bin/docker container rm"),
                1,
            )
        with self.assertRaises(installer.DurableAiUnitError):
            installer.render_unit("API-C", "acceptance", operation_id="17")

    def test_install_verify_remove_is_atomic_and_never_starts_or_enables(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal = root / "etc"
            acceptance = root / "run"
            env_root = root / "env"
            env_root.mkdir()
            worker_env = env_root / "ai-worker.env"
            worker_env.write_text(
                "DATABASE_URL=postgresql://noteai_ai_worker:synthetic@"
                "db.invalid:5432/noteai\n",
                encoding="utf-8",
            )
            storage_env = env_root / "private-storage.env"
            storage_env.write_text(
                "NOTEAI_PRIVATE_STORAGE_BACKEND=aliyun_oss\n"
                "NOTEAI_OSS_PRIVATE_BUCKET=synthetic-private\n"
                "NOTEAI_OSS_REGION=cn-shenzhen\n"
                "NOTEAI_OSS_ENDPOINT=https://oss-cn-shenzhen-internal.aliyuncs.com\n"
                "NOTEAI_OSS_RAM_ROLE=synthetic-role\n"
                "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH=1\n"
                "NOTEAI_OSS_KEY_PREFIX=noteai-private\n",
                encoding="utf-8",
            )
            for path in (worker_env, storage_env):
                path.chmod(0o600)
            runner = FakeRunner(
                formal_root=formal,
                acceptance_root=acceptance,
            )
            result = installer.install_unit(
                "Worker-C",
                "acceptance",
                operation_id=OPERATION_ID,
                formal_root=formal,
                acceptance_root=acceptance,
                env_root=env_root,
                lock_path=root / "unit.lock",
                expected_uid=os.geteuid(),
                require_root=False,
                runner=runner,
            )
            target = acceptance / "noteai-ai-worker-acceptance.service"
            self.assertEqual(result["status"], "installed")
            self.assertTrue(target.is_file())
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            verified = installer.verify_unit(
                "Worker-C",
                "acceptance",
                operation_id=OPERATION_ID,
                formal_root=formal,
                acceptance_root=acceptance,
                env_root=env_root,
                expected_uid=os.geteuid(),
                require_root=False,
                runner=runner,
            )
            self.assertEqual(verified["status"], "verified")
            removed = installer.remove_unit(
                "Worker-C",
                "acceptance",
                operation_id=OPERATION_ID,
                formal_root=formal,
                acceptance_root=acceptance,
                lock_path=root / "unit.lock",
                expected_uid=os.geteuid(),
                require_root=False,
                runner=runner,
            )
            self.assertEqual(removed["status"], "removed")
            self.assertFalse(target.exists())
            flattened = "\n".join(" ".join(command) for command in runner.commands)
            self.assertNotIn("systemctl start", flattened)
            self.assertNotIn("systemctl enable", flattened)
            self.assertNotIn("docker pull", flattened)

    def test_remove_refuses_drifted_unit(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            root.mkdir(exist_ok=True)
            target = root / "noteai-ai-dispatcher.service"
            target.write_text("drift\n", encoding="utf-8")
            target.chmod(0o644)
            with self.assertRaisesRegex(
                installer.DurableAiUnitError, "unit_contract"
            ):
                installer.remove_unit(
                    "API-C",
                    "formal",
                    formal_root=root,
                    acceptance_root=root,
                    lock_path=root / "unit.lock",
                    expected_uid=os.geteuid(),
                    require_root=False,
                    runner=FakeRunner(
                        formal_root=root,
                        acceptance_root=root,
                    ),
                )

    def test_remove_accepts_stopped_failed_acceptance_unit_and_resets_it(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "noteai-ai-worker-acceptance.service"
            target.write_text(
                installer.render_unit(
                    "Worker-C",
                    "acceptance",
                    operation_id=OPERATION_ID,
                ),
                encoding="utf-8",
            )
            target.chmod(0o644)
            fake = FakeRunner(
                formal_root=root,
                acceptance_root=root,
                unit_state="failed",
            )
            result = installer.remove_unit(
                "Worker-C",
                "acceptance",
                operation_id=OPERATION_ID,
                formal_root=root,
                acceptance_root=root,
                lock_path=root / "unit.lock",
                expected_uid=os.geteuid(),
                require_root=False,
                runner=fake,
            )
            self.assertEqual(result["status"], "removed")
            self.assertFalse(target.exists())
            self.assertIn(
                (
                    "/usr/bin/systemctl",
                    "reset-failed",
                    "noteai-ai-worker-acceptance.service",
                ),
                fake.commands,
            )

    def test_worker_env_contract_rejects_provider_or_storage_key_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            worker = root / "ai-worker.env"
            storage = root / "private-storage.env"
            worker.write_text(
                "DATABASE_URL=postgresql://noteai_ai_worker:synthetic@"
                "db.invalid:5432/noteai\n"
                "ANTHROPIC_API_KEY=placeholder",
                encoding="utf-8",
            )
            storage.write_text("TEST=synthetic\n", encoding="utf-8")
            for path in (worker, storage):
                path.chmod(0o600)
            with self.assertRaises(installer.DurableAiUnitError):
                installer._verify_env_files(
                    "Worker-C",
                    env_root=root,
                    expected_uid=os.geteuid(),
                )

    def test_environment_file_rejects_export_syntax(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "ai-worker.env"
            path.write_text(
                "export DATABASE_URL=postgresql://noteai_ai_worker:synthetic@"
                "db.invalid:5432/noteai\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                installer.DurableAiUnitError,
                "env_file_contract",
            ):
                installer._env_rows(path)

    def test_loaded_unit_must_use_exact_fragment_and_no_dropins(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "noteai-ai-dispatcher.service"
            body = installer.render_unit("API-C", "formal")
            target.write_text(body, encoding="utf-8")
            target.chmod(0o644)
            env_root = root / "env"
            env_root.mkdir()
            dispatcher = env_root / "ai-dispatcher.env"
            dispatcher.write_text(
                "DATABASE_URL=postgresql://noteai_ai_dispatcher:synthetic@"
                "db.invalid:5432/noteai\n",
                encoding="utf-8",
            )
            dispatcher.chmod(0o600)
            for fake in (
                FakeRunner(
                    formal_root=root,
                    acceptance_root=root,
                    fragment_override="/etc/systemd/system/other.service",
                ),
                FakeRunner(
                    formal_root=root,
                    acceptance_root=root,
                    drop_ins="/etc/systemd/system/noteai-ai-dispatcher.service.d/override.conf",
                ),
            ):
                with self.subTest(fake=fake), self.assertRaisesRegex(
                    installer.DurableAiUnitError,
                    "unit_not_loaded",
                ):
                    installer.verify_unit(
                        "API-C",
                        "formal",
                        formal_root=root,
                        acceptance_root=root,
                        env_root=env_root,
                        expected_uid=os.geteuid(),
                        require_root=False,
                        runner=fake,
                    )

    def test_container_inspect_error_is_not_absence(self):
        with self.assertRaisesRegex(
            installer.DurableAiUnitError,
            "container_state_unknown",
        ):
            installer._container_absent(
                "Worker-C",
                "formal",
                runner=FakeRunner(
                    container_error="docker context default not found"
                ),
            )


if __name__ == "__main__":
    unittest.main()
