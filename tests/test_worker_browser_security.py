import asyncio
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
sys.path.insert(0, str(MODEL_DIR))

import chromium_security  # noqa: E402


SECCOMP_PATH = ROOT / "deploy" / "security" / "playwright-chromium-seccomp-v1.56.0.json"
SECCOMP_SHA256 = "cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849"


class WorkerBrowserSecurityTests(unittest.TestCase):
    def test_sync_launch_forces_sandbox(self):
        class Chromium:
            def __init__(self):
                self.kwargs = None

            def launch(self, **kwargs):
                self.kwargs = kwargs
                return object()

        chromium = Chromium()
        chromium_security.launch_chromium(
            chromium,
            headless=True,
            args=["--disable-gpu"],
        )

        self.assertIs(chromium.kwargs["chromium_sandbox"], True)
        self.assertEqual(chromium.kwargs["args"], ["--disable-gpu"])

    def test_async_launch_forces_sandbox(self):
        class Chromium:
            def __init__(self):
                self.kwargs = None

            async def launch(self, **kwargs):
                self.kwargs = kwargs
                return object()

        chromium = Chromium()
        asyncio.run(chromium_security.launch_chromium_async(chromium, headless=True))

        self.assertIs(chromium.kwargs["chromium_sandbox"], True)

    def test_sandbox_bypass_options_are_rejected_before_launch(self):
        class Chromium:
            def __init__(self):
                self.calls = 0

            def launch(self, **_kwargs):
                self.calls += 1

        for flag in sorted(chromium_security.FORBIDDEN_CHROMIUM_FLAGS):
            with self.subTest(flag=flag):
                chromium = Chromium()
                with self.assertRaisesRegex(ValueError, "Forbidden Chromium"):
                    chromium_security.launch_chromium(chromium, args=[f"{flag}=true"])
                self.assertEqual(chromium.calls, 0)

        chromium = Chromium()
        with self.assertRaisesRegex(ValueError, "must remain enabled"):
            chromium_security.launch_chromium(chromium, chromium_sandbox=False)
        self.assertEqual(chromium.calls, 0)

    def test_sandbox_launch_failure_has_no_unsandboxed_retry(self):
        class Chromium:
            def __init__(self):
                self.calls = []

            def launch(self, **kwargs):
                self.calls.append(kwargs)
                raise RuntimeError("sandbox unavailable")

        chromium = Chromium()
        with self.assertRaisesRegex(RuntimeError, "sandbox unavailable"):
            chromium_security.launch_chromium(chromium, headless=True)

        self.assertEqual(len(chromium.calls), 1)
        self.assertIs(chromium.calls[0]["chromium_sandbox"], True)

    def test_all_repository_browser_launches_use_guard(self):
        sources = {
            name: (MODEL_DIR / name).read_text(encoding="utf-8")
            for name in ("crawler.py", "download_covers.py", "scheduler_a.py")
        }
        combined = "\n".join(sources.values())

        self.assertNotIn(".chromium.launch(", combined)
        self.assertEqual(sum(text.count("launch_chromium_async(") for text in sources.values()), 4)
        self.assertEqual(sources["download_covers.py"].count("launch_chromium("), 0)
        for flag in chromium_security.FORBIDDEN_CHROMIUM_FLAGS:
            self.assertNotIn(flag, combined)

    def test_vendored_playwright_seccomp_profile_is_pinned_and_fail_closed(self):
        raw = SECCOMP_PATH.read_bytes()
        profile = json.loads(raw)

        self.assertEqual(hashlib.sha256(raw).hexdigest(), SECCOMP_SHA256)
        self.assertEqual(profile["defaultAction"], "SCMP_ACT_ERRNO")
        self.assertIn("SCMP_ARCH_X86_64", {item["architecture"] for item in profile["archMap"]})
        self.assertTrue(any(
            {"clone", "setns", "unshare"}.issubset(set(rule.get("names", ())))
            and rule.get("action") == "SCMP_ACT_ALLOW"
            for rule in profile["syscalls"]
        ))

    def test_compose_production_roles_are_browser_free(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertEqual(compose.count("no-new-privileges:true"), 4)
        self.assertEqual(compose.count("privileged: false"), 4)
        self.assertEqual(compose.count('user: "999:999"'), 4)
        self.assertEqual(compose.count("read_only: true"), 4)
        self.assertEqual(compose.count("cap_drop:"), 4)
        self.assertNotIn("seccomp=", compose)
        self.assertNotIn("target: worker-runtime", compose)
        self.assertNotIn("FROM runtime-common AS worker-runtime", dockerfile)
        self.assertNotIn("python -m playwright install", dockerfile)
        self.assertNotIn("privileged: true", compose)
        self.assertNotIn("cap_add:", compose)
        self.assertNotIn("devices:", compose)
        self.assertNotIn("seccomp=unconfined", compose)
        self.assertNotIn("SYS_ADMIN", compose)


if __name__ == "__main__":
    unittest.main()
