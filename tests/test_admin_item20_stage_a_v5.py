from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v5.sh"
V4_SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v4.sh"


class AdminItem20StageAV5Tests(unittest.TestCase):
    def test_shell_syntax_and_offline_self_test(self) -> None:
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

    def test_successor_delta_is_exact_and_minimal(self) -> None:
        v4_bytes = V4_SCRIPT.read_bytes()
        self.assertEqual(
            hashlib.sha256(v4_bytes).hexdigest(),
            "2b811021305e81c3250c4b72f7707ac5f8d4c5fcd87ab0ae93e5c671086a8c75",
        )
        v4 = v4_bytes.decode("utf-8")
        v5 = SCRIPT.read_text(encoding="utf-8")
        expected = v4
        for old, new in (
            ("admin-5335-current-v4", "admin-5335-current-v5"),
            ("noteai-admin-item20-inspect-v4", "noteai-admin-item20-inspect-v5"),
            ("noteai-admin-stage-a-v4", "noteai-admin-stage-a-v5"),
            (
                "NOTEAI_ADMIN_STAGE_A=PASS invocation=4",
                "NOTEAI_ADMIN_STAGE_A=PASS invocation=5",
            ),
        ):
            self.assertIn(old, expected)
            expected = expected.replace(old, new)

        old_scanner_block = "\n".join(
            (
                '"$task_root/tools/trivy-real" image --help > '
                '"$task_root/trivy-image-help.txt"',
                "grep -F -- '--download-db-only' "
                '"$task_root/trivy-image-help.txt" >/dev/null',
                'rm -f "$task_root/trivy-image-help.txt"',
                "timeout --foreground --signal=TERM --kill-after=30s 1200s   "
                'env DOCKER_CONFIG="$task_root/docker-empty"   '
                '"$task_root/tools/trivy-real" image     '
                '--cache-dir "$task_root/trivy-cache"     '
                "--db-repository ghcr.io/aquasecurity/trivy-db:2     "
                '--download-db-only --no-progress     '
                '>"$task_root/scanner-db.log" 2>&1',
            )
        )
        new_scanner_block = "\n".join(
            (
                '"$task_root/tools/trivy-real" image --help > '
                '"$task_root/trivy-image-help.txt"',
                "grep -F -- '--download-db-only' "
                '"$task_root/trivy-image-help.txt" >/dev/null',
                "grep -F -- '--timeout' "
                '"$task_root/trivy-image-help.txt" >/dev/null',
                'rm -f "$task_root/trivy-image-help.txt"',
                "timeout --foreground --signal=TERM --kill-after=30s 1200s \\",
                '  env DOCKER_CONFIG="$task_root/docker-empty" \\',
                '  "$task_root/tools/trivy-real" image \\',
                '    --cache-dir "$task_root/trivy-cache" \\',
                "    --db-repository ghcr.io/aquasecurity/trivy-db:2 \\",
                "    --timeout 15m \\",
                "    --download-db-only \\",
                '    2>&1 | tee "$task_root/scanner-db.log"',
            )
        )
        self.assertEqual(expected.count(old_scanner_block), 1)
        expected = expected.replace(old_scanner_block, new_scanner_block)
        self.assertEqual(v5, expected)

    def test_timeout_and_progress_contract_is_fail_closed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        scanner = source.split("phase='scanner_db_refresh'", 1)[1].split(
            "phase='admin_build_scan'",
            1,
        )[0]
        self.assertEqual(scanner.count("--timeout 15m"), 1)
        self.assertEqual(scanner.count("1200s"), 1)
        self.assertEqual(scanner.count("--download-db-only"), 2)
        self.assertNotIn("--no-progress", scanner)
        self.assertEqual(
            scanner.count('2>&1 | tee "$task_root/scanner-db.log"'),
            1,
        )
        self.assertIn("set -Eeuo pipefail", source)
        self.assertLess(scanner.index("--timeout 15m"), scanner.index("| tee"))

    def test_data_plane_and_mutation_boundary_remain_fixed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for fixed in (
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
            "38e574e56406ba3380acb78edbe784508cc537cd",
            "216be18bab10e5e0358e1f61e3f6b70bd207a8a8",
            "4e62b0627b4be73d7ccc14d821d34f01894340297729456f9f3e22b45a6e75b3",
            "639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2",
            "a2420972f187f461d283964e71cb5b5d4980f8e5251faf0489993ac7ca6df22c",
            "ghcr.io/aquasecurity/trivy-db:2",
            "NOTEAI_ADMIN_STAGE_A=PASS invocation=5",
        ):
            self.assertIn(fixed, source)
        for forbidden in (
            "registry-vpc.cn-shenzhen.cr.aliyuncs.com",
            "docker login",
            "docker push",
            "DATABASE_URL",
            "admin_sessions",
            "curl ",
            "wget ",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
