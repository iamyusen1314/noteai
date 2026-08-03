from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v3.sh"
V2_SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v2.sh"
NATIVE_SCRIPT = ROOT / "scripts" / "ci" / "native_release_evidence.sh"


class AdminItem20StageAV3Tests(unittest.TestCase):
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
            "NOTEAI_ADMIN_STAGE_A=PASS invocation=3",
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
        self.assertNotIn("admin-5335-current-v2", source)
        self.assertNotIn("NOTEAI_ADMIN_STAGE_A=PASS invocation=1", source)
        self.assertNotIn("NOTEAI_ADMIN_STAGE_A=PASS invocation=2", source)
        self.assertEqual(
            source.count('bash "$task_root/admin-native-release.sh"'),
            1,
        )
        self.assertEqual(source.count("roles=(admin)"), 2)
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

    def test_source_fetch_retry_is_exact_bounded_and_clean_room(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        matcher = source.split(
            "source_fetch_failure_is_retryable() {",
            1,
        )[1].split("\n}\n\nprepare_source_clean_room", 1)[0]
        transport = source.split("run_source_fetch_transport() {", 1)[1].split(
            "\n}\n\nfetch_source_with_retry",
            1,
        )[0]
        retry = source.split("fetch_source_with_retry() {", 1)[1].split(
            "\n}\n\noffline_self_test",
            1,
        )[0]

        self.assertIn("[ \"$fetch_rc\" = '128' ]", matcher)
        self.assertIn("[ ! -s \"$stdout_path\" ]", matcher)
        self.assertIn("sed $'s/\\r$//'", matcher)
        self.assertEqual(
            matcher.count("error: RPC failed; curl 52 Empty reply from server"),
            1,
        )
        self.assertEqual(matcher.count("fatal: expected 'packfile'"), 1)

        self.assertEqual(transport.count("--foreground"), 1)
        self.assertEqual(transport.count("--signal=TERM"), 1)
        self.assertEqual(transport.count("--kill-after=15s 300s"), 1)
        self.assertEqual(transport.count("LC_ALL=C"), 1)
        self.assertEqual(transport.count("GIT_HTTP_MAX_REQUESTS=1"), 1)
        self.assertEqual(transport.count("http.version=HTTP/1.1"), 1)
        self.assertEqual(transport.count("http.maxRequests=1"), 1)
        self.assertEqual(
            transport.count(
                'fetch --quiet --no-tags --depth=1 origin "$release"'
            ),
            1,
        )

        self.assertEqual(retry.count("for attempt in 1 2; do"), 1)
        self.assertEqual(retry.count("prepare_source_clean_room"), 1)
        self.assertEqual(retry.count("run_source_fetch_transport"), 1)
        self.assertEqual(retry.count("source_fetch_failure_is_retryable"), 1)
        self.assertNotIn("while :", retry)
        self.assertNotIn("attempt in 1 2 3", retry)
        self.assertEqual(
            source.count(
                '"$task_root" "$source_root" "$real_git" '
                '"$real_timeout" "$real_git" 2'
            ),
            1,
        )

    def test_v3_changes_only_source_transport_control_plane(self) -> None:
        v2 = V2_SCRIPT.read_text(encoding="utf-8")
        v3 = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(V2_SCRIPT.read_bytes()).hexdigest(),
            "85e4e60e40e2a3f00c7fe9d1220ec37fdce2eb2772b8ce74ee92b0249755abd6",
        )

        model_start = "phase='model_materialization'"
        success_start = "phase='success_cleanup'"
        self.assertEqual(
            v3.split(model_start, 1)[1].split(success_start, 1)[0],
            v2.split(model_start, 1)[1].split(success_start, 1)[0],
        )

        checkout_start = 'git -C "$source_root" checkout -q --detach FETCH_HEAD'
        checkout_end = 'git -C "$source_root" remote remove origin'

        def checkout_block(text: str) -> str:
            start = text.index(checkout_start)
            end = text.index(checkout_end, start) + len(checkout_end)
            return text[start:end]

        self.assertEqual(checkout_block(v3), checkout_block(v2))

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
            "http.proxy",
            "https.proxy",
            "sslVerify=false",
            "postBuffer",
        )
        for value in forbidden:
            self.assertNotIn(value, source)


if __name__ == "__main__":
    unittest.main()
