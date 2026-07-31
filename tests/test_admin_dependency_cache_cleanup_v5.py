from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLEANUP = ROOT / "scripts" / "ci" / "cleanup_admin_dependency_cache_v5.sh"
TRANSIENT_VERIFIER = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v5.py"
)
BASE_VERIFIER = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v4.py"
)
PRODUCER = "noteai-admin-cache-v5-producer-123"
CONSUMER = "noteai-admin-cache-v5-consumer-123"
IMAGE_BASE = f"sha256:{'a' * 64}"
IMAGE_EXTRA_1 = f"sha256:{'b' * 64}"
IMAGE_EXTRA_2 = f"sha256:{'c' * 64}"
IMAGE_EXTRA_3 = f"sha256:{'d' * 64}"
CONTAINER_BASE = "1" * 64
NETWORK_BASE = "2" * 64


class AdminDependencyCacheCleanupV5Tests(unittest.TestCase):
    def _write_executable(self, path: Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _fixture(self, root: Path) -> tuple[Path, Path, Path, dict[str, str]]:
        runner_temp = root / "runner-temp"
        runner_temp.mkdir(mode=0o700)
        docker_config = runner_temp / "noteai-empty-docker-config-v5"
        buildx_config = runner_temp / "noteai-buildx-state-v5"
        docker_config.mkdir(mode=0o700)
        buildx_config.mkdir(mode=0o700)
        config = docker_config / "config.json"
        config.write_text(
            json.dumps({"auths": {}}, indent=2) + "\n",
            encoding="utf-8",
        )
        config.chmod(0o600)

        snapshots = {
            "images": f"{IMAGE_BASE}\n",
            "containers": f"{CONTAINER_BASE}\n",
            "volumes": "volume-base\n",
            "networks": f"{NETWORK_BASE}\n",
        }
        for kind, value in snapshots.items():
            snapshot = runner_temp / f"noteai-{kind}-before"
            snapshot.write_text(
                value,
                encoding="utf-8",
            )
            snapshot.chmod(0o600)
        baseline_marker = runner_temp / "noteai-docker-baseline-v5.complete"
        baseline_marker.write_text(
            "noteai-docker-baseline-v5=complete\n",
            encoding="utf-8",
        )
        baseline_marker.chmod(0o600)

        fake_bin = root / "fake-bin"
        fake_bin.mkdir(mode=0o700)
        builder_state = root / "builder-state"
        builder_state.write_text(f"{PRODUCER}\n{CONSUMER}\n", encoding="utf-8")
        docker_log = root / "docker-invocations"
        self._write_executable(
            fake_bin / "docker",
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${NOTEAI_TEST_DOCKER_LOG}"
if [[ "${NOTEAI_TEST_SLEEP_COMMAND:-}" = "$1 $2" ]] &&
  [[ ! -e "${NOTEAI_TEST_SLEEP_ONCE_FILE:-/nonexistent}" ]]
then
  : > "${NOTEAI_TEST_SLEEP_ONCE_FILE}"
  sleep "${NOTEAI_TEST_SLEEP_SECONDS:-5}"
fi
if [[ "$1 $2" = "buildx rm" ]]; then
  builder_name="$3"
  if [[ "${NOTEAI_TEST_KEEP_BUILDER_RM:-}" = "${builder_name}" ]]; then
    exit 0
  fi
  temporary="${NOTEAI_TEST_BUILDER_STATE_FILE}.tmp"
  grep -Fvx -- "${builder_name}" \
    "${NOTEAI_TEST_BUILDER_STATE_FILE}" > "${temporary}" || true
  mv "${temporary}" "${NOTEAI_TEST_BUILDER_STATE_FILE}"
  if [[ "${NOTEAI_TEST_FAIL_BUILDER_RM_AFTER_REMOVE:-}" = "${builder_name}" ]]; then
    exit 1
  fi
  exit 0
fi
if [[ "$1 $2" = "buildx ls" ]]; then
  if [[ "${NOTEAI_TEST_FAIL_BUILDER_LIST:-0}" = "1" ]]; then
    exit 1
  fi
  cat "${NOTEAI_TEST_BUILDER_STATE_FILE}"
  exit 0
fi
case "$1 $2" in
  "image ls")
    if [[ "${NOTEAI_TEST_FAIL_IMAGE_LIST:-0}" = "1" ]]; then exit 1; fi
    printf '%s' "${NOTEAI_TEST_IMAGES}"
    ;;
  "image rm")
    image_id="${4:-${3:-}}"
    if [[ "${NOTEAI_TEST_FAIL_IMAGE_RM_ID:-}" = "${image_id}" ]]; then
      exit 1
    fi
    exit 0
    ;;
  "container ls")
    if [[ "${NOTEAI_TEST_FAIL_CONTAINER_LIST:-0}" = "1" ]]; then exit 1; fi
    printf '%s' "${NOTEAI_TEST_CONTAINERS}"
    ;;
  "volume ls")
    if [[ "${NOTEAI_TEST_FAIL_VOLUME_LIST:-0}" = "1" ]]; then exit 1; fi
    printf '%s' "${NOTEAI_TEST_VOLUMES}"
    ;;
  "network ls")
    if [[ "${NOTEAI_TEST_FAIL_NETWORK_LIST:-0}" = "1" ]]; then exit 1; fi
    printf '%s' "${NOTEAI_TEST_NETWORKS}"
    ;;
  *) exit 99 ;;
