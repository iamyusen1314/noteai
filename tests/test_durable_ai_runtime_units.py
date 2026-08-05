import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIT_ROOT = ROOT / "deploy" / "production" / "systemd"
IMAGE_PLACEHOLDER = "@@NOTEAI_AI_WORKER_IMAGE@@"
OPERATION_PLACEHOLDER = "@@NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID@@"
ACTION_PLACEHOLDER = "@@NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION@@"


class DurableAiRuntimeUnitTests(unittest.TestCase):
    def setUp(self):
        self.units = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(UNIT_ROOT.glob("noteai-ai-*.service.template"))
        }

    def test_exact_four_unit_templates_are_hardened_and_digest_rendered(self):
        self.assertEqual(
            set(self.units),
            {
                "noteai-ai-dispatcher.service.template",
                "noteai-ai-worker.service.template",
                "noteai-ai-dispatcher-acceptance.service.template",
                "noteai-ai-worker-acceptance.service.template",
            },
        )
        for name, source in self.units.items():
            with self.subTest(name=name):
                self.assertEqual(source.count(IMAGE_PLACEHOLDER), 2)
                self.assertIn("--pull=never", source)
                self.assertIn("--user=999:999", source)
                self.assertIn("--read-only", source)
                self.assertIn("--cap-drop=ALL", source)
                self.assertIn("--security-opt=no-new-privileges:true", source)
                self.assertIn("--network=bridge", source)
                self.assertNotIn("--publish", source)
                self.assertNotIn("--privileged", source)
                self.assertNotIn("0.0.0.0", source)
                self.assertNotRegex(
                    source,
                    re.compile(r"(?i)(password|access[_-]?key|secret[_-]?key)=\S+"),
                )

    def test_baselines_are_default_suspended_and_bounded_restart(self):
        for name in (
            "noteai-ai-dispatcher.service.template",
            "noteai-ai-worker.service.template",
        ):
            source = self.units[name]
            with self.subTest(name=name):
                self.assertIn("NOTEAI_DURABLE_AI_SUSPENDED=1", source)
                self.assertIn("Restart=no", source)
                self.assertNotIn("RestartSec=", source)
                self.assertIn("ExecStartPost=/usr/bin/docker exec", source)

    def test_dispatcher_has_only_dispatcher_database_env(self):
        for name in (
            "noteai-ai-dispatcher.service.template",
            "noteai-ai-dispatcher-acceptance.service.template",
        ):
            source = self.units[name]
            with self.subTest(name=name):
                self.assertEqual(source.count("/etc/noteai/ai-dispatcher.env"), 2)
                self.assertNotIn("ai-worker.env", source)
                self.assertNotIn("private-storage.env", source)
                self.assertIn("NOTEAI_DURABLE_AI_COMPONENT=dispatcher", source)

    def test_worker_has_worker_database_and_private_storage_envs(self):
        for name in (
            "noteai-ai-worker.service.template",
            "noteai-ai-worker-acceptance.service.template",
        ):
            source = self.units[name]
            with self.subTest(name=name):
                self.assertEqual(source.count("/etc/noteai/ai-worker.env"), 2)
                self.assertEqual(
                    source.count("/etc/noteai/private-storage.env"),
                    2,
                )
                self.assertNotIn("ai-dispatcher.env", source)
                self.assertIn("NOTEAI_DURABLE_AI_COMPONENT=worker", source)

    def test_acceptance_units_are_exact_once_and_provider_free(self):
        dispatcher = self.units[
            "noteai-ai-dispatcher-acceptance.service.template"
        ]
        worker = self.units["noteai-ai-worker-acceptance.service.template"]
        for source in (dispatcher, worker):
            self.assertIn("Restart=no", source)
            self.assertIn("NOTEAI_DURABLE_AI_SUSPENDED=0", source)
            self.assertIn("NOTEAI_DURABLE_AI_ACCEPTANCE_MODE=1", source)
            self.assertEqual(source.count(OPERATION_PLACEHOLDER), 1)
            self.assertNotIn("production-v1", source)
        self.assertIn("--dispatcher-once", dispatcher)
        self.assertNotIn("--dispatcher-loop", dispatcher)
        self.assertIn("RuntimeMaxSec=120", dispatcher)
        self.assertIn("--worker-once", worker)
        self.assertNotIn("--worker-loop", worker)
        self.assertIn("RuntimeMaxSec=360", worker)
        self.assertEqual(worker.count(ACTION_PLACEHOLDER), 1)
        self.assertIn("internal-acceptance-v1", worker)


if __name__ == "__main__":
    unittest.main()
