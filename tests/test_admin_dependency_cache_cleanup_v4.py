from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLEANUP = ROOT / "scripts" / "ci" / "cleanup_admin_dependency_cache_v4.sh"
TRANSIENT_VERIFIER = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v4.py"
)


class AdminDependencyCacheCleanupV4Tests(unittest.TestCase):
    def _write_executable(self, path: Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _fixture(self, root: Path) -> tuple[Path, Path, Path, dict[str, str]]:
        runner_temp = root / "runner-temp"
        runner_temp.mkdir(mode=0o700)
        docker_config = runner_temp / "noteai-empty-docker-config-v4"
        buildx_config = runner_temp / "noteai-buildx-state-v4"
        docker_config.mkdir(mode=0o700)
        buildx_config.mkdir(mode=0o700)
        config = docker_config / "config.json"
        config.write_text(
            json.dumps({"auths": {}}, indent=2) + "\n",
            encoding="utf-8",
        )
        config.chmod(0o600)

        snapshots = {
            "images": "image-base\n",
            "containers": "container-base\n",
            "volumes": "volume-base\n",
            "networks": "network-base\n",
        }
        for kind, value in snapshots.items():
            (runner_temp / f"noteai-{kind}-before").write_text(
                value,
                encoding="utf-8",
            )

        fake_bin = root / "fake-bin"
        fake_bin.mkdir(mode=0o700)
        self._write_executable(
            fake_bin / "docker",
            """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" = "buildx rm" ]]; then
  if [[ "${NOTEAI_TEST_FAIL_BUILDER:-}" = "$3" ]]; then
    exit 1
  fi
  exit 0
fi
case "$1 $2" in
  "image ls") printf '%s' "${NOTEAI_TEST_IMAGES:-image-base
}" ;;
  "image rm") exit 0 ;;
  "container ls") printf 'container-base\\n' ;;
  "volume ls") printf 'volume-base\\n' ;;
  "network ls") printf 'network-base\\n' ;;
  *) exit 99 ;;
esac
""",
        )
        self._write_executable(
            fake_bin / "rm",
            """#!/usr/bin/env bash
set -euo pipefail
targets=()
for value in "$@"; do
  case "${value}" in
    -*) ;;
    *) targets+=("${value}") ;;
  esac
done
/bin/rm -rf "${targets[@]}"
""",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                "RUNNER_TEMP": str(runner_temp),
                "DOCKER_CONFIG": str(docker_config),
                "BUILDX_CONFIG": str(buildx_config),
                "NOTEAI_PRODUCER_BUILDER": "noteai-v4-producer",
                "NOTEAI_CONSUMER_BUILDER": "noteai-v4-consumer",
                "NOTEAI_TRANSIENT_STATE_VERIFIER_PATH": str(
                    TRANSIENT_VERIFIER
                ),
                "NOTEAI_TRANSIENT_STATE_VERIFIER_SHA256": hashlib.sha256(
                    TRANSIENT_VERIFIER.read_bytes()
                ).hexdigest(),
            }
        )
        return runner_temp, docker_config, buildx_config, environment

    def _run(self, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(CLEANUP)],
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _assert_roots_absent(
        self,
        docker_config: Path,
        buildx_config: Path,
    ) -> None:
        self.assertFalse(docker_config.exists())
        self.assertFalse(buildx_config.exists())

    def test_all_pass_removes_both_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "admin_dependency_cache_cleanup=PASS",
                result.stdout,
            )
            self._assert_roots_absent(docker_config, buildx_config)

    def test_missing_verifier_fails_after_removing_both_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = (
                self._fixture(Path(temporary))
            )
            environment["NOTEAI_TRANSIENT_STATE_VERIFIER_PATH"] = str(
                runner_temp / "missing-verifier.py"
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            self.assertIn("verifier unavailable", result.stderr)
            self._assert_roots_absent(docker_config, buildx_config)

    def test_drifted_verifier_fails_after_removing_both_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            environment["NOTEAI_TRANSIENT_STATE_VERIFIER_SHA256"] = "0" * 64
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            self.assertIn("verifier drift", result.stderr)
            self._assert_roots_absent(docker_config, buildx_config)

    def test_verifier_failure_still_removes_both_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            (docker_config / "unexpected").write_text(
                "must fail validation",
                encoding="utf-8",
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            self._assert_roots_absent(docker_config, buildx_config)

    def test_builder_or_snapshot_failure_still_removes_both_roots(self) -> None:
        cases = ("builder", "snapshot", "parity")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                runner_temp, docker_config, buildx_config, environment = (
                    self._fixture(Path(temporary))
                )
                if case == "builder":
                    environment["NOTEAI_TEST_FAIL_BUILDER"] = (
                        "noteai-v4-producer"
                    )
                elif case == "snapshot":
                    (
                        runner_temp / "noteai-containers-before"
                    ).unlink()
                else:
                    environment["NOTEAI_TEST_IMAGES"] = "image-extra\n"
                result = self._run(environment)
                self.assertEqual(result.returncode, 1)
                self._assert_roots_absent(docker_config, buildx_config)

    def test_symlinked_runner_temp_is_rejected_without_recursive_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_temp, docker_config, buildx_config, environment = (
                self._fixture(root)
            )
            runner_link = root / "runner-link"
            runner_link.symlink_to(runner_temp, target_is_directory=True)
            environment["RUNNER_TEMP"] = str(runner_link)
            environment["DOCKER_CONFIG"] = str(
                runner_link / docker_config.name
            )
            environment["BUILDX_CONFIG"] = str(
                runner_link / buildx_config.name
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(docker_config.exists())
            self.assertTrue(buildx_config.exists())


if __name__ == "__main__":
    unittest.main()