esac
""",
        )
        self._write_executable(
            fake_bin / "timeout",
            """#!/usr/bin/env python3
import os
import signal
import subprocess
import sys

arguments = sys.argv[1:]
while arguments and arguments[0].startswith("--"):
    arguments.pop(0)
if not arguments:
    raise SystemExit(125)
duration = arguments.pop(0)
if not duration.endswith("s") or not duration[:-1].isdigit():
    raise SystemExit(125)
limit = int(duration[:-1])
if os.environ.get("NOTEAI_TEST_TIMEOUT_CAP_SECONDS"):
    limit = min(limit, int(os.environ["NOTEAI_TEST_TIMEOUT_CAP_SECONDS"]))
process = subprocess.Popen(arguments, start_new_session=True)
try:
    returncode = process.wait(timeout=limit)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    raise SystemExit(124)
raise SystemExit(returncode)
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
for target in "${targets[@]}"; do
  if [[ "${NOTEAI_TEST_FAIL_RM_TARGET:-}" = "${target}" ]]; then
    exit 1
  fi
done
/bin/rm -rf "${targets[@]}"
""",
        )
        environment = os.environ.copy()
        now_epoch = int(time.time())
        environment.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                "RUNNER_TEMP": str(runner_temp),
                "DOCKER_CONFIG": str(docker_config),
                "BUILDX_CONFIG": str(buildx_config),
                "BUILDKIT_NO_CLIENT_TOKEN": "1",
                "NOTEAI_PRODUCER_BUILDER": PRODUCER,
                "NOTEAI_CONSUMER_BUILDER": CONSUMER,
                "NOTEAI_PRE_CLEANUP_DEADLINE_EPOCH": str(now_epoch + 300),
                "NOTEAI_CLEANUP_DEADLINE_EPOCH": str(now_epoch + 900),
                "NOTEAI_CLEANUP_COMMAND_TIMEOUT_SECONDS": "15",
                "NOTEAI_TEST_BUILDER_STATE_FILE": str(builder_state),
                "NOTEAI_TEST_DOCKER_LOG": str(docker_log),
                "NOTEAI_TEST_IMAGES": f"{IMAGE_BASE}\n",
                "NOTEAI_TEST_CONTAINERS": f"{CONTAINER_BASE}\n",
                "NOTEAI_TEST_VOLUMES": "volume-base\n",
                "NOTEAI_TEST_NETWORKS": f"{NETWORK_BASE}\n",
                "NOTEAI_TRANSIENT_STATE_VERIFIER_PATH": str(
                    TRANSIENT_VERIFIER
                ),
                "NOTEAI_TRANSIENT_STATE_VERIFIER_SHA256": hashlib.sha256(
                    TRANSIENT_VERIFIER.read_bytes()
                ).hexdigest(),
                "NOTEAI_V4_TRANSIENT_VERIFIER_PATH": str(BASE_VERIFIER),
                "NOTEAI_V4_TRANSIENT_VERIFIER_SHA256": hashlib.sha256(
                    BASE_VERIFIER.read_bytes()
                ).hexdigest(),
                "NOTEAI_CLEANUP_RECEIPT_PATH": str(
                    runner_temp
                    / "noteai-admin-dependency-cache-cleanup-v5.json"
                ),
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

    def _receipt(
        self,
        runner_temp: Path,
    ) -> dict[str, object]:
        return json.loads(
            (
                runner_temp
                / "noteai-admin-dependency-cache-cleanup-v5.json"
            ).read_text(encoding="utf-8")
        )

    def _assert_roots_absent(
        self,
        docker_config: Path,
        buildx_config: Path,
    ) -> None:
        self.assertFalse(os.path.lexists(docker_config))
        self.assertFalse(os.path.lexists(buildx_config))

    def test_all_pass_emits_exact_receipt_and_removes_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = self._receipt(runner_temp)
            self.assertEqual(
                set(receipt),
                {
                    "schema_version",
                    "deadline_control_valid",
                    "client_token_disabled",
                    "pre_state",
                    "producer_builder_remove",
                    "producer_builder_absent",
                    "consumer_builder_remove",
                    "consumer_builder_absent",
                    "post_builder_state",
                    "docker_baseline_state",
                    "new_images_remove",
                    "images_parity",
                    "containers_parity",
                    "volumes_parity",
                    "networks_parity",
                    "docker_root_absent",
                    "buildx_root_absent",
                    "diagnostic_files_absent",
                    "cleanup_effective",
                    "overall_pass",
                },
            )
            self.assertEqual(receipt["schema_version"], 2)
            self.assertTrue(receipt["deadline_control_valid"])
            self.assertEqual(receipt["docker_baseline_state"], "pass")
            self.assertEqual(receipt["diagnostic_files_absent"], "pass")
            self.assertTrue(receipt["cleanup_effective"])
            self.assertTrue(receipt["overall_pass"])
            self.assertEqual(receipt["pre_state"], "pass")
            self.assertEqual(receipt["post_builder_state"], "pass")
            self._assert_roots_absent(docker_config, buildx_config)

    def test_builder_remove_nonzero_but_absent_is_reported_factually(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, _, _, environment = self._fixture(Path(temporary))
            environment["NOTEAI_TEST_FAIL_BUILDER_RM_AFTER_REMOVE"] = PRODUCER
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(
                receipt["producer_builder_remove"],
                "rm_nonzero_absent_after",
            )
            self.assertEqual(receipt["producer_builder_absent"], "pass")
            self.assertTrue(receipt["cleanup_effective"])
            self.assertFalse(receipt["overall_pass"])

    def test_builder_readback_present_or_failed_fails_closed(self) -> None:
        cases = ("present", "readback_failed")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                runner_temp, docker_config, buildx_config, environment = (
                    self._fixture(Path(temporary))
                )
                if case == "present":
                    environment["NOTEAI_TEST_KEEP_BUILDER_RM"] = PRODUCER
                else:
                    environment["NOTEAI_TEST_FAIL_BUILDER_LIST"] = "1"
                result = self._run(environment)
                self.assertEqual(result.returncode, 1)
                receipt = self._receipt(runner_temp)
                expected = "fail" if case == "present" else "unknown"
                self.assertEqual(receipt["producer_builder_absent"], expected)
                self.assertFalse(receipt["cleanup_effective"])
                self._assert_roots_absent(docker_config, buildx_config)

    def test_each_parity_or_snapshot_failure_is_reported(self) -> None:
        cases = {
            "images": ("NOTEAI_TEST_IMAGES", f"{IMAGE_EXTRA_1}\n"),
            "containers": (
                "NOTEAI_TEST_CONTAINERS",
                f"{'3' * 64}\n",
            ),
            "volumes": ("NOTEAI_TEST_VOLUMES", "volume-extra\n"),
            "networks": ("NOTEAI_TEST_NETWORKS", f"{'4' * 64}\n"),
        }
        for kind, (key, value) in cases.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                runner_temp, docker_config, buildx_config, environment = (
                    self._fixture(Path(temporary))
                )
                environment[key] = value
                result = self._run(environment)
                self.assertEqual(result.returncode, 1)
                receipt = self._receipt(runner_temp)
                self.assertEqual(receipt[f"{kind}_parity"], "fail")
                self.assertFalse(receipt["cleanup_effective"])
                self._assert_roots_absent(docker_config, buildx_config)

    def test_each_snapshot_command_failure_is_unknown_and_fails_closed(
        self,
    ) -> None:
        cases = {
            "images": "NOTEAI_TEST_FAIL_IMAGE_LIST",
            "containers": "NOTEAI_TEST_FAIL_CONTAINER_LIST",
            "volumes": "NOTEAI_TEST_FAIL_VOLUME_LIST",
            "networks": "NOTEAI_TEST_FAIL_NETWORK_LIST",
        }
        for kind, key in cases.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                runner_temp, docker_config, buildx_config, environment = (
                    self._fixture(Path(temporary))
                )
                environment[key] = "1"
                result = self._run(environment)
                self.assertEqual(result.returncode, 1)
                receipt = self._receipt(runner_temp)
                self.assertEqual(receipt[f"{kind}_parity"], "unknown")
                self.assertFalse(receipt["cleanup_effective"])
                self._assert_roots_absent(docker_config, buildx_config)

    def test_new_image_removal_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            environment["NOTEAI_TEST_IMAGES"] = (
                f"{IMAGE_BASE}\n{IMAGE_EXTRA_1}\n"
            )
            environment["NOTEAI_TEST_FAIL_IMAGE_RM_ID"] = IMAGE_EXTRA_1
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["new_images_remove"], "fail")
            self.assertFalse(receipt["cleanup_effective"])
            self._assert_roots_absent(docker_config, buildx_config)

    def test_new_image_removal_attempts_every_id_after_first_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                root
            )
            environment["NOTEAI_TEST_IMAGES"] = (
                f"{IMAGE_BASE}\n"
                f"{IMAGE_EXTRA_1}\n"
                f"{IMAGE_EXTRA_2}\n"
                f"{IMAGE_EXTRA_3}\n"
            )
            environment["NOTEAI_TEST_FAIL_IMAGE_RM_ID"] = IMAGE_EXTRA_1
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["new_images_remove"], "fail")
            invocation_log = (root / "docker-invocations").read_text(
                encoding="utf-8"
            )
            for image_id in (
                IMAGE_EXTRA_1,
                IMAGE_EXTRA_2,
                IMAGE_EXTRA_3,
            ):
                self.assertIn(f"image rm -- {image_id}", invocation_log)
            self._assert_roots_absent(docker_config, buildx_config)

    def test_incomplete_baseline_never_drives_image_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                root
            )
            (runner_temp / "noteai-docker-baseline-v5.complete").unlink()
            environment["NOTEAI_TEST_IMAGES"] = (
                f"{IMAGE_BASE}\n{IMAGE_EXTRA_1}\n"
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["docker_baseline_state"], "invalid")
            self.assertEqual(receipt["new_images_remove"], "unknown")
            invocation_log = (root / "docker-invocations").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("image rm", invocation_log)
            self.assertFalse(receipt["cleanup_effective"])
            self._assert_roots_absent(docker_config, buildx_config)

    def test_blocked_docker_call_times_out_then_writes_receipt_and_cleans_roots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                root
            )
            environment["NOTEAI_TEST_SLEEP_COMMAND"] = "image ls"
            environment["NOTEAI_TEST_SLEEP_ONCE_FILE"] = str(
                root / "sleep-once"
            )
            environment["NOTEAI_TEST_SLEEP_SECONDS"] = "5"
            environment["NOTEAI_TEST_TIMEOUT_CAP_SECONDS"] = "1"
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertTrue(receipt["deadline_control_valid"])
            self.assertFalse(receipt["overall_pass"])
            self._assert_roots_absent(docker_config, buildx_config)

    def test_pre_state_drift_is_distinct_from_effective_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            sentinel = "DUMMY_SECRET_SENTINEL_48b2"
            (docker_config / ".token_seed").write_text(
                sentinel,
                encoding="utf-8",
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["pre_state"], "drift")
            self.assertEqual(receipt["post_builder_state"], "drift")
            self.assertTrue(receipt["cleanup_effective"])
            self.assertFalse(receipt["overall_pass"])
            self.assertNotIn(sentinel, result.stdout + result.stderr)
            self._assert_roots_absent(docker_config, buildx_config)

    def test_owner_nonwritable_exact_roots_are_reopened_only_for_removal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            docker_config.chmod(0o500)
            buildx_config.chmod(0o500)
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["docker_root_absent"], "pass")
            self.assertEqual(receipt["buildx_root_absent"], "pass")
            self._assert_roots_absent(docker_config, buildx_config)

    def test_verifier_drift_still_proves_cleanup_effectiveness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            environment["NOTEAI_TRANSIENT_STATE_VERIFIER_SHA256"] = "0" * 64
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["pre_state"], "verifier_unavailable")
            self.assertTrue(receipt["cleanup_effective"])
            self.assertFalse(receipt["overall_pass"])
            self._assert_roots_absent(docker_config, buildx_config)

    def test_missing_client_token_control_fails_but_cleanup_is_effective(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            environment.pop("BUILDKIT_NO_CLIENT_TOKEN")
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertFalse(receipt["client_token_disabled"])
            self.assertTrue(receipt["cleanup_effective"])
            self.assertFalse(receipt["overall_pass"])
            self._assert_roots_absent(docker_config, buildx_config)

    def test_symlink_root_is_unlinked_without_following_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                root
            )
            target = root / "outside-target"
            target.mkdir()
            marker = target / "must-survive"
            marker.write_text("keep", encoding="utf-8")
            for child in docker_config.iterdir():
                child.unlink()
            docker_config.rmdir()
            docker_config.symlink_to(target, target_is_directory=True)
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["docker_root_absent"], "pass")
            self.assertTrue(marker.exists())
            self._assert_roots_absent(docker_config, buildx_config)

    def test_one_root_removal_failure_does_not_skip_the_other_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            environment["NOTEAI_TEST_FAIL_RM_TARGET"] = str(docker_config)
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            receipt = self._receipt(runner_temp)
            self.assertEqual(receipt["docker_root_absent"], "fail")
            self.assertEqual(receipt["buildx_root_absent"], "pass")
            self.assertTrue(docker_config.exists())
            self.assertFalse(buildx_config.exists())

    def test_existing_receipt_directory_fails_after_root_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                Path(temporary)
            )
            receipt_path = Path(environment["NOTEAI_CLEANUP_RECEIPT_PATH"])
            receipt_path.mkdir()
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(
                "admin_dependency_cache_cleanup_v5=PASS",
                result.stdout,
            )
            self.assertTrue(receipt_path.is_dir())
            self._assert_roots_absent(docker_config, buildx_config)

    def test_compact_receipt_read_failure_never_prints_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                root
            )
            real_jq = shutil.which("jq")
            self.assertIsNotNone(real_jq)
            environment["NOTEAI_TEST_REAL_JQ"] = str(real_jq)
            fake_jq = root / "fake-bin" / "jq"
            self._write_executable(
                fake_jq,
                """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" = "-c" ]]; then
  exit 7
fi
exec "${NOTEAI_TEST_REAL_JQ}" "$@"
""",
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(
                "admin_dependency_cache_cleanup_v5=PASS",
                result.stdout,
            )
            self.assertTrue(
                (
                    runner_temp
                    / "noteai-admin-dependency-cache-cleanup-v5.json"
                ).is_file()
            )
            self._assert_roots_absent(docker_config, buildx_config)

    def test_unsafe_runner_temp_stops_before_recursive_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_temp, docker_config, buildx_config, environment = self._fixture(
                root
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
            environment["NOTEAI_CLEANUP_RECEIPT_PATH"] = str(
                runner_link
                / "noteai-admin-dependency-cache-cleanup-v5.json"
            )
            result = self._run(environment)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(docker_config.exists())
            self.assertTrue(buildx_config.exists())


if __name__ == "__main__":
    unittest.main()
