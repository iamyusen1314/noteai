from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v4.sh"
V3_SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v3.sh"
NATIVE_SCRIPT = ROOT / "scripts" / "ci" / "native_release_evidence.sh"


class AdminItem20StageAV4Tests(unittest.TestCase):
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

    def test_exact_release_and_incremental_bundle_anchors_are_fixed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        expected_once = (
            "release='5335bdaed933b1f999b5f819c047ec50c11821ae'",
            "release_tree='38e574e56406ba3380acb78edbe784508cc537cd'",
            "prior_release='b55f11882100e9ef919522540729e366a511f88f'",
            "prior_tree='ad3c949ae585ed529854d47a8599b7cb36a25ab2'",
            "release_parent='216be18bab10e5e0358e1f61e3f6b70bd207a8a8'",
            "source_bundle_size='159507'",
            (
                "source_bundle_sha256="
                "'4e62b0627b4be73d7ccc14d821d34f01894340297729456f9f3e22b45a6e75b3'"
            ),
            "source_delta_commit_count='11'",
            "NOTEAI_ADMIN_STAGE_A=PASS invocation=4",
        )
        for value in expected_once:
            self.assertEqual(source.count(value), 1, value)

        self.assertEqual(
            source.count(
                "639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2"
            ),
            2,
        )
        self.assertEqual(
            source.count(
                "a2420972f187f461d283964e71cb5b5d4980f8e5251faf0489993ac7ca6df22c"
            ),
            2,
        )
        self.assertEqual(
            hashlib.sha256(NATIVE_SCRIPT.read_bytes()).hexdigest(),
            "639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2",
        )
        self.assertEqual(
            hashlib.sha256(V3_SCRIPT.read_bytes()).hexdigest(),
            "562cceb3f6b08da0b8e0723e4b636d664b6fc67cf622c6da3061601ee8b3f31a",
        )

        self.assertNotIn("python3", source)
        self.assertNotIn("fromisoformat", source)
        self.assertNotIn("NOTEAI_STAGE_A_NOW_EPOCH", source)
        self.assertNotIn("NOTEAI_ADMIN_STAGE_A=PASS invocation=1", source)
        self.assertNotIn("NOTEAI_ADMIN_STAGE_A=PASS invocation=2", source)
        self.assertNotIn("NOTEAI_ADMIN_STAGE_A=PASS invocation=3", source)
        self.assertNotIn("admin-5335-current-v1", source)
        self.assertNotIn("admin-5335-current-v2", source)
        self.assertNotIn("admin-5335-current-v3", source)
        self.assertEqual(
            source.count('bash "$task_root/admin-native-release.sh"'),
            1,
        )
        self.assertEqual(source.count("roles=(admin)"), 2)
        self.assertEqual(source.count("--download-db-only --no-progress"), 1)

    def test_source_transport_is_local_exact_and_non_retrying(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        transport = source.split("prepare_source_from_bundle() {", 1)[1].split(
            "\n}\n\noffline_self_test",
            1,
        )[0]
        production = source.split("phase='source_bundle_import'", 1)[1].split(
            "phase='model_materialization'",
            1,
        )[0]

        self.assertIn("[ -f \"$bundle_path\" ] && [ ! -L \"$bundle_path\" ]", transport)
        self.assertIn('wc -c < "$bundle_path"', transport)
        self.assertIn('sha256sum "$bundle_path"', transport)
        self.assertEqual(transport.count("bundle list-heads"), 1)
        self.assertEqual(transport.count("bundle verify"), 1)
        self.assertEqual(transport.count("fetch --quiet --no-tags"), 2)
        self.assertEqual(transport.count("GIT_ALLOW_PROTOCOL=file"), 2)
        self.assertGreaterEqual(transport.count("GIT_NO_LAZY_FETCH=1"), 4)
        self.assertIn(r"extensions\.partialclone", source)
        self.assertIn("promisor", source)
        self.assertIn("GIT_NO_REPLACE_OBJECTS=1", source)
        self.assertIn("GIT_ALTERNATE_OBJECT_DIRECTORIES", source)
        self.assertIn("GIT_EXEC_PATH", source)
        self.assertIn("GIT_TEMPLATE_DIR", source)
        self.assertIn("refs/replace", source)
        self.assertIn("objects/info/alternates", source)
        self.assertIn("fsck --strict --full", source)
        self.assertIn("fsck --strict --full", transport)
        self.assertIn("rev-list --count \"$prior_release..HEAD\"", transport)
        self.assertIn("rev-list --count HEAD", transport)
        self.assertIn("merge-base --is-ancestor", transport)
        self.assertIn("status --porcelain=v1 --untracked-files=all", transport)
        self.assertIn("[ -z \"$(\"$git_bin\" -C \"$destination\" remote)\" ]", transport)

        self.assertEqual(production.count("prepare_source_from_bundle"), 1)
        self.assertIn('"$source_bundle_size" "$source_bundle_sha256"', production)
        self.assertNotIn("for attempt", transport)
        self.assertNotIn("while :", transport)
        self.assertNotIn("sleep ", transport)
        self.assertNotIn("http.version", source)
        self.assertNotIn("http.maxRequests", source)
        self.assertNotIn("source_fetch", source)
        self.assertNotIn("curl 52", source)
        self.assertNotIn("https://github.com/iamyusen1314/noteai.git", source)
        self.assertIn(
            "/root/noteai-admin-stage-a-v4-transfer/source.bundle",
            source,
        )
        self.assertEqual(source.count("git clone -q --bare --shared"), 2)
        self.assertIn('second_maker_repo="$fixture_root/second-maker.git"', source)
        self.assertEqual(source.count("bundle create"), 2)
        self.assertEqual(source.count('cmp "$fixture_bundle"'), 1)

    def test_v4_changes_only_source_transport_before_materialization(self) -> None:
        v3 = V3_SCRIPT.read_text(encoding="utf-8")
        v4 = SCRIPT.read_text(encoding="utf-8")
        model_loop = "while IFS='|' read -r sha size rel; do"
        tool_prep = "phase='tool_prep'"
        success = "phase='success_cleanup'"
        v3_production = v3.split("phase='model_materialization'", 1)[1]
        v4_production = v4.split("phase='model_materialization'", 1)[1]

        self.assertEqual(
            v4_production.split(model_loop, 1)[1].split(success, 1)[0],
            v3_production.split(model_loop, 1)[1].split(success, 1)[0],
        )
        self.assertEqual(
            v4_production.split(tool_prep, 1)[1].split(success, 1)[0],
            v3_production.split(tool_prep, 1)[1].split(success, 1)[0],
        )

        native_source = NATIVE_SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(native_source.count("docker buildx build"), 1)
        self.assertEqual(native_source.count("--pull"), 1)
        self.assertEqual(native_source.count("--platform linux/amd64"), 1)
        self.assertEqual(native_source.count('--target "${target}"'), 1)
        self.assertEqual(native_source.count("--load"), 1)
        self.assertIn('if [[ -e "${NOTEAI_EVIDENCE_DIR}" ]]; then', native_source)
        self.assertIn('mkdir -p "${NOTEAI_EVIDENCE_DIR}"', native_source)
        self.assertNotIn(
            'install -d -o root -g root -m 0700 "$task_root" "$evidence_root"',
            v4,
        )
        self.assertEqual(
            v4.count('install -d -o root -g root -m 0700 "$task_root"'),
            1,
        )

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
