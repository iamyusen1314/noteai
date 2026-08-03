from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_public_ecr.sh"
V5_SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_a_v5.sh"


class AdminItem20StageAPublicECRTests(unittest.TestCase):
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

    def test_public_ecr_baseline_and_wheelhouse_recovery_are_fixed(self) -> None:
        v5_bytes = V5_SCRIPT.read_bytes()
        self.assertEqual(
            hashlib.sha256(v5_bytes).hexdigest(),
            "4f2e6c116694347cbfb748ac486f1ab391f9e346df155b50d45c6f158db3a249",
        )
        source = SCRIPT.read_text(encoding="utf-8")
        for expected in (
            "admin-5335-current-public-ecr",
            "noteai-admin-item20-inspect-public-ecr",
            "noteai-admin-stage-a-public-ecr",
            "NOTEAI_ADMIN_STAGE_A=PASS invocation=public-ecr",
            "public.ecr.aws/aquasecurity/trivy-db:2",
            "admin-dependency-wheelhouse-v17.zip",
            "extract_native_wheelhouse_artifact",
            "derive_wheelhouse_dockerfile",
            "--build-context \"noteai_wheelhouse=$NOTEAI_WHEELHOUSE_ROOT\"",
            "RUN --network=none --mount=type=bind,from=noteai_wheelhouse",
            "--no-cache-dir --no-index --find-links=/wheelhouse",
        ):
            self.assertIn(expected, source)
        self.assertNotIn("ghcr.io/aquasecurity/trivy-db:2", source)
        self.assertEqual(source.count("phase='wheelhouse_import'"), 1)
        self.assertEqual(source.count("NOTEAI_WHEELHOUSE_DOCKERFILE="), 1)
        self.assertEqual(source.count("NOTEAI_WHEELHOUSE_ROOT="), 1)

    def test_public_ecr_scanner_contract_remains_fail_closed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        scanner = source.split("phase='scanner_db_refresh'", 1)[1].split(
            "phase='admin_build_scan'",
            1,
        )[0]
        self.assertEqual(
            scanner.count("public.ecr.aws/aquasecurity/trivy-db:2"),
            1,
        )
        self.assertNotIn("ghcr.io/aquasecurity/trivy-db:2", scanner)
        self.assertEqual(scanner.count("--db-repository"), 1)
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
            "ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447",
            "639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2",
            "a2420972f187f461d283964e71cb5b5d4980f8e5251faf0489993ac7ca6df22c",
            "noteai-native-evidence:5335bda-admin",
            "noteai-local:git-5335bda-amd64-admin-r1",
            "NOTEAI_ADMIN_STAGE_A=PASS invocation=public-ecr",
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
            "--trusted-host",
            "--extra-index-url",
        ):
            self.assertNotIn(forbidden, source)

    def test_original_dockerfile_and_requirements_hashes_are_unchanged(self) -> None:
        self.assertEqual(
            hashlib.sha256((ROOT / "Dockerfile").read_bytes()).hexdigest(),
            "ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447",
        )
        self.assertEqual(
            hashlib.sha256(
                (ROOT / "model" / "requirements-api.txt").read_bytes()
            ).hexdigest(),
            "0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9",
        )

    def test_stage_a_requires_an_independent_native_artifact_digest(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[ \"$#\" = '3' ]", source)
        self.assertIn('wheelhouse_archive_sha256="$3"', source)
        self.assertIn(
            '"$(sha256sum "$archive_path" | awk \'{print $1}\')" = \\\n'
            '    "$expected_archive_sha256"',
            source,
        )
        self.assertNotIn(
            'wheelhouse_archive_sha256="$(sha256sum',
            source,
        )


if __name__ == "__main__":
    unittest.main()
