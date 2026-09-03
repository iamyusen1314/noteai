from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v2.sh"
NATIVE_SCRIPT = ROOT / "scripts" / "ci" / "native_release_evidence.sh"


class AdminItem20StageAV2Tests(unittest.TestCase):
    def test_shell_syntax_and_host_python_free_offline_fixtures(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--offline-self-test", str(ROOT)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout,
            "NOTEAI_ADMIN_STAGE_A_OFFLINE_SELF_TEST=PASS\n",
        )
        self.assertEqual(result.stderr, "")

    def test_exact_5335_data_plane_anchors_remain_fixed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        expected_once = (
            "release='5335bdaed933b1f999b5f819c047ec50c11821ae'",
            "release_tree='38e574e56406ba3380acb78edbe784508cc537cd'",
            "release_version='git-5335bda-amd64-r1'",
            "canonical_image='noteai-native-evidence:5335bda-admin'",
            "local_image='noteai-local:git-5335bda-amd64-admin-r1'",
            "ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447",
            "NOTEAI_ADMIN_STAGE_A=PASS invocation=2",
        )
        for value in expected_once:
            self.assertEqual(source.count(value), 1, value)
        self.assertEqual(
            source.count("639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2"),
            2,
        )
        self.assertEqual(
            source.count("a2420972f187f461d283964e71cb5b5d4980f8e5251faf0489993ac7ca6df22c"),
            2,
        )

        self.assertNotIn("python3", source)
        self.assertNotIn("fromisoformat", source)
        self.assertNotIn("NOTEAI_STAGE_A_NOW_EPOCH", source)
        self.assertNotIn("admin-5335-current-v1", source)
        self.assertNotIn("NOTEAI_ADMIN_STAGE_A=PASS invocation=1", source)
        self.assertEqual(
            source.count('bash "$task_root/admin-native-release.sh"'),
            1,
        )
        self.assertEqual(source.count("roles=(admin)"), 2)
        self.assertEqual(source.count("git -C \"$source_root\" fetch"), 1)
        self.assertEqual(source.count("--download-db-only --no-progress"), 1)
        self.assertIn(
            "'\"1970-01-01T00:00:00Z\" | fromdateiso8601'",
            source,
        )

        native_bytes = NATIVE_SCRIPT.read_bytes()
        self.assertEqual(
            hashlib.sha256(native_bytes).hexdigest(),
            "639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2",
        )
        native_source = native_bytes.decode("utf-8")
        self.assertEqual(native_source.count("docker buildx build"), 1)
        self.assertEqual(native_source.count("--pull"), 1)
        self.assertEqual(native_source.count("--platform linux/amd64"), 1)
        self.assertEqual(native_source.count("--target \"${target}\""), 1)
        self.assertEqual(native_source.count("--load"), 1)

    def test_executor_has_no_registry_or_production_mutation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        forbidden = (
            "registry-vpc.cn-shenzhen.cr.aliyuncs.com",
            "docker login",
            "docker push",
            "systemctl restart noteai-admin",
            "noteai-admin.service",
            "admin_sessions",
            "127.0.0.1:8001",
            "aliyun",
        )
        for value in forbidden:
            self.assertNotIn(value, source)


if __name__ == "__main__":
    unittest.main()
